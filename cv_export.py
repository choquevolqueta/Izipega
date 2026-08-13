"""
cv_export.py
------------
Todo lo que convierte un dict de perfil en un CV exportable: orden
cronologico de la experiencia, division en vinetas, y el render a PDF
nativo (texto real, legible por lectores ATS de portales de empleo).

Antes el PDF se hacia con window.print() del navegador. Eso produce una
capa de texto que los lectores de CV de portales (Laborum/Bumeran) no
logran extraer: el archivo "sube pero queda vacio". Aca se genera un PDF
nativo con fpdf2 y fuente Arial real: texto seleccionable y parseable.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

# fpdf2 subsetea la fuente con fontTools, que loguea decenas de lineas por PDF.
# No nos interesan: las silenciamos para no ensuciar el log del servidor.
logging.getLogger("fontTools").setLevel(logging.WARNING)

_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

# Paleta — misma que cv.css para que el PDF se vea igual que la vista previa.
_TINTA = (26, 26, 46)
_GRIS = (85, 85, 85)
_GRIS_CLARO = (136, 136, 136)
_ACENTO = (45, 74, 124)
_LINEA = (216, 221, 230)


# ──────────────────────────────────────────────────────────────────
# ORDEN CRONOLOGICO
# ──────────────────────────────────────────────────────────────────
def _exp_orden_key(exp: dict) -> tuple:
    """Clave para ordenar experiencias de mas reciente a mas antigua.
    Usa el periodo (texto libre): 'actualidad/presente' pesa como ano 9999."""
    periodo = (exp.get("periodo") or "").lower()
    anios = [int(a) for a in re.findall(r"(?:19|20)\d{2}", periodo)]
    actual = any(w in periodo for w in ("actual", "presente", "present", "current", "hoy"))
    fin = 9999 if actual else (max(anios) if anios else 0)
    inicio = min(anios) if anios else 0
    return (fin, inicio)


def ordenar_experiencia_reciente(exps: list) -> list:
    """Ordena las experiencias por empleo mas reciente primero (no por relevancia)."""
    if not isinstance(exps, list):
        return exps
    return sorted(exps, key=_exp_orden_key, reverse=True)


def _vinetas_de(e: dict) -> list[str]:
    """Replica aVinetas() del front: usa e['vinetas'] o parte la descripcion."""
    v = e.get("vinetas")
    if isinstance(v, list) and v:
        return [str(x).strip() for x in v if str(x).strip()]
    desc = str(e.get("descripcion") or "").strip()
    if not desc:
        return []
    partes = re.split(r"(?<=[.;])\s+", desc)
    return [p.strip() for p in partes if len(p.strip()) > 1]


# ──────────────────────────────────────────────────────────────────
# PDF
# ──────────────────────────────────────────────────────────────────
def construir_cv_pdf(cv: dict) -> bytes:
    """Renderiza el CV (mismo dict que muestra cv.js) a un PDF A4 de una pagina."""
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=13)
    pdf.set_margins(14, 13, 14)
    pdf.set_title(f"CV - {cv.get('nombre', '')}".strip(" -"))
    pdf.add_page()

    # Fuente Arial real -> sin problemas de tildes/ñ ni de extraccion de texto.
    # Si por lo que sea no esta, caemos a Helvetica (core) saneando a latin-1.
    arial = _FONT_DIR / "arial.ttf"
    if arial.exists():
        pdf.add_font("CV", "", str(arial))
        pdf.add_font("CV", "B", str(_FONT_DIR / "arialbd.ttf"))
        pdf.add_font("CV", "I", str(_FONT_DIR / "ariali.ttf"))
        FONT = "CV"

        def T(s):  # noqa: E306
            return str(s if s is not None else "")
    else:
        FONT = "Helvetica"

        def T(s):  # noqa: E306
            return str(s if s is not None else "").encode("latin-1", "replace").decode("latin-1")

    left = pdf.l_margin
    usable = pdf.w - pdf.l_margin - pdf.r_margin

    def seccion(titulo: str):
        pdf.ln(2)
        pdf.set_font(FONT, "B", 9)
        pdf.set_text_color(*_ACENTO)
        pdf.cell(0, 5, T(titulo.upper()), new_x="LMARGIN", new_y="NEXT")
        y = pdf.get_y()
        pdf.set_draw_color(*_LINEA)
        pdf.set_line_width(0.2)
        pdf.line(left, y, left + usable, y)
        pdf.ln(1.6)

    # ── Encabezado: nombre + rol ──
    pdf.set_font(FONT, "B", 20)
    pdf.set_text_color(*_TINTA)
    pdf.cell(0, 9, T(cv.get("nombre", "")), new_x="LMARGIN", new_y="NEXT")

    rol = (cv.get("estudios") or [{}])[0].get("titulo", "") if cv.get("estudios") else ""
    if rol:
        pdf.set_font(FONT, "B", 11)
        pdf.set_text_color(*_ACENTO)
        pdf.cell(0, 6, T(rol), new_x="LMARGIN", new_y="NEXT")

    # ── Linea de contacto ──
    ubic = ", ".join(x for x in [cv.get("comuna"), cv.get("ciudad")] if x)
    redes = cv.get("redes") or {}
    contacto = [x for x in [
        cv.get("telefono"),
        cv.get("email"),
        ubic,
        cv.get("nacionalidad"),
        redes.get("linkedin"),
        redes.get("portafolio_web"),
        redes.get("behance"),
    ] if x]
    if contacto:
        pdf.ln(1)
        pdf.set_font(FONT, "", 8.5)
        pdf.set_text_color(*_GRIS)
        pdf.multi_cell(usable, 4.2, T("   ·   ".join(contacto)), new_x="LMARGIN", new_y="NEXT")

    # Regla bajo el contacto (acento, gruesa) — igual que el borde de cv.css.
    y = pdf.get_y() + 0.5
    pdf.set_draw_color(*_ACENTO)
    pdf.set_line_width(0.5)
    pdf.line(left, y, left + usable, y)
    pdf.ln(3)

    # ── Perfil profesional ──
    if cv.get("perfil_profesional"):
        seccion("Perfil profesional")
        pdf.set_font(FONT, "", 9.5)
        pdf.set_text_color(*_GRIS)
        pdf.multi_cell(usable, 4.6, T(cv["perfil_profesional"]), new_x="LMARGIN", new_y="NEXT")

    # ── Experiencia ──
    exps = cv.get("experiencia") or []
    if exps:
        seccion("Experiencia")
        for e in exps:
            periodo = T(e.get("periodo", ""))
            pdf.set_font(FONT, "", 9)
            pw = pdf.get_string_width(periodo) + 1 if periodo else 0
            y0 = pdf.get_y()
            # Cargo (izq) + periodo (der) en la misma linea.
            pdf.set_xy(left, y0)
            pdf.set_font(FONT, "B", 10.5)
            pdf.set_text_color(*_TINTA)
            pdf.cell(usable - pw, 5, T(e.get("cargo", "")))
            if periodo:
                pdf.set_font(FONT, "", 9)
                pdf.set_text_color(*_GRIS_CLARO)
                pdf.set_xy(left + usable - pw, y0)
                pdf.cell(pw, 5, periodo, align="R")
            pdf.set_xy(left, y0 + 5)
            # Empresa · ubicacion
            lugar = " · ".join(x for x in [e.get("empresa"), e.get("ubicacion")] if x)
            if lugar:
                pdf.set_font(FONT, "B", 9.5)
                pdf.set_text_color(*_ACENTO)
                pdf.cell(0, 4.6, T(lugar), new_x="LMARGIN", new_y="NEXT")
            # Viñetas con sangria francesa
            for v in _vinetas_de(e):
                yb = pdf.get_y()
                pdf.set_font(FONT, "", 9.5)
                pdf.set_text_color(*_ACENTO)
                pdf.set_xy(left + 1, yb)
                pdf.cell(3.5, 4.6, "-" if FONT == "Helvetica" else "•")
                pdf.set_text_color(*_GRIS)
                pdf.set_xy(left + 4.5, yb)
                pdf.multi_cell(usable - 4.5, 4.6, T(v), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

    # ── Formación ──
    estudios = cv.get("estudios") or []
    if estudios:
        seccion("Formación")
        for s in estudios:
            pdf.set_font(FONT, "B", 9.5)
            pdf.set_text_color(*_TINTA)
            pdf.cell(0, 4.8, T(s.get("titulo", "")), new_x="LMARGIN", new_y="NEXT")
            sub = " · ".join(
                str(x) for x in [s.get("institucion"), s.get("ubicacion"), s.get("anio_egreso")] if x
            )
            if sub:
                pdf.set_font(FONT, "", 9)
                pdf.set_text_color(*_GRIS)
                pdf.cell(0, 4.4, T(sub), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    # ── Habilidades (habilidades + herramientas, sin duplicados) ──
    skills, vistos = [], set()
    for s in [*(cv.get("habilidades") or []), *(cv.get("herramientas") or [])]:
        s = str(s).strip()
        if s and s.lower() not in vistos:
            vistos.add(s.lower())
            skills.append(s)
    if skills:
        seccion("Habilidades")
        pdf.set_font(FONT, "", 9.5)
        pdf.set_text_color(*_GRIS)
        pdf.multi_cell(usable, 4.6, T(", ".join(skills)), new_x="LMARGIN", new_y="NEXT")

    # ── Idiomas ──
    idiomas = cv.get("idiomas") or []
    if idiomas:
        seccion("Idiomas")
        pdf.set_font(FONT, "", 9.5)
        pdf.set_text_color(*_GRIS)

        def _fmt_idioma(i: dict) -> str:
            idioma = str(i.get("idioma", "")).strip()
            nivel = str(i.get("nivel", "")).strip()
            return f"{idioma} ({nivel})" if nivel else idioma

        linea = "    ".join(_fmt_idioma(i) for i in idiomas)
        pdf.multi_cell(usable, 4.6, T(linea), new_x="LMARGIN", new_y="NEXT")

    out = pdf.output()
    return bytes(out)
