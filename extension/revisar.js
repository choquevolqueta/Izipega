// revisar.js — Vista de revision de propuesta de perfil

const SERVER_URL = "http://localhost:8765";

const $ = (sel) => document.querySelector(sel);

const statusPill = $("#status-pill");
const resumenEl = $("#resumen");
const seccionesEl = $("#secciones");
const btnAceptar = $("#btn-aceptar");
const btnCancelar = $("#btn-cancelar");
const modoVisualBtn = $("#modo-visual");
const modoJsonBtn = $("#modo-json");
const vistaVisual = $("#vista-visual");
const vistaJson = $("#vista-json");
const jsonEditor = $("#json-editor");
const jsonError = $("#json-error");

let perfilActual = null;
let perfilPropuesto = null;
let modoActivo = "visual";

// ──────────────────────────────────────────────────────────────────
// CARGA INICIAL
// ──────────────────────────────────────────────────────────────────
async function cargar() {
  try {
    const [rActual, rProp] = await Promise.all([
      fetch(`${SERVER_URL}/perfil_actual`),
      fetch(`${SERVER_URL}/perfil_propuesto`),
    ]);
    if (!rActual.ok) throw new Error(`perfil_actual: HTTP ${rActual.status}`);
    if (rProp.status === 404) {
      statusPill.textContent = "sin propuesta";
      statusPill.className = "pill pill-error";
      resumenEl.textContent =
        "No hay propuesta pendiente. Sube un PDF desde el popup para generar una.";
      btnAceptar.disabled = true;
      return;
    }
    if (!rProp.ok) throw new Error(`perfil_propuesto: HTTP ${rProp.status}`);

    perfilActual = await rActual.json();
    perfilPropuesto = await rProp.json();

    renderResumen();
    renderVisual();
    jsonEditor.value = JSON.stringify(perfilPropuesto, null, 4);

    statusPill.textContent = "lista para aplicar";
    statusPill.className = "pill pill-ok";
  } catch (e) {
    statusPill.textContent = "error";
    statusPill.className = "pill pill-error";
    resumenEl.textContent = `No pude cargar los datos: ${e.message}`;
    btnAceptar.disabled = true;
  }
}

// ──────────────────────────────────────────────────────────────────
// COMPARACION
// ──────────────────────────────────────────────────────────────────
function esVacio(v) {
  if (v === null || v === undefined) return true;
  if (typeof v === "string") return v.trim() === "";
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v).length === 0;
  return false;
}

