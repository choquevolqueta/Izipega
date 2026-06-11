// cv.js — Genera y muestra un CV imprimible a partir del perfil + keywords del historial.

const SERVER_URL = "http://localhost:8765";
const $ = (s) => document.querySelector(s);

const statusPill = $("#status-pill");
const chkOptimizar = $("#chk-optimizar");
const btnRegenerar = $("#btn-regenerar");
const btnGuardarPerfil = $("#btn-guardar-perfil");
const btnPdf = $("#btn-pdf");
const keywordsAviso = $("#keywords-aviso");
const panelBrechas = $("#panel-brechas");
const cvEl = $("#cv");

// Mini-formulario de experiencia
const btnToggleExp = $("#btn-toggle-exp");
const formExp = $("#form-exp");
const btnExpAdd = $("#btn-exp-add");
const btnExpCancelar = $("#btn-exp-cancelar");

// Estado:
//  - draftBase: perfil de trabajo SIN optimizar. Es lo que se re-optimiza y lo
//    que se va editando al agregar experiencia. Arranca como el perfil guardado.
//  - cvActual: lo que se ve / descarga / guarda (puede estar ya optimizado).
let draftBase = null;
let cvActual = null;

function setStatus(texto, tipo = "info") {
  statusPill.textContent = texto;
  statusPill.className = `pill pill-${tipo}`;
}

// Escapa HTML para no romper el layout con caracteres especiales del perfil.
function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

// Devuelve las vinetas de una experiencia. Usa e.vinetas (IA, formato Harvard)
// si existen; si no, divide la descripcion-parrafo del CV base en oraciones.
function aVinetas(e) {
  if (Array.isArray(e.vinetas) && e.vinetas.length) {
    return e.vinetas.map((v) => String(v).trim()).filter(Boolean);
  }
  const desc = String(e.descripcion || "").trim();
  if (!desc) return [];
  return desc
    .split(/(?<=[.;])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 1);
}

function render(cv) {
  const rol = cv.estudios?.[0]?.titulo || "";
  const ubic = [cv.comuna, cv.ciudad].filter(Boolean).join(", ");
  const redes = cv.redes || {};

  const contacto = [
    cv.telefono && `<span>${esc(cv.telefono)}</span>`,
    cv.email && `<span><a href="mailto:${esc(cv.email)}">${esc(cv.email)}</a></span>`,
    ubic && `<span>${esc(ubic)}</span>`,
    cv.nacionalidad && `<span>${esc(cv.nacionalidad)}</span>`,
    redes.linkedin && `<span><a href="${esc(redes.linkedin)}">LinkedIn</a></span>`,
    redes.portafolio_web && `<span><a href="${esc(redes.portafolio_web)}">Portafolio</a></span>`,
    redes.behance && `<span><a href="${esc(redes.behance)}">Behance</a></span>`,
  ].filter(Boolean).join("");

  const experiencia = (cv.experiencia || []).map((e) => {
    const lugar = [e.empresa, e.ubicacion].filter(Boolean).join(" · ");
    const vinetas = aVinetas(e);
    const cuerpo = vinetas.length
      ? `<ul class="cv-exp-bullets">${vinetas.map((v) => `<li>${esc(v)}</li>`).join("")}</ul>`
      : "";
    return `
      <div class="cv-exp">
        <div class="cv-exp-head">
          <div><span class="cv-exp-cargo">${esc(e.cargo)}</span></div>
          <div class="cv-exp-periodo">${esc(e.periodo || "")}</div>
        </div>
        <div class="cv-exp-empresa">${esc(lugar)}</div>
        ${cuerpo}
      </div>`;
  }).join("");

  const estudios = (cv.estudios || []).map((s) => `
    <div class="cv-estudio">
      <div class="cv-estudio-titulo">${esc(s.titulo)}</div>
      <div class="cv-estudio-sub">${esc([s.institucion, s.ubicacion, s.anio_egreso].filter(Boolean).join(" · "))}</div>
    </div>`).join("");

  const idiomas = (cv.idiomas || []).map((i) =>
    `<div class="cv-idioma"><b>${esc(i.idioma)}</b> <span>${esc(i.nivel)}</span></div>`
  ).join("");

  const secciones = [];
  if (cv.perfil_profesional) {
    secciones.push(`<section class="cv-seccion"><h2>Perfil profesional</h2><p class="cv-resumen">${esc(cv.perfil_profesional)}</p></section>`);
  }
  if (experiencia) {
    secciones.push(`<section class="cv-seccion"><h2>Experiencia</h2>${experiencia}</section>`);
  }
  if (estudios) {
    secciones.push(`<section class="cv-seccion"><h2>Formación</h2>${estudios}</section>`);
  }
  // Habilidades: una sola seccion (habilidades + herramientas) en texto por
  // comas, estilo Harvard. Las fortalezas se integran en el perfil profesional.
  const skills = [...(cv.habilidades || []), ...(cv.herramientas || [])]
    .map((s) => String(s).trim())
    .filter(Boolean);
  const skillsUnicas = [...new Set(skills)];
  if (skillsUnicas.length) {
    secciones.push(`<section class="cv-seccion"><h2>Habilidades</h2><p class="cv-skill-line">${esc(skillsUnicas.join(", "))}</p></section>`);
  }
  if (idiomas) {
    secciones.push(`<section class="cv-seccion"><h2>Idiomas</h2><div class="cv-idiomas">${idiomas}</div></section>`);
  }

  cvEl.innerHTML = `
    <h1 class="cv-nombre">${esc(cv.nombre || "")}</h1>
    ${rol ? `<div class="cv-titulo-rol">${esc(rol)}</div>` : ""}
    <div class="cv-contacto">${contacto}</div>
    ${secciones.join("")}`;
}

