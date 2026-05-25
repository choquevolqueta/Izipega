"""
server.py
---------
Servidor local FastAPI para la extension "Izipega".

La extension funciona en cualquier sitio web: detecta campos del formulario
(inputs, textareas, selects, radios, checkboxes), los manda aqui, y devuelve
respuestas generadas con IA + el perfil del usuario.

Opcionalmente: si el usuario esta en una pagina de oferta de empleo y quiere
pre-analizarla, /analizar guarda un "contexto" (titulo, descripcion, score
de idoneidad, keywords) que enriquece las respuestas posteriores de /rellenar.

Sin contexto, /rellenar tambien funciona: solo usa el perfil + la pregunta.

Esta version usa Gemini (primario) + Groq (fallback). Las API keys se
configuran desde la extension via POST /configurar_keys, que escribe el .env
local y reinicia los clientes IA.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader

from ia_client import get_ia, reload_ia

# ──────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
LOG_FILE = f"logs/server_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("server")

# ──────────────────────────────────────────────────────────────────
# PERFIL
# ──────────────────────────────────────────────────────────────────
PERFIL_PATH = Path(__file__).parent / "perfil.json"
ENV_PATH = Path(__file__).parent / ".env"


def _construir_perfil_resumido(p: dict) -> str:
    estudios = p.get("estudios") or [{}]
    primer_estudio = estudios[0] if estudios else {}
    idiomas = p.get("idiomas") or []
    return (
        f"Nombre: {p.get('nombre', '')}\n"
        f"Edad: {p.get('edad', '')}\n"
        f"Ciudad: {p.get('ciudad', '')}, {p.get('comuna', '')}\n"
        f"Profesion: {primer_estudio.get('titulo', '')}\n"
        f"Perfil: {(p.get('perfil_profesional') or '')[:300]}\n"
        f"Habilidades: {', '.join((p.get('habilidades') or [])[:6])}\n"
        f"Idiomas: {', '.join((i.get('idioma', '') + ' ' + i.get('nivel', '')) for i in idiomas)}"
    )


with open(PERFIL_PATH, encoding="utf-8") as f:
    PERFIL = json.load(f)

PERFIL_RESUMIDO = _construir_perfil_resumido(PERFIL)

# Schema canonico que se le muestra a la IA al extraer un perfil desde PDF.
# Un item poblado por array fija las subclaves correctas y evita que la IA
# invente nombres (p.ej. "puesto" en vez de "cargo", o idiomas como strings).
SCHEMA_EJEMPLO = {
    "nombre": "Nombre Apellido",
    "edad": 30,
    "ciudad": "Santiago",
    "comuna": "Providencia",
    "telefono": "+56 9 1234 5678",
    "email": "correo@ejemplo.com",
    "nacionalidad": "Chilena",
    "perfil_profesional": "Breve resumen profesional de 2-4 oraciones.",
    "experiencia": [
        {
            "cargo": "Titulo del puesto",
            "empresa": "Nombre de la empresa",
            "ubicacion": "Ciudad, Pais",
            "periodo": "Marzo 2020 - Marzo 2025",
            "descripcion": "Descripcion de tareas y logros, en un solo string."
        }
    ],
    "estudios": [
        {
            "titulo": "Carrera o titulo obtenido",
            "institucion": "Nombre de la institucion",
            "ubicacion": "Ciudad, Pais",
            "anio_egreso": 2023
        }
    ],
    "habilidades": ["habilidad 1", "habilidad 2"],
    "herramientas": ["herramienta 1", "herramienta 2"],
    "idiomas": [
        {"idioma": "Español", "nivel": "Nativo"}
    ],
    "motivacion": "Texto motivacional...",
    "disponibilidad": "inmediata",
    "expectativa_sueldo": "a convenir",
    "modalidad_preferida": "presencial, hibrido o remoto",
    "fortalezas": ["fortaleza 1", "fortaleza 2"],
    "redes": {
        "linkedin": "https://www.linkedin.com/in/usuario",
        "portafolio_web": "https://miportafolio.com",
        "behance": "https://www.behance.net/usuario"
    },
    "respuestas_extra": {
        "por_que_este_cargo": "...",
        "licencia_conducir": "si/no",
        "residencia_legal": "..."
    },
    "cv_archivo": "nombre_del_archivo.pdf"
}

IA = get_ia()

# ──────────────────────────────────────────────────────────────────
# CONTEXTO ACTUAL (opcional — solo si se uso /analizar)
# ──────────────────────────────────────────────────────────────────
CONTEXTO_PATH = Path(__file__).parent / "contexto_actual.json"
_CONTEXTO: dict | None = None

# ──────────────────────────────────────────────────────────────────
# PROPUESTA DE PERFIL (extraida de PDF, pendiente de aprobacion)
# ──────────────────────────────────────────────────────────────────
PROPUESTA_PATH = Path(__file__).parent / "perfil_propuesto.json"
BACKUPS_DIR = Path(__file__).parent / "perfil_backups"
BACKUPS_DIR.mkdir(exist_ok=True)


def cargar_contexto_disco() -> dict | None:
    global _CONTEXTO
    if CONTEXTO_PATH.exists():
        try:
            _CONTEXTO = json.loads(CONTEXTO_PATH.read_text(encoding="utf-8"))
            return _CONTEXTO
        except Exception:
            return None
    return None


cargar_contexto_disco()


# ──────────────────────────────────────────────────────────────────
# GESTION DE API KEYS EN .env
# ──────────────────────────────────────────────────────────────────
def _leer_env_actual() -> dict[str, str]:
    """Lee el .env actual a un dict. Si no existe, devuelve {}."""
    if not ENV_PATH.exists():
        return {}
    datos: dict[str, str] = {}
    for linea in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = linea.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        clave, _, valor = s.partition("=")
        datos[clave.strip()] = valor.strip().strip('"').strip("'")
    return datos


def _escribir_env(datos: dict[str, str]) -> None:
    """Reescribe el .env con las claves dadas. Sobrescribe el archivo."""
    lineas = [
        "# Generado por /configurar_keys desde la extension.",
        "# No se sube a git (esta en .gitignore).",
        "",
    ]
    for k, v in datos.items():
        lineas.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lineas) + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
# RESPUESTAS DIRECTAS (no gastan tokens — vienen del perfil)
# ──────────────────────────────────────────────────────────────────
def respuesta_directa(pregunta: str) -> str | None:
    t = pregunta.lower()
    extra = PERFIL.get("respuestas_extra", {})
    if any(p in t for p in ["renta", "sueldo", "pretension", "expectativa salar", "salario"]):
        return PERFIL.get("expectativa_sueldo") or None
    if any(p in t for p in ["disponibilidad", "disponible para empezar"]):
        return PERFIL.get("disponibilidad") or None
    # Combinado telefono+correo: cuando UN solo campo pide ambos datos.
    # Tiene que ir ANTES de los matches individuales para tomar prioridad.
    if any(
        p in t
        for p in [
            "datos de contacto", "informacion de contacto", "información de contacto",
            "numero y correo", "número y correo", "numero y email", "número y email",
            "telefono y correo", "teléfono y correo", "telefono y email", "teléfono y email",
            "celular y correo", "celular y email", "fono y correo",
            "contacto personal", "datos personales y de contacto",
        ]
    ):
        tel = PERFIL.get("telefono") or ""
        em = PERFIL.get("email") or ""
        if tel and em:
            return f"{tel} / {em}"
        return tel or em or None
    if any(
        p in t
        for p in [
            "telefono", "teléfono", "celular", "fono", "movil", "móvil",
            "whatsapp", "numero de contacto", "número de contacto",
            "numero telef", "número telef", "n° telef", "no. telef",
            "contacto telef",
        ]
    ):
        return PERFIL.get("telefono") or None
    if any(p in t for p in ["correo", "email", "e-mail", "mail "]):
        return PERFIL.get("email") or None
    if "comuna" in t:
        return PERFIL.get("comuna") or None
    if any(p in t for p in ["ciudad", "ubicacion", "ubicación", "donde vive", "donde resides", "lugar de residencia"]):
        return PERFIL.get("ciudad") or None
    # Eliminado: matching automatico de "edad" causaba falsos positivos en
    # campos de experiencia / necesidad / etc. que contenian la subcadena.
    if any(p in t for p in ["nombre completo", "nombre y apellido", "tu nombre", "nombres y apellidos"]):
        return PERFIL.get("nombre") or None
    if any(p in t for p in ["licencia", "conducir"]):
        return extra.get("licencia_conducir") or None
    if any(p in t for p in ["nacionalidad", "pais de origen", "país de origen"]):
        return PERFIL.get("nacionalidad") or None
    if any(p in t for p in ["residencia", "permiso de trabaj", "visa"]):
        return extra.get("residencia_legal") or None
    # Redes y portafolio
    redes = PERFIL.get("redes") or {}
    if "linkedin" in t:
        return redes.get("linkedin") or None
    if any(p in t for p in ["behance", "dribbble"]):
        return redes.get("behance") or None
    if any(p in t for p in ["portafolio", "portfolio", "sitio web", "pagina web", "página web", "página personal", "pagina personal", "sitio personal", "website", "web personal"]):
        return redes.get("portafolio_web") or None
    return None


# ──────────────────────────────────────────────────────────────────
# RESPUESTA IA (preguntas abiertas)
# ──────────────────────────────────────────────────────────────────
def _bloque_campo(campo: "Campo") -> str:
    """Bloque con TODA la informacion del campo para que la IA identifique
    inequivocamente que se le pregunta y no caiga en alucinaciones."""
    m = campo.meta
    if m is None:
        return f"- Label: {campo.label}\n"
    pares = [
        ("Label visible", m.label or campo.label),
        ("Placeholder", m.placeholder),
        ("Name (atributo HTML)", m.name),
        ("Id (atributo HTML)", m.id),
        ("Aria-label", m.aria_label),
        ("Aria-describedby (texto)", m.aria_describedby_texto),
        ("Legend del fieldset", m.legend),
        ("Texto cercano (hermanos)", m.hermanos),
        ("Tipo de input", m.tipo_input),
    ]
    lineas = [f"- {k}: {v}" for k, v in pares if v]
    return "\n".join(lineas) + "\n"


def respuesta_ia_para_pregunta(campo: "Campo", titulo_contexto: str = "", imagen_bytes: bytes | None = None) -> str:
    perfil_json = json.dumps(PERFIL, ensure_ascii=False)
    nombre = PERFIL.get("nombre", "el candidato")
    empresa_cargo = "; ".join(
        f"{e.get('empresa', '?')} = {e.get('cargo', '?')}"
        for e in PERFIL.get("experiencia", [])
    ) or "(sin experiencia registrada)"

    ctx = _CONTEXTO or {}
    if ctx:
        bloque_ctx = (
            "\nANALISIS DE LA OFERTA (referencia para responder preguntas sobre experiencia o motivacion):\n"
            f"- Cargo/tema objetivo: {ctx.get('cargo_objetivo', titulo_contexto)}\n"
            f"- Empresa o entidad: {ctx.get('empresa', '')}\n"
            f"- Que busca la oferta: {ctx.get('resumen_pedido', '')}\n"
            f"- Experiencia requerida: {ctx.get('experiencia_requerida', '')}\n"
            f"- Nivel: {ctx.get('nivel_seniority', '')}\n"
            f"- Habilidades duras pedidas: {', '.join(ctx.get('habilidades_duras', []))}\n"
            f"- Habilidades blandas pedidas: {', '.join(ctx.get('habilidades_blandas', []))}\n"
            f"- Keywords del perfil que coinciden: {', '.join(ctx.get('keywords_coincidentes', []))}\n"
            f"- Keywords pedidas que no estan en el perfil: {', '.join(ctx.get('keywords_faltantes', []))}\n"
        )
    else:
        bloque_ctx = ""

    bloque_campo = _bloque_campo(campo)
    pregunta = campo.label

    bloque_vision = (
        "\nTIENES UNA CAPTURA DE PANTALLA del formulario adjunta. Antes de responder:\n"
        "1. Localiza visualmente el campo descrito abajo en la imagen (usa label, placeholder, name, id).\n"
        "2. Lee el texto VISIBLE alrededor de ese campo (la pregunta real, no solo el HTML).\n"
        "3. Confirma que tu interpretacion de la pregunta concuerda con lo que se ve. Si el texto en la imagen contradice los atributos HTML, prefiere lo que se ve en la imagen.\n"
        "4. Solo entonces responde.\n"
        if imagen_bytes
        else ""
    )

    prompt = (
        f"Eres {nombre} completando un formulario web"
        + (f" para postular al cargo \"{titulo_contexto}\"" if titulo_contexto else "")
        + ".\n\n"
        f"PERFIL OFICIAL (tu UNICA fuente de verdad, NO existe nada fuera de esto):\n{perfil_json}\n\n"
        f"MAPEO empresa => cargo real (NUNCA mezclar):\n{empresa_cargo}\n"
        f"{bloque_ctx}"
        f"{bloque_vision}\n"
        "DATOS DEL CAMPO QUE DEBES RESPONDER (lee TODOS antes de responder; si\n"
        "el label es ambiguo, los demas atributos aclaran que se pregunta):\n"
        f"{bloque_campo}\n"
        "REGLAS ABSOLUTAS (violarlas es peor que no responder):\n"
        "1. PROHIBIDO inventar empresas, cargos, fechas, estudios, habilidades o cualquier dato que no este textualmente en el PERFIL OFICIAL.\n"
        "2. Si mencionas una empresa del perfil, el cargo que le asocies DEBE ser exactamente el que aparece en el MAPEO de arriba. NUNCA mezcles el cargo de una empresa con tareas de otra. NUNCA combines en una misma frase logros de empresas distintas como si fueran una sola.\n"
        "3. Identifica primero QUE pide el campo. Si pregunta por datos personales (nombre, telefono, correo, edad, ciudad, comuna, disponibilidad, sueldo, nacionalidad, residencia, licencia), IGNORA por completo el ANALISIS del contexto y responde SOLO con el dato del PERFIL OFICIAL. El contexto solo aplica a preguntas sobre experiencia, motivacion, encaje con el cargo, o similares.\n"
        "4. Si la pregunta es sobre experiencia, motivacion o encaje con el cargo: elige la experiencia del perfil mas relevante para el cargo_objetivo de la oferta. Si tienes varias experiencias relevantes, prioriza primero las de mas anos / mas senior, luego las mas recientes. Menciona SOLO una o dos experiencias, no listes todas.\n"
        "5. SIEMPRE que sea natural, INCLUYE 1-3 keywords coincidentes (de habilidades_duras o blandas de la oferta que TAMBIEN aparezcan en tu perfil). Usa los terminos LITERALES de la oferta — eso ayuda a pasar el filtro ATS. NO inventes habilidades que no estan en tu perfil solo porque la oferta las pide.\n"
        "6. Si nada en el perfil aplica directamente, di honestamente: \"No tengo experiencia directa en X, pero mi experiencia en Y como [cargo real] es transferible porque...\".\n"
        "7. Maximo 3 oraciones Y maximo 450 caracteres totales. Muchos sitios (Indeed) rechazan respuestas mas largas de 500 caracteres. Se conciso. Primera persona, profesional. PROHIBIDO empezar con: \"Claro\", \"Por supuesto\", \"Con gusto\", \"Como [profesion]\", o cualquier muletilla introductoria. Sin saludos ni firmas.\n\n"
        f"Pregunta principal del campo: {pregunta}\n\n"
        "Responde SOLO con la respuesta directa (sin comillas, sin etiquetas, sin explicar por que respondes asi)."
    )
    fallback = PERFIL.get("respuestas_extra", {}).get(
        "por_que_este_cargo",
        "Cuento con la experiencia y disponibilidad descritas en mi perfil.",
    )
    if imagen_bytes:
        return IA.vision(prompt, imagen_bytes, fallback=fallback)
    return IA.chat(prompt, fallback=fallback, max_tokens=250)


# ──────────────────────────────────────────────────────────────────
# ANALISIS DE CONTEXTO (opcional)
# ──────────────────────────────────────────────────────────────────
def analizar_contexto_logic(titulo: str, descripcion: str, imagen_bytes: bytes | None = None) -> dict:
    global _CONTEXTO
    # Limpieza incondicional: cada "Analizar" parte de cero, asi el usuario
    # no tiene que apretar "Olvidar contexto" antes de cambiar de oferta.
    _CONTEXTO = None
    try:
        if CONTEXTO_PATH.exists():
            CONTEXTO_PATH.unlink()
    except Exception as e:
        log.warning(f"analizar_contexto: no pude borrar {CONTEXTO_PATH.name}: {e}")

    if not titulo and not descripcion and not imagen_bytes:
        return {}

    perfil_json = json.dumps(PERFIL, ensure_ascii=False)

    bloque_vision = (
        "\nTIENES UNA CAPTURA DE PANTALLA del navegador del usuario adjunta.\n"
        "Reglas para usar la imagen:\n"
        "1. Si hay un MODAL/DIALOG/POPUP abierto al frente (lightbox con la oferta abierta), enfocate SOLO en su contenido. Ignora el listado o sidebar de busqueda que este detras.\n"
        "2. Si el texto adjunto incluye 'X.XXX ofertas' u otros indicadores de pagina de busqueda PERO la imagen muestra UNA oferta concreta abierta, confia en la imagen: NO es generica.\n"
        "3. Si texto e imagen estan en conflicto, prefiere la imagen para identificar cual es la oferta visible.\n"
        "4. El texto adjunto se queda como respaldo: usa la imagen para identificar el contexto, y el texto para detalles que la imagen no muestra (descripcion completa, requisitos, etc.).\n"
        if imagen_bytes
        else ""
    )

    prompt = (
        "Eres un analizador ATS senior. Tu trabajo es DISECCIONAR una oferta"
        " de empleo y separar lo que un reclutador realmente evalua (skills,"
        " experiencia, nivel) del ruido logistico (jornada, horario, sueldo,"
        " ubicacion, beneficios).\n\n"
        " Devuelve SOLO JSON valido (sin texto extra, sin ```).\n\n"
        f"{bloque_vision}"
        f"TEXTO DE LA OFERTA:\nTitulo: {titulo}\nDescripcion: {descripcion[:6000]}\n\n"
        f"PERFIL COMPLETO DEL CANDIDATO:\n{perfil_json}\n\n"
        "Devuelve este JSON exacto (todas las claves obligatorias):\n"
        "{\n"
        '  "cargo_objetivo": "titulo del cargo segun la oferta",\n'
        '  "empresa": "empresa o entidad que publica (vacio si no aplica)",\n'
        '  "resumen_pedido": "1-2 oraciones, SOLO sobre el rol y responsabilidades. NO menciones jornada/horario/sueldo.",\n'
        '  "experiencia_requerida": "anos minimos y/o tipo de experiencia que pide la oferta. Ejemplo: \'3+ anos en ventas B2B\' o \'experiencia previa en cadena de frio\'. Vacio si no se menciona.",\n'
        '  "nivel_seniority": "junior | semi-senior | senior | sin especificar",\n'
        '  "habilidades_duras": ["lista de skills tecnicas / conocimientos especificos / herramientas / certificaciones que la oferta pide. Ej: \'Salesforce CRM\', \'Excel intermedio\', \'manejo de cadena de frio\', \'ingles B2\'"],\n'
        '  "habilidades_blandas": ["SOLO las que la oferta menciona explicitamente. Ej: \'orientacion al cliente\', \'trabajo bajo presion\', \'liderazgo\'. NO inventes."],\n'
        '  "keywords_ats": ["union de habilidades_duras + blandas + experiencia + nivel. SIN ruido logistico (jornada, horario, sueldo, ubicacion, contrato, beneficios). 10-15 terminos."],\n'
        '  "keywords_coincidentes": ["keywords del perfil que aparecen en la oferta (cualquiera de las 3 categorias)"],\n'
        '  "keywords_faltantes": ["keywords de la oferta que NO estan en el perfil"],\n'
        '  "score_idoneidad": 0-100,\n'
        '  "justificacion": "2-3 oraciones: que pesa a favor y que pesa en contra. Honesto, no inflado."\n'
        "}\n\n"
        "REGLAS DE EXTRACCION (criticas):\n"
        "- Distingue DURAS de BLANDAS. Duras = se aprenden y se demuestran (herramienta, idioma, certificacion, conocimiento de sector). Blandas = rasgos personales (comunicacion, liderazgo, proactividad).\n"
        "- NO incluyas en NINGUNA categoria: jornada (full-time, part-time, turnos), horario, sueldo, beneficios, ubicacion, tipo de contrato, modalidad (remoto/presencial). Eso es metadata, no skills.\n"
        "- Si una habilidad blanda no esta escrita EN LA OFERTA, NO la inventes (aunque sea obvia para el rol).\n"
        "- Si la oferta es CORTA pero concreta (cargo claro + alguna descripcion), igual extrae lo que puedas. Una oferta corta NO es generica.\n"
        "- Solo marca generica (score=0, justificacion='es un listado, no una oferta unica') si el texto es realmente una PAGINA DE BUSQUEDA con multiples ofertas distintas listadas, o un aviso vacio sin descripcion del rol.\n\n"
        "CRITERIOS PARA EL SCORE (0-100):\n"
        "- 90-100: encaja casi perfecto (mayoria de habilidades_duras + experiencia + anos).\n"
        "- 70-89: encaja bien. Falta 1-2 cosas no criticas o tiene experiencia transferible solida.\n"
        "- 50-69: encaja parcialmente. Faltan habilidades clave o menos experiencia de la pedida pero hay base.\n"
        "- 30-49: encaja poco. Faltan varias habilidades duras o la experiencia es de otro sector.\n"
        "- 0-29: no encaja. Cambio total de carrera o sin habilidades duras requeridas.\n"
    )

    if imagen_bytes and IA.vision_disponible():
        log.info(f"analizar_contexto: usando VISION ({len(imagen_bytes)//1024} KB)")
        raw = IA.vision(prompt, imagen_bytes, fallback="{}")
    else:
        raw = IA.chat(prompt, fallback="{}", max_tokens=1200)
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        ctx = json.loads(raw)
    except Exception as e:
        log.warning(f"analizar_contexto: JSON invalido ({e}). Uso fallback minimo.")
        ctx = {
            "cargo_objetivo": titulo,
            "empresa": "",
            "resumen_pedido": descripcion[:300],
            "experiencia_requerida": "",
            "nivel_seniority": "sin especificar",
            "habilidades_duras": [],
            "habilidades_blandas": [],
            "keywords_ats": [],
            "keywords_coincidentes": [],
            "keywords_faltantes": [],
            "score_idoneidad": 0,
            "justificacion": "No pude analizar la oferta.",
        }

    _CONTEXTO = ctx
    try:
        CONTEXTO_PATH.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"analizar_contexto: no pude escribir {CONTEXTO_PATH.name}: {e}")
    return ctx


# ──────────────────────────────────────────────────────────────────
# EXTRACCION DE PDF + PROPUESTA DE PERFIL
# ──────────────────────────────────────────────────────────────────
def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """Extrae texto de un PDF (no funciona con PDFs escaneados sin OCR)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    partes = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
            if t.strip():
                partes.append(t)
        except Exception as e:
            log.warning(f"PDF: error extrayendo pagina {i}: {e}")
    return "\n".join(partes).strip()


