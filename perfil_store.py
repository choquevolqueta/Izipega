"""
perfil_store.py
----------------
Estado y persistencia del perfil del usuario: perfil.json, el "contexto"
de la oferta analizada, el historial de keywords, la propuesta de perfil
pendiente (extraida de un PDF), los backups, y el .env con las API keys.

Ningun endpoint de FastAPI vive aca — este modulo es puro estado + disco.
El estado mutable (PERFIL, contexto) se expone via funciones get_/set_
para que otros modulos siempre lean el valor actual, no una copia
importada en el momento del arranque.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger("server")

# ──────────────────────────────────────────────────────────────────
# RUTAS
# ──────────────────────────────────────────────────────────────────
PERFIL_PATH = Path(__file__).parent / "perfil.json"
ENV_PATH = Path(__file__).parent / ".env"
CONTEXTO_PATH = Path(__file__).parent / "contexto_actual.json"
HISTORIAL_PATH = Path(__file__).parent / "historial_keywords.json"
HISTORIAL_MAX = 10
PROPUESTA_PATH = Path(__file__).parent / "perfil_propuesto.json"
BACKUPS_DIR = Path(__file__).parent / "perfil_backups"
BACKUPS_DIR.mkdir(exist_ok=True)


# ──────────────────────────────────────────────────────────────────
# PERFIL (estado en memoria + disco)
# ──────────────────────────────────────────────────────────────────
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


def _reload_perfil_desde_disco() -> None:
    global PERFIL, PERFIL_RESUMIDO
    with open(PERFIL_PATH, encoding="utf-8") as f:
        PERFIL = json.load(f)
    PERFIL_RESUMIDO = _construir_perfil_resumido(PERFIL)


PERFIL: dict = {}
PERFIL_RESUMIDO: str = ""
_reload_perfil_desde_disco()


def get_perfil() -> dict:
    return PERFIL


def get_perfil_resumido() -> str:
    return PERFIL_RESUMIDO


def guardar_perfil(nuevo: dict) -> Path:
    """Hace backup del perfil actual, escribe `nuevo` a disco y recarga el
    estado en memoria. Devuelve la ruta del backup creado."""
    backup_path = backup_perfil_actual()
    PERFIL_PATH.write_text(
        json.dumps(nuevo, ensure_ascii=False, indent=4), encoding="utf-8"
    )
    _reload_perfil_desde_disco()
    return backup_path


def backup_perfil_actual() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUPS_DIR / f"perfil_{ts}.json"
    shutil.copy2(PERFIL_PATH, dst)
    return dst


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


# ──────────────────────────────────────────────────────────────────
# CONTEXTO ACTUAL (opcional — solo si se uso /analizar)
# ──────────────────────────────────────────────────────────────────
_CONTEXTO: dict | None = None


def get_contexto() -> dict | None:
    return _CONTEXTO


def cargar_contexto_disco() -> dict | None:
    global _CONTEXTO
    if CONTEXTO_PATH.exists():
        try:
            _CONTEXTO = json.loads(CONTEXTO_PATH.read_text(encoding="utf-8"))
            return _CONTEXTO
        except Exception:
            return None
    return None


def set_contexto(ctx: dict | None) -> None:
    """ctx=None limpia el contexto (memoria + disco). ctx=dict lo guarda."""
    global _CONTEXTO
    _CONTEXTO = ctx
    if ctx is None:
        try:
            if CONTEXTO_PATH.exists():
                CONTEXTO_PATH.unlink()
        except Exception as e:
            log.warning(f"No pude borrar {CONTEXTO_PATH.name}: {e}")
        return
    try:
        CONTEXTO_PATH.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"No pude escribir {CONTEXTO_PATH.name}: {e}")


cargar_contexto_disco()


# ──────────────────────────────────────────────────────────────────
# HISTORIAL DE KEYWORDS (ultimas N ofertas analizadas)
# Sirve para reescribir el CV: acumula las keywords que faltan en el
# perfil a lo largo de varias ofertas y muestra cuales se repiten mas.
# ──────────────────────────────────────────────────────────────────
def cargar_historial() -> list[dict]:
    if HISTORIAL_PATH.exists():
        try:
            data = json.loads(HISTORIAL_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning(f"historial: no pude leer {HISTORIAL_PATH.name}: {e}")
    return []


def guardar_en_historial(ctx: dict) -> None:
    """Anade el analisis actual al historial (ring buffer de HISTORIAL_MAX)."""
    if not ctx or not ctx.get("cargo_objetivo"):
        return
    entrada = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "cargo_objetivo": ctx.get("cargo_objetivo", ""),
        "empresa": ctx.get("empresa", ""),
        "score_idoneidad": ctx.get("score_idoneidad"),
        "keywords_faltantes": ctx.get("keywords_faltantes", []),
        "keywords_coincidentes": ctx.get("keywords_coincidentes", []),
        "keywords_ats": ctx.get("keywords_ats", []),
    }
    historial = cargar_historial()
    historial.append(entrada)
    historial = historial[-HISTORIAL_MAX:]
    try:
        HISTORIAL_PATH.write_text(
            json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info(f"historial: guardada entrada ({len(historial)}/{HISTORIAL_MAX}).")
    except Exception as e:
        log.warning(f"historial: no pude escribir {HISTORIAL_PATH.name}: {e}")


def top_keywords_faltantes(historial: list[dict] | None = None, score_minimo: int = 0) -> list[dict]:
    """Cuenta cuantas veces aparece cada keyword faltante en el historial.

    score_minimo filtra las ofertas con score_idoneidad por debajo del umbral
    antes de contar. Sirve para que el CV "generalista" (pensado para varias
    postulaciones, no una a medida) no se contamine con keywords de ofertas
    donde el candidato claramente no encajaba (score bajo) — sin eso, buscar
    en rubros distintos mezcla vocabulario que no tiene nada que ver entre si."""
    if historial is None:
        historial = cargar_historial()
    conteo: dict[str, dict] = {}
    for e in historial:
        if score_minimo:
            score = e.get("score_idoneidad")
            if score is None or score < score_minimo:
                continue
        for kw in e.get("keywords_faltantes", []):
            clave = (kw or "").strip().lower()
            if not clave:
                continue
            if clave not in conteo:
                conteo[clave] = {"keyword": kw.strip(), "veces": 0}
            conteo[clave]["veces"] += 1
    return sorted(conteo.values(), key=lambda x: x["veces"], reverse=True)


# ──────────────────────────────────────────────────────────────────
# PROPUESTA DE PERFIL (extraida de PDF, pendiente de aprobacion)
# ──────────────────────────────────────────────────────────────────
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


def descartar_propuesta_disco() -> None:
    if PROPUESTA_PATH.exists():
        PROPUESTA_PATH.unlink()


# ──────────────────────────────────────────────────────────────────
# GESTION DE API KEYS EN .env
# ──────────────────────────────────────────────────────────────────
def leer_env_actual() -> dict[str, str]:
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


def escribir_env(datos: dict[str, str]) -> None:
    """Reescribe el .env con las claves dadas. Sobrescribe el archivo."""
    lineas = [
        "# Generado por /configurar_keys desde la extension.",
        "# No se sube a git (esta en .gitignore).",
        "",
    ]
    for k, v in datos.items():
        lineas.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lineas) + "\n", encoding="utf-8")