// Panel de transparencia: muestra qué hizo la IA con cada keyword. NO se imprime.
function renderBrechas(clasif) {
  clasif = clasif || {};
  const tiene = clasif.tiene || [];
  const transf = clasif.transferible || [];
  const aprender = clasif.no_tiene || [];
  if (!tiene.length && !transf.length && !aprender.length) {
    panelBrechas.classList.add("hidden");
    return;
  }
  const grupo = (titulo, sub, items, dotCls, chipCls) =>
    items.length
      ? `<div class="brecha-grupo">
           <div class="brecha-titulo"><span class="dot ${dotCls}"></span>${titulo} <small>${sub}</small></div>
           <div class="brecha-chips">${items.map((t) => `<span class="chip ${chipCls}">${esc(t)}</span>`).join("")}</div>
         </div>`
      : "";
  panelBrechas.innerHTML = `
    <h3>Cómo usé las keywords (esto NO sale en el PDF)</h3>
    <p class="sub">La IA solo escribe en tu CV lo que tu perfil respalda. Tú tienes la última palabra.</p>
    ${grupo("Reflejadas en tu CV", "ya las tenías, con otras palabras", tiene, "dot-tiene", "chip-tiene")}
    ${grupo("Mencionadas como transferibles", "algo cercano, sin afirmar el término exacto", transf, "dot-transf", "chip-transf")}
    ${grupo("Por aprender", "no están en tu CV: brechas reales para calificar a esas ofertas", aprender, "dot-aprender", "chip-aprender")}`;
  panelBrechas.classList.remove("hidden");
}

function setBusy(busy) {
  btnRegenerar.disabled = busy;
  btnPdf.disabled = busy;
  btnGuardarPerfil.disabled = busy;
  btnExpAdd.disabled = busy;
}