def proponer_perfil_desde_texto(texto: str) -> dict:
    """
    Pide a la IA que extraiga TODOS los campos del perfil presentes en `texto`.
    Comportamiento: el JSON devuelto reemplaza por completo al perfil actual.
    Lo que no aparezca en el texto queda vacio en el nuevo perfil.
    """
    schema_json = json.dumps(SCHEMA_EJEMPLO, ensure_ascii=False, indent=2)
    prompt = (
        "Eres un extractor estructurado de datos de CVs. Lee el TEXTO de"
        " abajo (extraido de un PDF) y devuelve UN JSON con TODOS los campos"
        " del perfil que aparezcan en el texto. Este JSON va a REEMPLAZAR"
        " por completo el perfil actual del usuario, asi que extrae todo lo"
        " que puedas del CV.\n\n"
        "ESQUEMA DE PERFIL OBJETIVO. Los valores que ves abajo son SOLO"
        " EJEMPLOS de formato: copia EXACTAMENTE las CLAVES y los TIPOS,"
        " pero los VALORES los sacas del TEXTO del CV (nunca del ejemplo)."
        " NO inventes claves nuevas ni renombres las existentes (p.ej. usa"
        " 'cargo', no 'puesto'; idiomas son objetos {idioma, nivel}, no"
        " strings):\n"
        f"{schema_json}\n\n"
        "TEXTO DEL DOCUMENTO:\n"
        f"{texto[:8000]}\n\n"
        "REGLAS ABSOLUTAS:\n"
        "1. PROHIBIDO inventar datos. Si un dato no aparece textualmente en"
        " el texto, OMITE esa clave del JSON (o ponla como \"\" / [] / null"
        " segun el tipo). NO copies valores del ESQUEMA EJEMPLO ni datos de"
        " ningun perfil previo: solo existe lo que este en el TEXTO.\n"
        "2. Respeta los tipos y las CLAVES del esquema literalmente. Si el"
        " esquema tiene {cargo, empresa}, NO devuelvas {puesto, compania}."
        " Si idiomas es [{idioma, nivel}], NO devuelvas strings sueltos.\n"
        "3. Para arrays (experiencia, estudios, habilidades, etc): SOLO"
        " incluye los items que aparezcan en el texto. El resultado"
        " reemplaza la lista entera; no se preservan items previos.\n"
        "4. Para respuestas_extra (objeto con preguntas comunes): incluye"
        " SOLO las claves cuyas respuestas se puedan inferir directamente"
        " del texto.\n"
        "5. Devuelve SOLO JSON valido. Sin texto extra, sin comentarios, sin"
        " ```. Empieza con { y termina con }.\n"
    )
    raw = IA.chat(prompt, fallback="{}", max_tokens=4000)
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except Exception as e:
        log.warning(f"proponer_perfil: JSON invalido ({e}). Raw: {raw[:200]}")
        return {}


