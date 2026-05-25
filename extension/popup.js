// popup.js — UI de Izipega. Orquesta extension <-> servidor local.

const SERVER_URL = "http://localhost:8765";

const $ = (sel) => document.querySelector(sel);
const statusEl = $("#status");
const statusTxt = $("#status .txt");
const ctxCargo = $("#ctx-cargo");
const ctxEmpresa = $("#ctx-empresa");
const btnAnalizar = $("#btn-analizar");
const btnRellenar = $("#btn-rellenar");
const btnForzar = $("#btn-forzar");
const scoreBox = $("#score-box");
const scoreNum = $("#score-num");
const scoreFill = $("#score-fill");
const scoreJustif = $("#score-justificacion");
const kwCoincidentes = $("#kw-coincidentes");
const kwFaltantes = $("#kw-faltantes");
const logBody = $("#log-body");
const dropZone = $("#drop-zone");
const inputPdf = $("#input-pdf");
const btnElegirPdf = $("#btn-elegir-pdf");
const propuestaAviso = $("#propuesta-aviso");
const btnAbrirRevision = $("#btn-abrir-revision");
const panelConfigKeys = $("#config-keys");
const inputGeminiKey = $("#input-gemini-key");
const inputGroqKey = $("#input-groq-key");
const btnGuardarKeys = $("#btn-guardar-keys");
const btnConfigKeys = $("#btn-config-keys");
const btnCerrarConfig = $("#btn-cerrar-config");
const estadoConfigEl = $("#config-keys-estado");

function log(msg, tipo = "info") {
  const hora = new Date().toLocaleTimeString();
  const div = document.createElement("div");
  div.className = `log-line ${tipo}`;
  div.innerHTML = `<span class="time">${hora}</span><span class="msg"></span>`;
  div.querySelector(".msg").textContent = msg;
  logBody.appendChild(div);
  logBody.scrollTop = logBody.scrollHeight;
}

// Estado de procesamiento: spinner en el boton activo + barra superior.
const barraProgreso = $("#barra-progreso");
const botonesAccion = [btnAnalizar, btnRellenar, btnForzar];

function comenzarCargando(boton, texto = "Procesando...") {
  boton.dataset.textoOriginal = boton.textContent;
  boton.setAttribute("data-loading-text", texto);
  boton.classList.add("cargando");
  // Deshabilitar los otros para evitar disparos simultaneos
  for (const b of botonesAccion) {
    if (b !== boton) b.disabled = true;
  }
  barraProgreso.classList.add("activa");
}

function terminarCargando(boton) {
  boton.classList.remove("cargando");
  boton.removeAttribute("data-loading-text");
  if (boton.dataset.textoOriginal) {
    boton.textContent = boton.dataset.textoOriginal;
    delete boton.dataset.textoOriginal;
  }
  for (const b of botonesAccion) b.disabled = false;
  barraProgreso.classList.remove("activa");
}

async function conCargando(boton, texto, fn) {
  comenzarCargando(boton, texto);
  try {
    return await fn();
  } finally {
    terminarCargando(boton);
  }
}

function setStatus(ok, txt) {
  statusEl.className = `status ${ok ? "on" : "off"}`;
  statusTxt.textContent = txt;
}

function setContexto(cargo, empresa) {
  ctxCargo.textContent = cargo || "—";
  ctxEmpresa.textContent = empresa || "—";
  if (cargo && cargo !== "—") {
    btnAnalizar.textContent = "Re-analizar (descarta el actual)";
  } else {
    btnAnalizar.textContent = "Analizar contexto";
  }
}

function colorScore(n) {
  if (n >= 70) return "verde";
  if (n >= 40) return "amarillo";
  return "rojo";
}