async function generar(optimizar) {
  setStatus(optimizar ? "Optimizando con IA…" : "Generando…", "info");
  setBusy(true);
  cvEl.innerHTML = `<p class="cargando">${optimizar ? "La IA está reescribiendo tu CV con las keywords que más te han faltado…" : "Generando tu CV…"}</p>`;
  keywordsAviso.classList.add("hidden");
  panelBrechas.classList.add("hidden");
  panelBrechas.innerHTML = "";

  try {
    const body = { optimizar };
    if (draftBase) body.perfil = draftBase; // optimiza/normaliza el borrador actual
    const r = await fetch(`${SERVER_URL}/generar_cv`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();

    cvActual = data.cv;
    // El render sin IA es nuestra "base" normalizada y ordenada cronológicamente.
    if (!optimizar) draftBase = JSON.parse(JSON.stringify(data.cv));
    render(cvActual);

    const kws = data.keywords_disponibles || [];
    keywordsAviso.classList.remove("hidden");
    if (data.optimizado && kws.length) {
      keywordsAviso.innerHTML = `Optimizado con <b>${kws.length}</b> keyword(s) del historial: ${esc(kws.join(", "))}`;
      setStatus("CV optimizado con IA ✓", "ok");
    } else if (kws.length) {
      keywordsAviso.innerHTML = `Tienes <b>${kws.length}</b> keyword(s) acumuladas del historial. Marca <b>“Optimizar con IA”</b> y pulsa <b>Regenerar</b> para reescribir tu CV con ellas.`;
      setStatus("CV base generado ✓", "ok");
    } else {
      keywordsAviso.innerHTML = `Aún no hay keywords acumuladas. Analiza algunas ofertas con Izipega y vuelve: entonces podré optimizar tu CV con lo que más te piden. Por ahora refleja tu perfil tal cual.`;
      setStatus(optimizar ? "Sin keywords aún" : "CV base generado ✓", optimizar ? "warn" : "ok");
    }

    if (data.optimizado) renderBrechas(data.clasificacion);
  } catch (e) {
    setStatus("Error: ¿está el servidor encendido?", "error");
    cvEl.innerHTML = `<p class="cargando">No pude generar el CV. Verifica que el servidor esté corriendo en localhost:8765.<br><small>${esc(e.message)}</small></p>`;
  } finally {
    setBusy(false);
  }
}

function limpiarFormExp() {
  ["#exp-cargo", "#exp-empresa", "#exp-ubicacion", "#exp-periodo", "#exp-descripcion"].forEach((s) => {
    $(s).value = "";
  });
}

// Agrega una experiencia al borrador y re-genera (el servidor la ordena cronológicamente).
async function agregarExperiencia(exp) {
  if (!draftBase) return;
  draftBase.experiencia = draftBase.experiencia || [];
  draftBase.experiencia.push(exp);
  await generar(false);
}

// Reemplaza el perfil guardado con el CV actual (con respaldo automático del servidor).
async function guardarEnPerfil() {
  if (!cvActual) return;
  const ok = window.confirm(
    "Esto reemplazará tu perfil guardado con el CV que ves ahora (redacción optimizada y experiencia agregada). " +
    "Se hace un respaldo automático por si quieres volver atrás.\n\n¿Continuar?"
  );
  if (!ok) return;
  setStatus("Guardando en tu perfil…", "info");
  setBusy(true);
  try {
    const r = await fetch(`${SERVER_URL}/aplicar_perfil`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ perfil: cvActual }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    // Adoptamos lo guardado como nueva base de trabajo.
    draftBase = JSON.parse(JSON.stringify(cvActual));
    setStatus(`Perfil actualizado ✓ (respaldo: ${data.backup || "ok"})`, "ok");
  } catch (e) {
    setStatus("No pude guardar el perfil", "error");
  } finally {
    setBusy(false);
  }
}

// Descarga el CV como PDF nativo generado por el servidor. NO usamos
// window.print(): ese PDF del navegador sale con una capa de texto que los
// lectores de CV de portales (Laborum/Bumeran) no pueden extraer ("sube pero
// queda vacío"). El del servidor lleva texto real, parseable por cualquier ATS.
async function descargarPdf() {
  if (!cvActual) return;
  setStatus("Generando PDF…", "info");
  setBusy(true);
  try {
    const r = await fetch(`${SERVER_URL}/generar_cv_pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ perfil: cvActual }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const nombre = (cvActual.nombre || "CV").trim().replace(/\s+/g, "_");
    a.download = `CV_${nombre}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus("PDF descargado ✓", "ok");
  } catch (e) {
    setStatus("No pude generar el PDF (¿servidor encendido?)", "error");
  } finally {
    setBusy(false);
  }
}

// ── Listeners ──
btnRegenerar.addEventListener("click", () => generar(chkOptimizar.checked));
btnPdf.addEventListener("click", descargarPdf);
btnGuardarPerfil.addEventListener("click", guardarEnPerfil);

btnToggleExp.addEventListener("click", () => formExp.classList.toggle("hidden"));
btnExpCancelar.addEventListener("click", () => {
  formExp.classList.add("hidden");
  limpiarFormExp();
});
btnExpAdd.addEventListener("click", async () => {
  const exp = {
    cargo: $("#exp-cargo").value.trim(),
    empresa: $("#exp-empresa").value.trim(),
    ubicacion: $("#exp-ubicacion").value.trim(),
    periodo: $("#exp-periodo").value.trim(),
    descripcion: $("#exp-descripcion").value.trim(),
  };
  if (!exp.cargo) {
    window.alert("El cargo es obligatorio.");
    return;
  }
  formExp.classList.add("hidden");
  limpiarFormExp();
  await agregarExperiencia(exp);
});

// Carga inicial: CV base SIN IA (instantáneo, no gasta tokens). La optimización
// solo corre cuando el usuario lo pide con "Regenerar", y solo vale la pena
// cuando ya hay keywords acumuladas en el historial.
generar(false);