def cargar_propuesta_disco() -> dict | None:
    if PROPUESTA_PATH.exists():
        try:
            return json.loads(PROPUESTA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def guardar_propuesta_disco(propuesta: dict) -> None:
    PROPUESTA_PATH.write_text(
        json.dumps(propuesta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def backup_perfil_actual() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUPS_DIR / f"perfil_{ts}.json"
    shutil.copy2(PERFIL_PATH, dst)
    return dst


# ──────────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Izipega — servidor local")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalizarRequest(BaseModel):
    titulo: str = ""
    descripcion: str = ""
    imagen_base64: str = ""


class CampoMeta(BaseModel):
    label: str = ""
    placeholder: str = ""
    name: str = ""
    id: str = ""
    aria_label: str = ""
    aria_describedby_texto: str = ""
    legend: str = ""
    hermanos: str = ""
    tipo_input: str = ""


class Campo(BaseModel):
    id: str
    tipo: str  # text | textarea | radio | checkbox | select
    label: str
    opciones: list[str] | None = None
    meta: CampoMeta | None = None


class RellenarRequest(BaseModel):
    titulo_contexto: str = ""
    campos: list[Campo]
    usar_directas: bool = True
    imagen_base64: str = ""


class Respuesta(BaseModel):
    id: str
    tipo: str
    valor: str


class RellenarResponse(BaseModel):
    respuestas: list[Respuesta]


class ConfigurarKeysRequest(BaseModel):
    gemini_api_key: str = ""
    groq_api_key: str = ""


def _texto_completo_campo(campo: Campo) -> str:
    """Concatena todos los atributos textuales del campo. Sirve para que
    respuesta_directa() pueda matchear aunque el label visible sea pobre."""
    partes = [campo.label]
    m = campo.meta
    if m is not None:
        partes.extend([
            m.placeholder, m.name, m.id, m.aria_label,
            m.aria_describedby_texto, m.legend,
        ])
    return " | ".join(p for p in partes if p)


def rellenar_campo(campo: Campo, titulo_contexto: str, usar_directas: bool, imagen_bytes: bytes | None = None) -> Respuesta:
    tipo = campo.tipo
    pregunta = campo.label
    texto_match = _texto_completo_campo(campo)

    if tipo in ("text", "textarea"):
        resp = (respuesta_directa(texto_match) if usar_directas else None)
        if resp is None:
            resp = respuesta_ia_para_pregunta(campo, titulo_contexto, imagen_bytes=imagen_bytes)
            if tipo == "text" and resp and len(resp) > 150:
                resp = resp.split(".")[0][:150]
            elif tipo == "textarea" and resp and len(resp) > 480:
                # Cap duro a ~480 chars para no romper validaciones tipo
                # Indeed (limite tipico 500). Corta en el ultimo punto.
                corte = resp[:480]
                ultimo_punto = corte.rfind(".")
                if ultimo_punto > 200:
                    resp = corte[: ultimo_punto + 1]
                else:
                    resp = corte.rstrip() + "..."
        return Respuesta(id=campo.id, tipo=tipo, valor=resp or "")

    if tipo == "radio":
        opciones = campo.opciones or []
        if not opciones:
            return Respuesta(id=campo.id, tipo=tipo, valor="")
        respuesta_pref = respuesta_directa(texto_match) if usar_directas else None
        if respuesta_pref:
            for o in opciones:
                if respuesta_pref.lower() in o.lower() or o.lower() in respuesta_pref.lower():
                    return Respuesta(id=campo.id, tipo=tipo, valor=o)
            return Respuesta(id=campo.id, tipo=tipo, valor=opciones[0])
        if len(opciones) <= 2:
            es_si = IA.si_no(
                f"Perfil: {PERFIL_RESUMIDO[:200]}\n\nPregunta: {pregunta}\n"
                "Responde SOLO SI o NO segun el perfil.",
                default=True,
            )
            for o in opciones:
                tl = o.lower()
                if es_si and any(p in tl for p in ["sí", "si", "yes", "1", "true"]):
                    return Respuesta(id=campo.id, tipo=tipo, valor=o)
                if not es_si and any(p in tl for p in ["no", "0", "false"]):
                    return Respuesta(id=campo.id, tipo=tipo, valor=o)
            return Respuesta(id=campo.id, tipo=tipo, valor=opciones[0])
        eleccion = IA.elegir(pregunta, opciones, contexto=f"Candidato: {PERFIL_RESUMIDO[:200]}")
        return Respuesta(id=campo.id, tipo=tipo, valor=eleccion)

    if tipo == "select":
        opciones = campo.opciones or []
        if not opciones:
            return Respuesta(id=campo.id, tipo=tipo, valor="")
        respuesta_pref = respuesta_directa(texto_match) if usar_directas else None
        if respuesta_pref:
            for o in opciones:
                if respuesta_pref.lower() in o.lower() or o.lower() in respuesta_pref.lower():
                    return Respuesta(id=campo.id, tipo=tipo, valor=o)
        eleccion = IA.elegir(pregunta, opciones, contexto=f"Candidato: {PERFIL_RESUMIDO[:200]}")
        return Respuesta(id=campo.id, tipo=tipo, valor=eleccion)

    if tipo == "checkbox":
        label_l = pregunta.lower()
        # 1) Checkboxes legales / aceptaciones se marcan siempre que existan
        if any(p in label_l for p in ["acept", "terminos", "privacid", "consenti", "autorizo", "declaro"]):
            return Respuesta(id=campo.id, tipo=tipo, valor="true")
        # 2) Si la respuesta directa del perfil cubre el campo, usar eso
        respuesta_pref = respuesta_directa(texto_match) if usar_directas else None
        if respuesta_pref:
            val = respuesta_pref.strip().lower()
            es_negativo = val in ("no", "false", "0") or val.startswith("no ")
            return Respuesta(
                id=campo.id, tipo=tipo, valor="false" if es_negativo else "true"
            )
        # 3) Pregunta a la IA si la afirmacion del checkbox aplica al perfil
        es_si = IA.si_no(
            f"Perfil: {PERFIL_RESUMIDO[:300]}\n\n"
            f"La pregunta del checkbox es: '{pregunta}'\n"
            "Si la afirmacion es verdadera segun el perfil, responde SI. "
            "Si es falsa o no se puede deducir, responde NO.",
            default=False,
        )
        return Respuesta(id=campo.id, tipo=tipo, valor="true" if es_si else "false")

    return Respuesta(id=campo.id, tipo=tipo, valor="")


@app.get("/ping")
def ping():
    ctx = _CONTEXTO or {}
    estado_ia = IA.estado()
    return {
        "ok": True,
        "contexto_cargado": bool(ctx),
        "cargo_objetivo": ctx.get("cargo_objetivo", ""),
        "empresa": ctx.get("empresa", ""),
        "score_idoneidad": ctx.get("score_idoneidad"),
        "justificacion": ctx.get("justificacion", ""),
        "keywords_coincidentes": ctx.get("keywords_coincidentes", []),
        "keywords_faltantes": ctx.get("keywords_faltantes", []),
        "propuesta_pendiente": PROPUESTA_PATH.exists(),
        "keys_configuradas": estado_ia["gemini_configurado"] or estado_ia["groq_configurado"],
        "ia_disponible": estado_ia["alguno_disponible"],
    }


# ─── Gestion de API keys ──────────────────────────────────────────
@app.get("/estado_keys")
def estado_keys():
    """Devuelve el estado de configuracion de las API keys (sin exponer valores)."""
    return IA.estado()


@app.post("/configurar_keys")
def configurar_keys(req: ConfigurarKeysRequest):
    """Recibe las API keys de la extension, las escribe al .env y recarga
    los clientes IA. Si solo se manda una, la otra se preserva."""
    gemini = (req.gemini_api_key or "").strip()
    groq = (req.groq_api_key or "").strip()

    if not gemini and not groq:
        raise HTTPException(status_code=400, detail="Debes enviar al menos una API key.")

    actual = _leer_env_actual()
    if gemini:
        actual["GEMINI_API_KEY"] = gemini
    if groq:
        actual["GROQ_API_KEY"] = groq

    try:
        _escribir_env(actual)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No pude escribir el .env: {e}")

    log.info(f"/configurar_keys: gemini={'sí' if gemini else 'no'}, groq={'sí' if groq else 'no'}")
    estado = reload_ia()
    return {"ok": True, **estado}


# ─── Perfil + propuesta de perfil desde PDF ───────────────────────
@app.get("/perfil_actual")
def perfil_actual():
    with open(PERFIL_PATH, encoding="utf-8") as f:
        return json.load(f)


@app.get("/perfil_propuesto")
def perfil_propuesto():
    propuesta = cargar_propuesta_disco()
    if propuesta is None:
        raise HTTPException(status_code=404, detail="No hay propuesta pendiente")
    return propuesta


@app.post("/proponer_perfil")
async def proponer_perfil(pdf: UploadFile = File(...)):
    if pdf.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail=f"Tipo no soportado: {pdf.content_type}")
    contenido = await pdf.read()
    log.info(f"/proponer_perfil: archivo='{pdf.filename}' bytes={len(contenido)}")
    if not contenido:
        raise HTTPException(status_code=400, detail="PDF vacio")

    try:
        texto = extraer_texto_pdf(contenido)
    except Exception as e:
        log.error(f"extraer_texto_pdf fallo: {e}")
        raise HTTPException(status_code=400, detail=f"No pude leer el PDF: {e}")

    if len(texto) < 50:
        raise HTTPException(
            status_code=400,
            detail=(
                "El PDF parece estar escaneado (sin texto extraible). "
                "Convertelo a texto antes de subirlo."
            ),
        )

    log.info(f"  Texto extraido: {len(texto)} chars. Pidiendo a IA...")
    propuesto = proponer_perfil_desde_texto(texto)
    if not propuesto:
        raise HTTPException(status_code=500, detail="La IA no devolvio JSON valido")

    guardar_propuesta_disco(propuesto)
    log.info(f"  Propuesta guardada en {PROPUESTA_PATH.name}")

    return {
        "ok": True,
        "actual": PERFIL,
        "propuesto": propuesto,
        "campos_detectados": list(propuesto.keys()),
    }


class AplicarPerfilRequest(BaseModel):
    perfil: dict


@app.post("/aplicar_perfil")
def aplicar_perfil(req: AplicarPerfilRequest):
    global PERFIL, PERFIL_RESUMIDO
    if not req.perfil or not isinstance(req.perfil, dict):
        raise HTTPException(status_code=400, detail="Perfil invalido")

    backup_path = backup_perfil_actual()
    log.info(f"/aplicar_perfil: backup en {backup_path.name}")

    PERFIL_PATH.write_text(
        json.dumps(req.perfil, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )

    # Recargar en memoria
    with open(PERFIL_PATH, encoding="utf-8") as f:
        PERFIL = json.load(f)
    PERFIL_RESUMIDO = _construir_perfil_resumido(PERFIL)

    # Limpiar propuesta
    if PROPUESTA_PATH.exists():
        PROPUESTA_PATH.unlink()

    return {"ok": True, "backup": backup_path.name}


@app.post("/descartar_propuesta")
def descartar_propuesta():
    if PROPUESTA_PATH.exists():
        PROPUESTA_PATH.unlink()
    return {"ok": True}


@app.post("/analizar")
def analizar(req: AnalizarRequest):
    imagen_bytes: bytes | None = None
    if req.imagen_base64:
        try:
            import base64
            raw = req.imagen_base64
            if "," in raw and raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            imagen_bytes = base64.b64decode(raw)
        except Exception as e:
            log.warning(f"/analizar: imagen invalida ({e}), uso solo texto.")
            imagen_bytes = None
    log.info(f"/analizar: titulo='{req.titulo[:60]}' desc_chars={len(req.descripcion)} vision={'si' if imagen_bytes else 'no'}")
    ctx = analizar_contexto_logic(req.titulo, req.descripcion, imagen_bytes=imagen_bytes)
    log.info(f"  -> cargo='{ctx.get('cargo_objetivo', '?')}' empresa='{ctx.get('empresa', '?')}'")
    score = ctx.get("score_idoneidad")
    if score is not None:
        log.info(f"  -> score: {score}/100. {ctx.get('justificacion', '')[:150]}")
    return ctx


@app.post("/limpiar_contexto")
def limpiar_contexto():
    global _CONTEXTO
    _CONTEXTO = None
    try:
        if CONTEXTO_PATH.exists():
            CONTEXTO_PATH.unlink()
    except Exception as e:
        log.warning(f"No pude borrar {CONTEXTO_PATH.name}: {e}")
    return {"ok": True}


@app.post("/rellenar", response_model=RellenarResponse)
def rellenar(req: RellenarRequest):
    imagen_bytes: bytes | None = None
    if req.imagen_base64:
        try:
            import base64
            raw = req.imagen_base64
            # Soporta tanto "data:image/png;base64,..." como base64 puro
            if "," in raw and raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            imagen_bytes = base64.b64decode(raw)
        except Exception as e:
            log.warning(f"/rellenar: imagen invalida ({e}), uso solo texto.")
            imagen_bytes = None

    if imagen_bytes:
        if IA.vision_disponible():
            log.info(
                f"/rellenar: {len(req.campos)} campos, titulo='{req.titulo_contexto[:60]}' "
                f"VISION ({len(imagen_bytes)//1024} KB)"
            )
        else:
            log.warning(
                f"/rellenar: {len(req.campos)} campos VISION pedida pero ningun proveedor con vision activo. Caigo a texto."
            )
            imagen_bytes = None
    else:
        log.info(f"/rellenar: {len(req.campos)} campos, titulo='{req.titulo_contexto[:60]}'")

    respuestas: list[Respuesta] = []
    for c in req.campos:
        try:
            r = rellenar_campo(c, req.titulo_contexto, req.usar_directas, imagen_bytes=imagen_bytes)
            respuestas.append(r)
            log.info(f"  [{c.tipo}] {c.label[:60]} -> {r.valor[:80]}")
        except Exception as e:
            log.warning(f"  [{c.tipo}] {c.label[:60]} -> ERROR: {e}")
            respuestas.append(Respuesta(id=c.id, tipo=c.tipo, valor=""))
    return RellenarResponse(respuestas=respuestas)


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    estado_inicial = IA.estado()

    print("=" * 70)
    print("  IZIPEGA — SERVIDOR LOCAL (Gemini + Groq)")
    print("=" * 70)
    print()
    print(f"  Log:    {LOG_FILE}")
    print(f"  Perfil: {PERFIL_PATH.name}")
    print(
        "  IA:     "
        f"Gemini={'OK' if estado_inicial['gemini_activo'] else 'no configurada'}, "
        f"Groq={'OK' if estado_inicial['groq_activo'] else 'no configurada'}"
    )
    if not estado_inicial["alguno_disponible"]:
        print("          (configura tus keys desde la extension al abrirla)")
    if _CONTEXTO:
        print(
            f"  Contexto previo: {_CONTEXTO.get('cargo_objetivo', '?')} "
            f"@ {_CONTEXTO.get('empresa', '?')}"
        )
    else:
        print("  Contexto previo: (ninguno)")
    print()
    print("  Endpoints:")
    print("    GET  http://localhost:8765/ping")
    print("    GET  http://localhost:8765/estado_keys")
    print("    POST http://localhost:8765/configurar_keys")
    print("    POST http://localhost:8765/analizar")
    print("    POST http://localhost:8765/limpiar_contexto")
    print("    POST http://localhost:8765/rellenar")
    print("    GET  http://localhost:8765/perfil_actual")
    print("    GET  http://localhost:8765/perfil_propuesto")
    print("    POST http://localhost:8765/proponer_perfil   (multipart con PDF)")
    print("    POST http://localhost:8765/aplicar_perfil")
    print("    POST http://localhost:8765/descartar_propuesta")
    print()
    print("  Para usar la extension:")
    print("    1) chrome://extensions  ->  activa 'Modo desarrollador'")
    print("    2) 'Cargar descomprimida' -> elige carpeta extension/")
    print("    3) Abre el panel lateral: pegara tus keys de Gemini y Groq")
    print("       la primera vez. Luego funciona en cualquier formulario.")
    print()
    print("  Ctrl+C para detener.")
    print("=" * 70)

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