function setScore(payload) {
  const score = payload?.score_idoneidad;
  if (typeof score !== "number") {
    scoreBox.classList.add("hidden");
    return;
  }
  const cls = colorScore(score);
  scoreNum.textContent = `${score}`;
  scoreNum.className = `score-num ${cls}`;
  scoreFill.className = `score-fill ${cls}`;
  scoreFill.style.width = `${Math.max(0, Math.min(100, score))}%`;
  scoreJustif.textContent = payload.justificacion || "";

  kwCoincidentes.innerHTML = "";
  for (const k of payload.keywords_coincidentes || []) {
    const tag = document.createElement("span");
    tag.className = "kw-tag ok";
    tag.textContent = k;
    kwCoincidentes.appendChild(tag);
  }
  if (!(payload.keywords_coincidentes || []).length) {
    kwCoincidentes.innerHTML = `<span class="muted">(ninguna)</span>`;
  }

  kwFaltantes.innerHTML = "";
  for (const k of payload.keywords_faltantes || []) {
    const tag = document.createElement("span");
    tag.className = "kw-tag miss";
    tag.textContent = k;
    kwFaltantes.appendChild(tag);
  }
  if (!(payload.keywords_faltantes || []).length) {
    kwFaltantes.innerHTML = `<span class="muted">(ninguna)</span>`;
  }

  scoreBox.classList.remove("hidden");
}

// ──────────────────────────────────────────────────────────────────
// COMUNICACION CON FRAMES
// ──────────────────────────────────────────────────────────────────
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function paginaAccesible(url) {
  if (!url) return false;
  return /^https?:/i.test(url) || /^file:/i.test(url);
}

// Cuenta campos visibles en cada frame; devuelve el frameId del frame con mas.
async function frameConMasCampos(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => {
      const visibles = (els) =>
        Array.from(els).filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        }).length;
      return (
        visibles(document.querySelectorAll(
          "input[type='text'], input[type='number'], input[type='tel'], input[type='email'], input[type='url'], input:not([type]), textarea, select, input[type='radio'], input[type='checkbox']"
        ))
      );
    },
  });
  let mejor = { frameId: 0, count: -1 };
  const desglose = [];
  for (const r of results) {
    const c = r.result ?? 0;
    desglose.push(`${r.frameId}:${c}`);
    if (c > mejor.count) {
      mejor = { frameId: r.frameId, count: c };
    }
  }
  mejor.desglose = desglose.join(" ");
  return mejor;
}

// Mide el tamano del contenido textual de cada frame; devuelve el con mas.
async function frameConMasContenido(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => {
      const sel = window.getSelection()?.toString() || "";
      if (sel.trim().length > 30) return sel.length + 100000; // prioriza seleccion
      return (document.body?.innerText || "").length;
    },
  });
  let mejor = { frameId: 0, count: -1 };
  for (const r of results) {
    if ((r.result ?? 0) > mejor.count) {
      mejor = { frameId: r.frameId, count: r.result ?? 0 };
    }
  }
  return mejor;
}

function sendToFrame(tabId, frameId, msg, timeoutMs = 8000) {
  return new Promise((resolve) => {
    let resuelto = false;
    const t = setTimeout(() => {
      if (resuelto) return;
      resuelto = true;
      resolve({ ok: false, error: `timeout ${timeoutMs}ms` });
    }, timeoutMs);
    chrome.tabs.sendMessage(tabId, msg, { frameId }, (resp) => {
      if (resuelto) return;
      resuelto = true;
      clearTimeout(t);
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        resolve(resp || { ok: false, error: "sin respuesta" });
      }
    });
  });
}

// Inyecta content.js en un frame especifico (no a todos). Util cuando el
// frame elegido es uno dinamico que se creo despues del primer inject.
async function inyectarEnFrame(tabId, frameId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId, frameIds: [frameId] },
      files: ["content.js"],
    });
    return true;
  } catch (e) {
    return false;
  }
}

// Inyecta el content script si todavia no esta cargado en la pestana.
// Necesario porque las pestanas que ya estaban abiertas cuando se recarga
// la extension no reciben el script automaticamente.
async function asegurarContentScript(tabId) {
  // Ping rapido al frame top: si responde, ya esta.
  const probe = await new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, { action: "ping" }, { frameId: 0 }, (resp) => {
      if (chrome.runtime.lastError) {
        resolve(null);
      } else {
        resolve(resp);
      }
    });
  });
  if (probe && probe.ok) return true;

  // Si no respondio, inyectar a todos los frames.
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ["content.js"],
    });
    return true;
  } catch (e) {
    // Pagina no inyectable (chrome://, chrome web store, etc.)
    return false;
  }
}