function igual(a, b) {
  if (a === b) return true;
  if (esVacio(a) && esVacio(b)) return true;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

function estadoCampo(actual, propuesto) {
  if (igual(actual, propuesto)) return "igual";
  if (esVacio(actual)) return "nuevo";
  return "modificado";
}

// ──────────────────────────────────────────────────────────────────
// RESUMEN
// ──────────────────────────────────────────────────────────────────
function renderResumen() {
  const claves = new Set([
    ...Object.keys(perfilActual),
    ...Object.keys(perfilPropuesto),
  ]);
  let cambiados = 0;
  let nuevos = 0;
  for (const k of claves) {
    const est = estadoCampo(perfilActual[k], perfilPropuesto[k]);
    if (est === "modificado") cambiados++;
    if (est === "nuevo") nuevos++;
  }
  resumenEl.innerHTML =
    `Se detectaron <strong>${cambiados}</strong> campos modificados y ` +
    `<strong>${nuevos}</strong> campos nuevos. Revisa antes de aplicar.`;
}

// ──────────────────────────────────────────────────────────────────
// RENDER DE VALORES
// ──────────────────────────────────────────────────────────────────
function renderValor(v) {
  if (esVacio(v)) {
    return `<span class="vacio">(vacio)</span>`;
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return `<span class="vacio">(vacio)</span>`;
    if (typeof v[0] === "string" || typeof v[0] === "number") {
      return (
        `<ul class="lista">` +
        v.map((it) => `<li>${escapeHtml(String(it))}</li>`).join("") +
        `</ul>`
      );
    }
    // array de objetos
    return v.map((obj) => renderObjeto(obj)).join("");
  }
  if (typeof v === "object") {
    return renderObjeto(v);
  }
  return escapeHtml(String(v));
}

function renderObjeto(obj) {
  if (!obj || typeof obj !== "object") return "";
  const items = Object.entries(obj)
    .filter(([, val]) => !esVacio(val))
    .map(
      ([k, val]) =>
        `<div><strong>${escapeHtml(k)}:</strong> ${escapeHtml(
          typeof val === "object" ? JSON.stringify(val) : String(val)
        )}</div>`
    );
  return `<div class="obj-card">${items.join("")}</div>`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ──────────────────────────────────────────────────────────────────
// VISTA VISUAL
// ──────────────────────────────────────────────────────────────────
// Agrupa los campos por seccion para que sea mas digerible.
const SECCIONES = [
  {
    titulo: "Datos personales",
    claves: ["nombre", "edad", "ciudad", "comuna", "telefono", "email", "nacionalidad"],
  },
  { titulo: "Perfil profesional", claves: ["perfil_profesional", "motivacion"] },
  { titulo: "Experiencia", claves: ["experiencia"] },
  { titulo: "Estudios", claves: ["estudios"] },
  { titulo: "Habilidades", claves: ["habilidades", "herramientas", "fortalezas"] },
  { titulo: "Idiomas", claves: ["idiomas"] },
  {
    titulo: "Preferencias laborales",
    claves: ["disponibilidad", "expectativa_sueldo", "modalidad_preferida"],
  },
  { titulo: "Respuestas frecuentes", claves: ["respuestas_extra"] },
  { titulo: "Otros", claves: ["cv_archivo"] },
];

function renderVisual() {
  seccionesEl.innerHTML = "";

  // claves no listadas explicitamente: anadirlas a "Otros"
  const conocidas = new Set(SECCIONES.flatMap((s) => s.claves));
  const todasClaves = new Set([
    ...Object.keys(perfilActual),
    ...Object.keys(perfilPropuesto),
  ]);
  const extras = [...todasClaves].filter((k) => !conocidas.has(k));
  if (extras.length) {
    SECCIONES[SECCIONES.length - 1].claves.push(...extras);
  }

  for (const sec of SECCIONES) {
    const camposHtml = [];
    let estadoSeccion = "igual";
    let cambios = 0;
    let nuevos = 0;

    for (const k of sec.claves) {
      const actual = perfilActual[k];
      const propuesto = perfilPropuesto[k];
      const est = estadoCampo(actual, propuesto);
      if (est === "modificado") {
        cambios++;
        estadoSeccion = "modificado";
      } else if (est === "nuevo") {
        nuevos++;
        if (estadoSeccion === "igual") estadoSeccion = "nuevo";
      }

      // No mostrar campos que ambos lados tienen vacios
      if (esVacio(actual) && esVacio(propuesto)) continue;

      const cls =
        est === "modificado"
          ? "campo cambiado"
          : est === "nuevo"
          ? "campo nuevo"
          : "campo";

      camposHtml.push(
        `<div class="${cls}">
          <div class="campo-nombre">${escapeHtml(k)}</div>
          <div class="campo-actual">${renderValor(actual)}</div>
          <div class="campo-propuesto">${renderValor(propuesto)}</div>
        </div>`
      );
    }

    if (!camposHtml.length) continue;

    const tag =
      cambios + nuevos === 0
        ? `<span class="seccion-estado estado-igual">sin cambios</span>`
        : `<span class="seccion-estado estado-${
            estadoSeccion === "modificado" ? "modificado" : "nuevo"
          }">${cambios} cambios · ${nuevos} nuevos</span>`;

    seccionesEl.insertAdjacentHTML(
      "beforeend",
      `<section class="seccion">
        <div class="seccion-header">
          <div class="seccion-titulo">${escapeHtml(sec.titulo)}</div>
          ${tag}
        </div>
        <div class="seccion-body">
          <div class="campo" style="border:none; color:#888; font-size:11px; text-transform:uppercase;">
            <div></div><div>Actual</div><div>Propuesto</div>
          </div>
          ${camposHtml.join("")}
        </div>
      </section>`
    );
  }
}

// ──────────────────────────────────────────────────────────────────
// MODO TOGGLE
// ──────────────────────────────────────────────────────────────────
function setModo(modo) {
  modoActivo = modo;
  if (modo === "visual") {
    vistaVisual.classList.remove("hidden");
    vistaJson.classList.add("hidden");
    modoVisualBtn.classList.add("activo");
    modoJsonBtn.classList.remove("activo");
  } else {
    vistaVisual.classList.add("hidden");
    vistaJson.classList.remove("hidden");
    modoVisualBtn.classList.remove("activo");
    modoJsonBtn.classList.add("activo");
  }
}

// ──────────────────────────────────────────────────────────────────
// ACCIONES
// ──────────────────────────────────────────────────────────────────
async function aceptar() {
  let perfilFinal;
  if (modoActivo === "json") {
    try {
      perfilFinal = JSON.parse(jsonEditor.value);
      jsonError.classList.add("hidden");
    } catch (e) {
      jsonError.textContent = `JSON invalido: ${e.message}`;
      jsonError.classList.remove("hidden");
      return;
    }
  } else {
    perfilFinal = perfilPropuesto;
  }

  btnAceptar.disabled = true;
  btnAceptar.textContent = "Guardando...";

  try {
    const r = await fetch(`${SERVER_URL}/aplicar_perfil`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ perfil: perfilFinal }),
    });
    if (!r.ok) {
      const t = await r.text().catch(() => "");
      throw new Error(`HTTP ${r.status}: ${t.slice(0, 200)}`);
    }
    const data = await r.json();
    statusPill.textContent = `aplicado (backup: ${data.backup})`;
    statusPill.className = "pill pill-ok";
    btnAceptar.textContent = "Guardado";
    setTimeout(() => window.close(), 1500);
  } catch (e) {
    statusPill.textContent = `error: ${e.message}`;
    statusPill.className = "pill pill-error";
    btnAceptar.disabled = false;
    btnAceptar.textContent = "Aceptar y guardar";
  }
}

async function cancelar() {
  if (
    !confirm(
      "Descartar la propuesta? El perfil actual no se modifica, pero se borra el archivo de propuesta."
    )
  )
    return;
  try {
    await fetch(`${SERVER_URL}/descartar_propuesta`, { method: "POST" });
  } catch (e) {
    // ignorar
  }
  window.close();
}

// ──────────────────────────────────────────────────────────────────
// EVENTOS
// ──────────────────────────────────────────────────────────────────
modoVisualBtn.addEventListener("click", () => setModo("visual"));
modoJsonBtn.addEventListener("click", () => setModo("json"));
btnAceptar.addEventListener("click", aceptar);
btnCancelar.addEventListener("click", cancelar);

// Validacion en tiempo real del JSON editor
jsonEditor.addEventListener("input", () => {
  try {
    JSON.parse(jsonEditor.value);
    jsonError.classList.add("hidden");
  } catch (e) {
    jsonError.textContent = `JSON invalido: ${e.message}`;
    jsonError.classList.remove("hidden");
  }
});

cargar();
