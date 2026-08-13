"""
ia_logic.py
-----------
Toda la logica que arma prompts y habla con la IA (DeepSeek para texto,
Gemini para vision): respuestas directas desde el perfil (sin gastar
tokens), relleno de campos, analisis de ofertas, extraccion de perfil
desde un PDF, y optimizacion del CV contra keywords ATS.

No define rutas de FastAPI — server.py orquesta, este modulo piensa.
"""

from __future__ import annotations

import io
import json
import logging

from pypdf import PdfReader

import perfil_store
from ia_client import get_ia
from models import Campo, CampoMeta, Respuesta

log = logging.getLogger("server")

IA = get_ia()


# ──────────────────────────────────────────────────────────────────
# RESPUESTAS DIRECTAS (no gastan tokens — vienen del perfil)
# ──────────────────────────────────────────────────────────────────
def respuesta_directa(pregunta: str) -> str | None:
    perfil = perfil_store.get_perfil()
    t = pregunta.lower()
    extra = perfil.get("respuestas_extra", {})
    if any(p in t for p in ["renta", "sueldo", "pretension", "expectativa salar", "salario"]):
        return perfil.get("expectativa_sueldo") or None
    if any(p in t for p in ["disponibilidad", "disponible para empezar"]):
        return perfil.get("disponibilidad") or None
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
        tel = perfil.get("telefono") or ""
        em = perfil.get("email") or ""
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
        return perfil.get("telefono") or None
    if any(p in t for p in ["correo", "email", "e-mail", "mail "]):
        return perfil.get("email") or None
    if "comuna" in t:
        return perfil.get("comuna") or None
    if any(p in t for p in ["ciudad", "ubicacion", "ubicación", "donde vive", "donde resides", "lugar de residencia"]):
        return perfil.get("ciudad") or None
    # Eliminado: matching automatico de "edad" causaba falsos positivos en
    # campos de experiencia / necesidad / etc. que contenian la subcadena.
    if any(p in t for p in ["nombre completo", "nombre y apellido", "tu nombre", "nombres y apellidos"]):
        return perfil.get("nombre") or None
    if any(p in t for p in ["licencia", "conducir"]):
        return extra.get("licencia_conducir") or None
    if any(p in t for p in ["nacionalidad", "pais de origen", "país de origen"]):
        return perfil.get("nacionalidad") or None
    if any(p in t for p in ["residencia", "permiso de trabaj", "visa"]):
        return extra.get("residencia_legal") or None
    # Redes y portafolio
    redes = perfil.get("redes") or {}
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


def _bloque_campo(campo: Campo) -> str:
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


def respuesta_ia_para_pregunta(campo: Campo, titulo_contexto: str = "", imagen_bytes: bytes | None = None) -> str:
    perfil = perfil_store.get_perfil()
    perfil_json = json.dumps(perfil, ensure_ascii=False)
    nombre = perfil.get("nombre", "el candidato")
    empresa_cargo = "; ".join(
        f"{e.get('empresa', '?')} = {e.get('cargo', '?')}"
        for e in perfil.get("experiencia", [])
    ) or "(sin experiencia registrada)"

    ctx = perfil_store.get_contexto() or {}
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
    fallback = perfil.get("respuestas_extra", {}).get(
        "por_que_este_cargo",
        "Cuento con la experiencia y disponibilidad descritas en mi perfil.",
    )
    if imagen_bytes:
        return IA.vision(prompt, imagen_bytes, fallback=fallback)
    return IA.chat(prompt, fallback=fallback, max_tokens=250)


def rellenar_campo(campo: Campo, titulo_contexto: str, usar_directas: bool, imagen_bytes: bytes | None = None) -> Respuesta:
    tipo = campo.tipo
    pregunta = campo.label
    texto_match = _texto_completo_campo(campo)
    perfil_resumido = perfil_store.get_perfil_resumido()

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
                f"Perfil: {perfil_resumido[:200]}\n\nPregunta: {pregunta}\n"
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
        eleccion = IA.elegir(pregunta, opciones, contexto=f"Candidato: {perfil_resumido[:200]}")
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
        eleccion = IA.elegir(pregunta, opciones, contexto=f"Candidato: {perfil_resumido[:200]}")
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
            f"Perfil: {perfil_resumido[:300]}\n\n"
            f"La pregunta del checkbox es: '{pregunta}'\n"
            "Si la afirmacion es verdadera segun el perfil, responde SI. "
            "Si es falsa o no se puede deducir, responde NO.",
            default=False,
        )
        return Respuesta(id=campo.id, tipo=tipo, valor="true" if es_si else "false")

    return Respuesta(id=campo.id, tipo=tipo, valor="")