// ──────────────────────────────────────────────────────────────────
// SERVER HEALTH
// ──────────────────────────────────────────────────────────────────
async function pingServer() {
  try {
    const r = await fetch(`${SERVER_URL}/ping`, { method: "GET" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    setStatus(true, "servidor OK");
    if (data.contexto_cargado) {
      setContexto(data.cargo_objetivo, data.empresa);
      setScore(data);
    } else {
      setScore(null);
    }
    if (data.propuesta_pendiente) {
      propuestaAviso.classList.remove("hidden");
    } else {
      propuestaAviso.classList.add("hidden");
    }
    return true;
  } catch (e) {
    setStatus(false, "servidor offline");
    return false;
  }
}

// ──────────────────────────────────────────────────────────────────
// ACCIONES
// ──────────────────────────────────────────────────────────────────
async function accionAnalizar() {
  log("Leyendo contenido de la pestana...", "info");
  const tab = await activeTab();
  if (!tab?.id || !paginaAccesible(tab.url)) {
    log("Pestana no accesible (chrome://, extension, etc).", "error");
    return;
  }

  const inyectado = await asegurarContentScript(tab.id);
  if (!inyectado) {
    log("No pude inyectar el lector en esta pestana (chrome://, web store, etc).", "error");
    return;
  }

  let frame;
  try {
    frame = await frameConMasContenido(tab.id);
  } catch (e) {
    log(`No pude inspeccionar frames: ${e.message}`, "error");
    return;
  }

  const datos = await sendToFrame(tab.id, frame.frameId, { action: "leer_contexto" });
  if (!datos.ok) {
    log(`No pude leer la pagina: ${datos.error || "?"}`, "error");
    return;
  }
  if (!datos.titulo && !datos.descripcion) {
    log("No encontre titulo/descripcion. Selecciona un texto en la pagina y reintenta.", "error");
    return;
  }

  log(`Titulo: "${datos.titulo.slice(0, 60)}" (fuente: ${datos.fuente})`, "info");
  log(`Descripcion: ${datos.descripcion.length} chars. Analizando con IA...`, "info");

  // Captura del viewport: ayuda al analizador a identificar la oferta
  // visible cuando esta en un modal sobre una lista de busqueda, o cuando
  // leerContexto trae texto mezclado.
  let imagenBase64 = "";
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
    if (dataUrl) imagenBase64 = dataUrl;
  } catch (e) {
    log(`  No pude capturar pantalla: ${e.message}. Sigo solo con texto.`, "info");
  }

  try {
    const r = await fetch(`${SERVER_URL}/analizar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        titulo: datos.titulo,
        descripcion: datos.descripcion,
        imagen_base64: imagenBase64,
      }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const ctx = await r.json();
    setContexto(ctx.cargo_objetivo, ctx.empresa);
    setScore(ctx);
    log(`OK: ${ctx.cargo_objetivo || "(sin cargo)"} @ ${ctx.empresa || "(sin empresa)"}`, "ok");
    if (typeof ctx.score_idoneidad === "number") {
      log(`Idoneidad: ${ctx.score_idoneidad}/100`, "ok");
    }
  } catch (e) {
    log(`Error analizando: ${e.message}`, "error");
  }
}

// Helper: escanea con un retry interno que re-inyecta el frame si falla.
async function escanearConFallback(tabId, frame) {
  let scan = await sendToFrame(tabId, frame.frameId, { action: "escanear" });
  if (scan.ok) return scan;
  log(`Scan en frame ${frame.frameId} fallo (${scan.error}). Reinyectando...`, "info");
  const ok = await inyectarEnFrame(tabId, frame.frameId);
  if (!ok) {
    log(`No pude reinyectar content.js en frame ${frame.frameId}.`, "error");
    return scan;
  }
  scan = await sendToFrame(tabId, frame.frameId, { action: "escanear" });
  return scan;
}

async function accionRellenar(forzar = false) {
  log(forzar ? "Re-llenando (forzar)..." : "Rellenando formulario...", "info");
  ocultarRespuestasCuradas();
  const tab = await activeTab();
  if (!tab?.id || !paginaAccesible(tab.url)) {
    log("Pestana no accesible (chrome://, extension, etc).", "error");
    return;
  }

  const inyectado = await asegurarContentScript(tab.id);
  if (!inyectado) {
    log("No pude inyectar el lector en esta pestana (chrome://, web store, etc).", "error");
    return;
  }

  let frame;
  try {
    frame = await frameConMasCampos(tab.id);
  } catch (e) {
    log(`No pude inspeccionar frames: ${e.message}`, "error");
    return;
  }
  log(`Frame elegido: id=${frame.frameId}, campos=${frame.count} (todos: ${frame.desglose || "?"})`, "info");
  if (frame.count <= 0) {
    log("No detecte campos en ningun frame. Asegurate de tener un formulario visible.", "error");
    return;
  }

  if (forzar) {
    const lim = await sendToFrame(tab.id, frame.frameId, { action: "limpiar" });
    if (!lim.ok) log(`Limpiar fallo: ${lim.error || "?"}`, "info");
  }

  const scan = await escanearConFallback(tab.id, frame);
  if (!scan.ok) {
    log(`Scan fallo: ${scan.error || "?"}`, "error");
    log("Sugerencia: recarga la pagina (F5) y reintenta. Si persiste, revisa DevTools.", "info");
    return;
  }
  const campos = scan.campos || [];
  if (!campos.length) {
    log("No encontre campos vacios en este paso.", "info");
    return;
  }
  log(`Detectados ${campos.length} campos. Pidiendo respuestas a IA...`, "info");

  const titulo = ctxCargo.textContent !== "—" ? ctxCargo.textContent : "";
  let respuestas = [];

  // ── Vision per-field SIEMPRE: cada campo recibe su propia captura tras
  // hacer scroll. Lento pero precision maxima. La diferencia entre normal y
  // forzar es solo `usar_directas`: en normal, respuesta_directa() (regex)
  // resuelve campos obvios (telefono, correo, datos de contacto) SIN gastar
  // tokens de IA. En forzar, todo va a IA con vision.
  const usarDirectas = !forzar;
  log(`Vision per-field activa (${forzar ? "forzar: todo IA" : "normal: directas + IA"}).`, "info");
  for (let i = 0; i < campos.length; i++) {
    const c = campos[i];
    log(`[${i + 1}/${campos.length}] ${c.tipo} "${(c.label || "").slice(0, 50)}" - capturando...`, "info");
    // 1) Scroll into view para que el campo este en pantalla
    await sendToFrame(tab.id, frame.frameId, { action: "scroll_into_view", id: c.id });
    await new Promise((r) => setTimeout(r, 250));
    // 2) Captura del viewport visible
    let imagenBase64 = "";
    try {
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
      if (dataUrl) imagenBase64 = dataUrl;
    } catch (e) {
      log(`  No pude capturar pantalla: ${e.message}. Sigo con texto.`, "info");
    }
    // 3) Pedir respuesta al server (un solo campo)
    try {
      const r = await fetch(`${SERVER_URL}/rellenar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          titulo_contexto: titulo,
          campos: [c],
          usar_directas: usarDirectas,
          imagen_base64: imagenBase64,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      respuestas.push(...(data.respuestas || []));
    } catch (e) {
      log(`  Error en campo ${c.id}: ${e.message}`, "error");
      respuestas.push({ id: c.id, tipo: c.tipo, valor: "" });
    }
    // Rate limit defensivo: chrome.tabs.captureVisibleTab tiene cap ~2/s
    await new Promise((r) => setTimeout(r, 200));
  }

  // ── Aplicar al DOM con reintento ──────────────────────────────
  // Si el frame se quedo sin content.js o cambio de id entre el scan y el
  // apply, reintentamos una vez (re-detectar frame + reinyectar).
  let aplicar = await sendToFrame(tab.id, frame.frameId, {
    action: "aplicar",
    respuestas,
  });

  if (!aplicar.ok) {
    log(`Aplicar fallo (intento 1): ${aplicar.error || "?"}. Reintentando...`, "info");
    try {
      const frame2 = await frameConMasCampos(tab.id);
      log(`Reintento: frame id=${frame2.frameId}, campos=${frame2.count}`, "info");
      await inyectarEnFrame(tab.id, frame2.frameId);
      aplicar = await sendToFrame(tab.id, frame2.frameId, {
        action: "aplicar",
        respuestas,
      });
    } catch (e) {
      aplicar = { ok: false, error: `reintento fallo: ${e.message}` };
    }
  }

  if (!aplicar.ok) {
    log(`Aplicar fallo definitivo: ${aplicar.error || "?"}`, "error");
    log(`Mostrando ${respuestas.length} respuestas para copia manual.`, "info");
    mostrarRespuestasCuradas(campos, respuestas);
    return;
  }

  const a = aplicar.aplicados || {};
  const total = Object.values(a).reduce((s, v) => s + v, 0);
  log(`OK: ${total} campos rellenados`, "ok");
  const detalles = Object.entries(a)
    .filter(([_, v]) => v > 0)
    .map(([k, v]) => `${k}:${v}`)
    .join("  ");
  if (detalles) log(`  ${detalles}`, "info");

  // Caso especial: el server devolvio respuestas pero ninguna se aplico
  // (p.ej. campos no editables). Igual mostramos las respuestas IA para
  // que el trabajo curado no se pierda.
  if (total === 0 && respuestas.length > 0) {
    log("Ningun campo se aplico al DOM. Mostrando respuestas para copia manual.", "info");
    mostrarRespuestasCuradas(campos, respuestas);
  }
}

// ──────────────────────────────────────────────────────────────────
// IMPORTAR PERFIL DESDE PDF (drag and drop o file picker)
// ──────────────────────────────────────────────────────────────────
function abrirRevision() {
  const url = chrome.runtime.getURL("revisar.html");
  chrome.tabs.create({ url });
  // En side panel window.close() no aplica; el panel sigue abierto, lo cual
  // ahora es deseado.
}

async function subirPdf(file) {
  if (!file) return;
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    log(`Archivo ignorado: no es PDF (${file.type || "?"})`, "error");
    return;
  }

  log(`Subiendo "${file.name}" (${(file.size / 1024).toFixed(1)} KB)...`, "info");
  log("No cierres el popup mientras procesa.", "info");
  dropZone.classList.add("procesando");

  try {
    const form = new FormData();
    form.append("pdf", file, file.name);
    const r = await fetch(`${SERVER_URL}/proponer_perfil`, {
      method: "POST",
      body: form,
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => "");
      throw new Error(`HTTP ${r.status}: ${txt.slice(0, 200)}`);
    }
    const data = await r.json();
    const detectados = (data.campos_detectados || []).length;
    log(`OK: ${detectados} campos detectados. Abriendo revision...`, "ok");
    abrirRevision();
  } catch (e) {
    log(`Error subiendo PDF: ${e.message}`, "error");
    dropZone.classList.remove("procesando");
  }
}

