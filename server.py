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

Usa DeepSeek (API compatible con OpenAI) como unico proveedor de IA.
La API key se configura desde la extension via POST /configurar_keys,
que escribe el .env local y reinicia el cliente.

Este archivo solo define las rutas de FastAPI. La logica vive en:
- perfil_store.py  estado + persistencia del perfil, contexto, historial
- ia_logic.py      prompts y llamadas a la IA
- cv_export.py     orden cronologico, vinetas y render del PDF
- models.py        modelos Pydantic de request/response
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import perfil_store
from cv_export import construir_cv_pdf, ordenar_experiencia_reciente
from ia_client import get_ia, reload_ia
from ia_logic import (
    analizar_contexto_logic,
    extraer_texto_pdf,
    optimizar_cv_con_ia,
    proponer_perfil_desde_texto,
    rellenar_campo,
)
from models import (
    AnalizarRequest,
    AplicarPerfilRequest,
    ConfigurarKeysRequest,
    GenerarCVRequest,
    RellenarRequest,
    RellenarResponse,
    Respuesta,
)

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

IA = get_ia()

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


@app.get("/ping")
def ping():
    ctx = perfil_store.get_contexto() or {}
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
        "propuesta_pendiente": perfil_store.PROPUESTA_PATH.exists(),
        "keys_configuradas": estado_ia["deepseek_configurado"],
        "ia_disponible": estado_ia["alguno_disponible"],
        "historial_total": len(perfil_store.cargar_historial()),
    }


# ─── Gestion de API keys ──────────────────────────────────────────
@app.get("/estado_keys")
def estado_keys():
    """Devuelve el estado de configuracion de las API keys (sin exponer valores)."""
    return IA.estado()


@app.post("/configurar_keys")
def configurar_keys(req: ConfigurarKeysRequest):
    """Recibe las API keys desde la extension, las escribe al .env y reinicia
    los clientes IA.
    - deepseek_api_key: DeepSeek para texto (obligatoria).
    - gemini_api_key: Gemini para vision (opcional, pero muy recomendada).
    Compatible con nombres viejos (groq_api_key) para no romper la extension."""
    dk = (req.deepseek_api_key or "").strip()
    gk = (req.gemini_api_key or "").strip()
    if not dk and not gk:
        # Retrocompat: si solo mandan gemini_api_key (antes era el unico campo)
        dk = dk or (req.groq_api_key or "").strip()

    if not dk:
        raise HTTPException(status_code=400, detail="Debes enviar al menos la API key de DeepSeek.")

    actual = perfil_store.leer_env_actual()
    actual["DEEPSEEK_API_KEY"] = dk
    if gk:
        actual["GEMINI_API_KEY"] = gk
    elif "GEMINI_API_KEY" in actual:
        # Si no mandaron gemini key pero ya existia, la conservamos
        pass
    # Limpia keys viejas de proveedores eliminados
    actual.pop("GROQ_API_KEY", None)

    try:
        perfil_store.escribir_env(actual)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No pude escribir el .env: {e}")

    log.info(f"/configurar_keys: deepseek_key={'si' if dk else 'no'}, gemini_key={'si' if gk else 'no'}")
    estado = reload_ia()
    return {"ok": True, **estado}


# ─── Perfil + propuesta de perfil desde PDF ───────────────────────
@app.get("/perfil_actual")
def perfil_actual():
    return perfil_store.get_perfil()


@app.get("/perfil_propuesto")
def perfil_propuesto():
    propuesta = perfil_store.cargar_propuesta_disco()
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

    perfil_store.guardar_propuesta_disco(propuesto)
    log.info(f"  Propuesta guardada en {perfil_store.PROPUESTA_PATH.name}")

    return {
        "ok": True,
        "actual": perfil_store.get_perfil(),
        "propuesto": propuesto,
        "campos_detectados": list(propuesto.keys()),
    }


@app.post("/aplicar_perfil")
def aplicar_perfil(req: AplicarPerfilRequest):
    if not req.perfil or not isinstance(req.perfil, dict):
        raise HTTPException(status_code=400, detail="Perfil invalido")

    backup_path = perfil_store.guardar_perfil(req.perfil)
    log.info(f"/aplicar_perfil: backup en {backup_path.name}")

    perfil_store.descartar_propuesta_disco()

    return {"ok": True, "backup": backup_path.name}


@app.post("/descartar_propuesta")
def descartar_propuesta():
    perfil_store.descartar_propuesta_disco()
    return {"ok": True}