# ──────────────────────────────────────────────────────────────────
# ANALISIS DE CONTEXTO (opcional)
# ──────────────────────────────────────────────────────────────────
def analizar_contexto_logic(titulo: str, descripcion: str, imagen_bytes: bytes | None = None) -> dict:
    # Limpieza incondicional: cada "Analizar" parte de cero, asi el usuario
    # no tiene que apretar "Olvidar contexto" antes de cambiar de oferta.
    perfil_store.set_contexto(None)

    if not titulo and not descripcion and not imagen_bytes:
        return {}

    perfil_json = json.dumps(perfil_store.get_perfil(), ensure_ascii=False)

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

    perfil_store.set_contexto(ctx)
    perfil_store.guardar_en_historial(ctx)
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
    schema_json = json.dumps(perfil_store.SCHEMA_EJEMPLO, ensure_ascii=False, indent=2)
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


# ──────────────────────────────────────────────────────────────────
# OPTIMIZACION DE CV CONTRA KEYWORDS
# ──────────────────────────────────────────────────────────────────
def optimizar_cv_con_ia(perfil: dict, keywords: list[str]) -> dict:
    """Clasifica cada keyword contra el perfil (tiene / transferible / no_tiene)
    y reescribe el CV usando SOLO las respaldadas por experiencia real. Nunca
    inventa: las 'no_tiene' jamas entran al CV (se devuelven como brechas).
    Devuelve los campos optimizados + la clasificacion para ser transparente.
    Usa IA.chat (DeepSeek via API compatible OpenAI)."""
    perfil_json = json.dumps(perfil, ensure_ascii=False)
    prompt = (
        "Eres a la vez un redactor experto en CVs para filtros ATS y un auditor"
        " HONESTO de habilidades. Mentir en un CV es la peor falta posible.\n"
        "Te doy el PERFIL real de un candidato (tu UNICA fuente de verdad) y una"
        " lista de KEYWORDS que los reclutadores piden.\n\n"
        f"PERFIL:\n{perfil_json}\n\n"
        f"KEYWORDS:\n{', '.join(keywords)}\n\n"
        "PASO 1 — Para CADA keyword, primero RAZONA brevemente (1 frase, campo"
        " 'razon') que concepto real hay detras de esa keyword y si algo en el"
        " PERFIL lo demuestra — recien despues elegis la categoria. No saltes"
        " directo a la etiqueta: una keyword como 'Logistica' o 'Excel"
        " intermedio' hay que pensarla contra las tareas reales descritas en"
        " la experiencia, no contra las palabras exactas del perfil.\n"
        "Clasifica en UNA categoria:\n"
        "- \"tiene\": el perfil YA demuestra ese concepto, aunque este escrito con otras palabras o en otro rubro. Ej: perfil describe 'organizar productos y controlar stock en bodega' y la keyword es 'Logistica' o 'Orden' -> tiene, es el mismo concepto con otro nombre. Ej: perfil dice 'gestion de redes sociales' y la keyword es 'community management'.\n"
        "- \"transferible\": el perfil NO muestra ese concepto exacto, pero SI algo cercano de la misma familia que se traspasa con poco esfuerzo. Reservalo para cuando la keyword nombra una HERRAMIENTA, MARCA O CERTIFICACION especifica que el perfil no prueba tal cual. Ej: keyword 'Salesforce' y el perfil tiene experiencia en otro CRM -> transferible (la habilidad de fondo, gestion de CRM, es la misma; la marca no).\n"
        "- \"no_tiene\": el perfil no muestra NADA, ni el concepto ni algo parecido, que respalde la keyword. No hay base real, ni conceptual ni de herramienta.\n"
        "IMPORTANTE — hay dos tipos de duda distintos, no los trates igual:\n"
        "  a) Duda sobre una HERRAMIENTA/MARCA/CERTIFICACION puntual (¿de verdad use Salesforce? ¿tengo el certificado X?): ahi si, ante la duda BAJA de categoria — afirmar una herramienta especifica sin haberla usado es mentir.\n"
        "  b) Duda sobre un CONCEPTO o HABILIDAD generica (logistica, orden, atencion al cliente, trabajo en equipo): jugatela por lo que la experiencia REAL demuestra que hizo la persona, no por si el perfil usa la palabra exacta. Bajar de categoria aca porque 'no dice la palabra tal cual' es un error — el objetivo es reflejar la habilidad real, no hacer matching de texto literal.\n\n"
        "PASO 2 — REESCRIBE el CV (perfil_profesional, vinetas de experiencia y habilidades) en formato Harvard:\n"
        "- La experiencia va en VINETAS, no en parrafo. Cada vineta empieza con un VERBO DE ACCION en pasado (Lidere, Implemente, Aumente, Gestione) y, si el PERFIL lo respalda, incluye un resultado o cifra. Nunca inventes cifras.\n"
        "- ANTES de escribir las vinetas de CADA experiencia, evalua si esa experiencia es RELEVANTE para las keywords dadas (mismo rubro, tareas o herramientas parecidas) o TANGENCIAL (rubro distinto, poco en comun). Para experiencias RELEVANTES: 2-4 vinetas, metiendo las keywords que apliquen de forma natural. Para experiencias TANGENCIALES: 1-2 vinetas cortas y honestas, SIN forzar keywords que no tengan relacion — una vineta simple suena mejor que una 'ensalada de keywords' forzada. No inventes relevancia que no existe.\n"
        "- Usa LIBREMENTE los terminos de 'tiene' (son verdad, solo cambias el vocabulario al de la oferta).\n"
        "- Para 'transferible': menciona la habilidad REAL cercana SIN afirmar el termino exacto. Ej: escribe 'experiencia en gestion de CRM y tickets', NO escribas 'Salesforce' si no lo uso.\n"
        "- PROHIBIDO usar en CUALQUIER texto las keywords de 'no_tiene'. Nunca, ni insinuarlas.\n"
        "- La mayoria de los rechazos son revision HUMANA, no un filtro automatico ciego. Prioriza que el texto suene natural y convincente para una persona por sobre maximizar cuantas keywords entran.\n\n"
        "Devuelve SOLO JSON valido (sin ```), con esta forma EXACTA:\n"
        "{\n"
        '  "clasificacion": {\n'
        '    "tiene": [{"keyword": "...", "razon": "1 frase: que parte de la experiencia real demuestra esto"}],\n'
        '    "transferible": [{"keyword": "...", "razon": "1 frase: que tiene de parecido y que le falta para ser exacto"}],\n'
        '    "no_tiene": [{"keyword": "...", "razon": "1 frase: por que nada en el perfil respalda esto"}]\n'
        '  },\n'
        '  "perfil_profesional": "resumen de 3-4 oraciones, honesto, que integre lo de tiene/transferible.",\n'
        '  "experiencia": [{"vinetas": ["2-4 vinetas con verbo de accion + logro, usando lo que aplique a ESA experiencia"]}],\n'
        '  "habilidades": ["habilidades reales del perfil, primero las que coinciden con la oferta. Nada de no_tiene."]\n'
        "}\n\n"
        "REGLAS:\n"
        "- PROHIBIDO inventar cargos, empresas, herramientas o experiencia que no esten en el PERFIL.\n"
        "- El array 'experiencia' debe tener el MISMO numero de items y en el MISMO orden que el perfil; solo reescribes las 'vinetas'.\n"
        "- Cada keyword va en UNA sola categoria; la suma de las 3 listas = todas las keywords dadas.\n"
        "- Nada de muletillas ('Soy un profesional con...'). Ve directo al valor.\n"
    )
    # pensar=True: esta llamada decide que keywords son transferibles de
    # verdad (no un relleno de campo en vivo), vale la pena que razone antes
    # de clasificar en vez de responder rapido. Con thinking activado, los
    # tokens de razonamiento salen del mismo presupuesto que la respuesta
    # final — max_tokens bajo (probado con 3000) deja el "content" vacio
    # porque el modelo gasta todo pensando y no le queda espacio para
    # escribir el JSON. 8000 le da margen a ambas cosas.
    raw = (IA.chat(prompt, fallback="{}", max_tokens=8000, pensar=True) or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except Exception as e:
        log.warning(f"optimizar_cv: JSON invalido ({e}). Devuelvo perfil sin optimizar.")
        return {}