// Drag & drop sobre la zona
["dragenter", "dragover"].forEach((evt) => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add("dragover");
  });
});

["dragleave", "drop"].forEach((evt) => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove("dragover");
  });
});

dropZone.addEventListener("drop", (e) => {
  const file = e.dataTransfer?.files?.[0];
  if (file) subirPdf(file);
});

// Click en cualquier parte de la zona (incluyendo el boton) abre el file picker.
dropZone.addEventListener("click", () => inputPdf.click());

inputPdf.addEventListener("change", (e) => {
  const file = e.target.files?.[0];
  if (file) subirPdf(file);
  e.target.value = ""; // permite re-subir el mismo archivo si fue rechazado
});

btnAbrirRevision.addEventListener("click", abrirRevision);

$("#btn-editar-perfil").addEventListener("click", () => {
  const url = chrome.runtime.getURL("editar_perfil.html");
  chrome.tabs.create({ url });
});

// ──────────────────────────────────────────────────────────────────
// PANEL DE RESPUESTAS CURADAS (cuando el aplicar al DOM fallo)
// ──────────────────────────────────────────────────────────────────
const panelCuradas = $("#respuestas-curadas");
const listaCuradas = $("#respuestas-lista");
const btnCerrarCuradas = $("#btn-cerrar-curadas");