# ─── Generar CV (reescrito con keywords del historial) ────────────
@app.post("/generar_cv")
def generar_cv(req: GenerarCVRequest):
    # Base: el borrador que mande la pestana (con experiencia recien agregada) o,
    # si no manda nada, el perfil guardado. Siempre copia: no tocamos perfil.json.
    base = req.perfil if isinstance(req.perfil, dict) and req.perfil else perfil_store.get_perfil()
    cv = json.loads(json.dumps(base))
    # score_minimo=60: el CV es generalista (sirve para varias postulaciones
    # del mismo rubro, no una a medida por oferta), asi que solo se cuentan
    # keywords de ofertas donde el candidato calificaba razonablemente. Sin
    # este filtro, buscar en rubros distintos mezcla vocabulario sin relacion.
    keywords = [k["keyword"] for k in perfil_store.top_keywords_faltantes(score_minimo=60)][:15]
    optimizado = False

    clasificacion = {"tiene": [], "transferible": [], "no_tiene": []}
    razones: dict[str, str] = {}
    if req.optimizar and keywords:
        opt = optimizar_cv_con_ia(cv, keywords)
        if opt:
            if opt.get("perfil_profesional"):
                cv["perfil_profesional"] = opt["perfil_profesional"]
            # Solo reemplazamos el texto de cada experiencia, por indice,
            # conservando cargo/empresa/ubicacion/periodo originales (anti-invento).
            exp_opt = opt.get("experiencia") or []
            for i, e in enumerate(cv.get("experiencia", [])):
                if i >= len(exp_opt) or not isinstance(exp_opt[i], dict):
                    continue
                vinetas = exp_opt[i].get("vinetas")
                if isinstance(vinetas, list) and vinetas:
                    e["vinetas"] = [str(v).strip() for v in vinetas if str(v).strip()]
                    e.pop("descripcion", None)  # el render usa vinetas
                elif exp_opt[i].get("descripcion"):  # compat con formato viejo
                    e["descripcion"] = exp_opt[i]["descripcion"]
            if isinstance(opt.get("habilidades"), list) and opt["habilidades"]:
                cv["habilidades"] = opt["habilidades"]
            cl = opt.get("clasificacion") or {}
            for k in clasificacion:
                v = cl.get(k)
                if isinstance(v, list):
                    for item in v:
                        # Item viene como {"keyword": "...", "razon": "..."};
                        # tambien acepta un string plano por si la IA no
                        # sigue el schema al pie de la letra.
                        if isinstance(item, dict):
                            kw = str(item.get("keyword", "")).strip()
                            razon = str(item.get("razon", "")).strip()
                        else:
                            kw = str(item).strip()
                            razon = ""
                        if not kw:
                            continue
                        clasificacion[k].append(kw)
                        if razon:
                            razones[kw] = razon
            optimizado = True

    # Orden cronologico: empleo mas reciente primero (no por relevancia).
    cv["experiencia"] = ordenar_experiencia_reciente(cv.get("experiencia", []))

    log.info(
        f"/generar_cv: optimizado={optimizado}, keywords={len(keywords)}, "
        f"tiene={len(clasificacion['tiene'])} transferible={len(clasificacion['transferible'])} "
        f"no_tiene={len(clasificacion['no_tiene'])}"
    )
    return {
        "ok": True,
        "cv": cv,
        "keywords_disponibles": keywords,
        "optimizado": optimizado,
        "clasificacion": clasificacion,
        "razones": razones,  # por que cada keyword cayo en su categoria (aun no se muestra en el popup)
        "por_aprender": clasificacion["no_tiene"],  # nunca entran al CV
    }


@app.post("/generar_cv_pdf")
def generar_cv_pdf(req: GenerarCVRequest):
    """Devuelve el CV como PDF nativo. El front manda el cvActual ya optimizado;
    aqui solo se renderiza (no se vuelve a llamar a la IA)."""
    base = req.perfil if isinstance(req.perfil, dict) and req.perfil else perfil_store.get_perfil()
    cv = json.loads(json.dumps(base))
    cv["experiencia"] = ordenar_experiencia_reciente(cv.get("experiencia", []))
    try:
        pdf_bytes = construir_cv_pdf(cv)
    except Exception as e:
        log.error(f"/generar_cv_pdf: fallo al construir PDF: {e}")
        raise HTTPException(status_code=500, detail=f"No pude generar el PDF: {e}")

    nombre = re.sub(r"[^\w\-]+", "_", (cv.get("nombre") or "CV").strip()) or "CV"
    log.info(f"/generar_cv_pdf: {len(pdf_bytes)} bytes, nombre='{nombre}'")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="CV_{nombre}.pdf"'},
    )


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


@app.get("/historial_keywords")
def historial_keywords():
    historial = perfil_store.cargar_historial()
    return {
        "ok": True,
        "total": len(historial),
        "max": perfil_store.HISTORIAL_MAX,
        "entradas": list(reversed(historial)),  # mas reciente primero
        "top_faltantes": perfil_store.top_keywords_faltantes(historial),
    }


@app.post("/limpiar_historial")
def limpiar_historial():
    try:
        if perfil_store.HISTORIAL_PATH.exists():
            perfil_store.HISTORIAL_PATH.unlink()
    except Exception as e:
        log.warning(f"No pude borrar {perfil_store.HISTORIAL_PATH.name}: {e}")
    return {"ok": True}


@app.post("/limpiar_contexto")
def limpiar_contexto():
    perfil_store.set_contexto(None)
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
    ctx_inicial = perfil_store.get_contexto()

    print("=" * 70)
    print("  IZIPEGA — SERVIDOR LOCAL (DeepSeek)")
    print("=" * 70)
    print()
    print(f"  Log:    {LOG_FILE}")
    print(f"  Perfil: {perfil_store.PERFIL_PATH.name}")
    print(
        "  IA:     "
        f"DeepSeek={'OK' if estado_inicial['deepseek_activo'] else 'no configurada'}"
    )
    if not estado_inicial["alguno_disponible"]:
        print("          (configura tu key desde la extension al abrirla)")
    if ctx_inicial:
        print(
            f"  Contexto previo: {ctx_inicial.get('cargo_objetivo', '?')} "
            f"@ {ctx_inicial.get('empresa', '?')}"
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
    print("    3) Abre el panel lateral: pega tu key de DeepSeek")
    print("       la primera vez. Luego funciona en cualquier formulario.")
    print()
    print("  Ctrl+C para detener.")
    print("=" * 70)

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