function ocultarRespuestasCuradas() {
  panelCuradas.classList.add("hidden");
  listaCuradas.innerHTML = "";
}

function mostrarRespuestasCuradas(campos, respuestas) {
  listaCuradas.innerHTML = "";
  const labelPorId = new Map(campos.map((c) => [c.id, c.label || c.id]));
  for (const r of respuestas) {
    if (!r.valor) continue;
    if (r.tipo === "checkbox") continue; // checkboxes no se "copian" a mano
    const item = document.createElement("div");
    item.className = "respuesta-item";

    const lbl = document.createElement("div");
    lbl.className = "respuesta-label";
    lbl.textContent = labelPorId.get(r.id) || r.id;
    item.appendChild(lbl);

    const val = document.createElement("div");
    val.className = "respuesta-valor";
    val.textContent = r.valor;
    item.appendChild(val);

    listaCuradas.appendChild(item);
  }
  if (!listaCuradas.children.length) {
    const vacio = document.createElement("div");
    vacio.className = "muted";
    vacio.style.fontSize = "11px";
    vacio.textContent = "(no hay respuestas de texto que copiar)";
    listaCuradas.appendChild(vacio);
  }
  panelCuradas.classList.remove("hidden");
}

btnCerrarCuradas.addEventListener("click", ocultarRespuestasCuradas);

// ──────────────────────────────────────────────────────────────────
// CONFIGURACION DE API KEYS
// ──────────────────────────────────────────────────────────────────
function mostrarConfigKeys({ forzar = false } = {}) {
  panelConfigKeys.classList.remove("hidden");
  if (forzar) {
    estadoConfigEl.textContent = "";
    estadoConfigEl.className = "config-keys-estado";
  }
  // Inhabilita acciones hasta que haya keys
  for (const b of botonesAccion) b.disabled = true;
}

function ocultarConfigKeys() {
  panelConfigKeys.classList.add("hidden");
  for (const b of botonesAccion) b.disabled = false;
}

function setEstadoConfig(msg, tipo = "") {
  estadoConfigEl.textContent = msg || "";
  estadoConfigEl.className = "config-keys-estado" + (tipo ? ` ${tipo}` : "");
}

async function cargarEstadoKeys() {
  try {
    const r = await fetch(`${SERVER_URL}/estado_keys`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const algunaConfig = data.gemini_configurado || data.groq_configurado;
    // Recordar en chrome.storage solo para UX (no es la fuente de verdad)
    chrome.storage.local.set({ keys_configuradas: algunaConfig });
    if (!algunaConfig) {
      log("No hay API keys configuradas. Configura al menos una.", "info");
      mostrarConfigKeys();
      setEstadoConfig("Pega tu key de Gemini o Groq y guarda.", "");
    } else if (!data.alguno_disponible) {
      // Hay key guardada pero el cliente no arranco (key invalida posiblemente)
      log("Las keys guardadas no funcionan. Revisa que sean validas.", "error");
      mostrarConfigKeys();
      setEstadoConfig("Las keys guardadas no funcionan. Revisalas.", "error");
    } else {
      ocultarConfigKeys();
    }
    return data;
  } catch (e) {
    log(`No pude consultar estado de keys: ${e.message}`, "error");
    return null;
  }
}

async function guardarKeys() {
  const gemini = inputGeminiKey.value.trim();
  const groq = inputGroqKey.value.trim();
  if (!gemini && !groq) {
    setEstadoConfig("Pega al menos una key.", "error");
    return;
  }

  btnGuardarKeys.disabled = true;
  setEstadoConfig("Guardando...", "");
  try {
    const r = await fetch(`${SERVER_URL}/configurar_keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        gemini_api_key: gemini,
        groq_api_key: groq,
      }),
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => "");
      throw new Error(`HTTP ${r.status}: ${txt.slice(0, 200)}`);
    }
    const data = await r.json();
    if (data.alguno_disponible) {
      setEstadoConfig("OK. Listo para usar.", "ok");
      log("API keys configuradas correctamente.", "ok");
      // Limpiamos los inputs por seguridad visual
      inputGeminiKey.value = "";
      inputGroqKey.value = "";
      chrome.storage.local.set({ keys_configuradas: true });
      setTimeout(ocultarConfigKeys, 800);
    } else {
      setEstadoConfig("Guardadas, pero ningun cliente arranco. Revisa las keys.", "error");
    }
  } catch (e) {
    setEstadoConfig(`Error: ${e.message}`, "error");
  } finally {
    btnGuardarKeys.disabled = false;
  }
}

btnGuardarKeys.addEventListener("click", guardarKeys);
btnConfigKeys.addEventListener("click", () => mostrarConfigKeys({ forzar: true }));
btnCerrarConfig.addEventListener("click", ocultarConfigKeys);
// Enter en cualquiera de los inputs envia
for (const inp of [inputGeminiKey, inputGroqKey]) {
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") guardarKeys();
  });
}

// ──────────────────────────────────────────────────────────────────
// EVENTOS
// ──────────────────────────────────────────────────────────────────
btnAnalizar.addEventListener("click", () =>
  conCargando(btnAnalizar, "Analizando...", accionAnalizar).catch((e) => log(String(e), "error"))
);
btnRellenar.addEventListener("click", () =>
  conCargando(btnRellenar, "Rellenando...", () => accionRellenar(false)).catch((e) => log(String(e), "error"))
);
btnForzar.addEventListener("click", () =>
  conCargando(btnForzar, "Re-llenando...", () => accionRellenar(true)).catch((e) => log(String(e), "error"))
);

$("#btn-reload-ext").addEventListener("click", () => {
  log("Recargando extension...", "info");
  setTimeout(() => chrome.runtime.reload(), 200);
});

// ──────────────────────────────────────────────────────────────────
// ATAJOS DE TECLADO (vienen desde background.js)
// ──────────────────────────────────────────────────────────────────
function dispararAccion(accion) {
  if (accion === "analizar") {
    btnAnalizar.click();
  } else if (accion === "rellenar") {
    btnRellenar.click();
  } else if (accion === "forzar") {
    btnForzar.click();
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.tipo === "ejecutar_accion" && msg.accion) {
    dispararAccion(msg.accion);
  }
});

async function consumirAccionPendiente() {
  try {
    const { accion_pendiente, accion_ts } = await chrome.storage.session.get([
      "accion_pendiente",
      "accion_ts",
    ]);
    if (!accion_pendiente) return;
    // Si el buffer es muy viejo (>5s) lo ignoramos para no disparar acciones
    // al abrir manualmente el panel mucho despues.
    if (accion_ts && Date.now() - accion_ts > 5000) {
      await chrome.storage.session.remove(["accion_pendiente", "accion_ts"]);
      return;
    }
    await chrome.storage.session.remove(["accion_pendiente", "accion_ts"]);
    dispararAccion(accion_pendiente);
  } catch (e) {
    // storage.session puede no estar disponible en algunos contextos
  }
}

// Init
(async () => {
  log("Izipega listo.", "info");
  const ok = await pingServer();
  if (!ok) {
    log("Servidor no responde en localhost:8765.", "error");
    log("Lanza el servidor: doble-click a lanzar_servidor.bat", "info");
    return;
  }
  await cargarEstadoKeys();
  await consumirAccionPendiente();
})();
