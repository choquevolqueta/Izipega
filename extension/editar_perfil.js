// editar_perfil.js — Vista para editar manualmente perfil.json

const SERVER_URL = "http://localhost:8765";
const $ = (s) => document.querySelector(s);

const statusPill = $("#status-pill");
const footerMsg = $("#footer-msg");
const btnGuardar = $("#btn-guardar");
const btnCancelar = $("#btn-cancelar");

const f = {
  nombre: $("#f-nombre"),
  edad: $("#f-edad"),
  ciudad: $("#f-ciudad"),
  comuna: $("#f-comuna"),
  telefono: $("#f-telefono"),
  email: $("#f-email"),
  nacionalidad: $("#f-nacionalidad"),
  linkedin: $("#f-linkedin"),
  portfolio: $("#f-portfolio"),
  behance: $("#f-behance"),
  perfilProf: $("#f-perfil-prof"),
  motivacion: $("#f-motivacion"),
  disponibilidad: $("#f-disponibilidad"),
  sueldo: $("#f-sueldo"),
  modalidad: $("#f-modalidad"),
  habilidades: $("#f-habilidades"),
  herramientas: $("#f-herramientas"),
  fortalezas: $("#f-fortalezas"),
  idiomas: $("#f-idiomas"),
  respuestasExtra: $("#f-respuestas-extra"),
};

function setStatus(texto, tipo = "info") {
  statusPill.textContent = texto;
  statusPill.className = `pill pill-${tipo}`;
}

function setFooter(msg) {
  footerMsg.textContent = msg || "";
}

// Listas: array <-> textarea "uno por linea"
function listaAtexto(arr) {
  if (!Array.isArray(arr)) return "";
  return arr.filter((x) => x !== null && x !== undefined).map(String).join("\n");
}

function textoAlista(t) {
  return (t || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

// Idiomas: array de {idioma, nivel} <-> "Idioma: Nivel" por linea
function idiomasAtexto(arr) {
  if (!Array.isArray(arr)) return "";
  return arr
    .map((it) => {
      if (!it) return "";
      return `${it.idioma || ""}: ${it.nivel || ""}`;
    })
    .filter((s) => s.trim() && s.trim() !== ":")
    .join("\n");
}

function textoAidiomas(t) {
  const out = [];
  for (const linea of (t || "").split("\n")) {
    const s = linea.trim();
    if (!s) continue;
    const idx = s.indexOf(":");
    if (idx < 0) {
      out.push({ idioma: s, nivel: "" });
    } else {
      out.push({
        idioma: s.slice(0, idx).trim(),
        nivel: s.slice(idx + 1).trim(),
      });
    }
  }
  return out;
}

// Respuestas extras: bloques "pregunta / respuesta indentada" <-> dict {clave: valor}.
// Parser permisivo: si la sintaxis esta rara, igual extrae lo que puede.
function slugClave(pregunta) {
  return (pregunta || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[¿?¡!.,;:()"']/g, "")
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_");
}

function preguntaHumana(clave) {
  if (!clave) return "";
  // Reemplaza guiones bajos por espacios y capitaliza la primera letra.
  const s = clave.replace(/_/g, " ").trim();
  return (s.charAt(0).toUpperCase() + s.slice(1)) + "?";
}

function extrasAtexto(obj) {
  if (!obj || typeof obj !== "object") return "";
  const bloques = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) continue;
    const valor = String(v).trim();
    if (!valor) continue;
    bloques.push(`${preguntaHumana(k)}\n  ${valor}`);
  }
  return bloques.join("\n\n");
}

function textoAextras(texto) {
  const out = {};
  const lineas = (texto || "").split("\n");
  let claveActual = null;
  let respuesta = [];
  const commit = () => {
    if (claveActual) {
      const v = respuesta.join(" ").replace(/\s+/g, " ").trim();
      if (v) out[claveActual] = v;
    }
    claveActual = null;
    respuesta = [];
  };
  for (const linea of lineas) {
    if (!linea.trim()) {
      commit();
      continue;
    }
    if (/^\s/.test(linea)) {
      // Linea indentada = parte de la respuesta
      respuesta.push(linea.trim());
    } else {
      // Linea sin indentar = nueva pregunta
      commit();
      const slug = slugClave(linea);
      if (slug) claveActual = slug;
    }
  }
  commit();
  return out;
}

// ─── CARGAR ─────────────────────────────────────────────────────
async function cargar() {
  setStatus("cargando...", "info");
  try {
    const r = await fetch(`${SERVER_URL}/perfil_actual`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const p = await r.json();
    pintar(p);
    setStatus("listo", "ok");
  } catch (e) {
    setStatus("error", "error");
    setFooter(`No pude cargar el perfil: ${e.message}. Servidor en ${SERVER_URL}?`);
  }
}

function pintar(p) {
  f.nombre.value = p.nombre || "";
  f.edad.value = p.edad ?? "";
  f.ciudad.value = p.ciudad || "";
  f.comuna.value = p.comuna || "";
  f.telefono.value = p.telefono || "";
  f.email.value = p.email || "";
  f.nacionalidad.value = p.nacionalidad || "";

  const redes = p.redes || {};
  f.linkedin.value = redes.linkedin || "";
  f.portfolio.value = redes.portafolio_web || "";
  f.behance.value = redes.behance || "";

  f.perfilProf.value = p.perfil_profesional || "";
  f.motivacion.value = p.motivacion || "";
  f.disponibilidad.value = p.disponibilidad || "";
  f.sueldo.value = p.expectativa_sueldo || "";
  f.modalidad.value = p.modalidad_preferida || "";

  f.habilidades.value = listaAtexto(p.habilidades);
  f.herramientas.value = listaAtexto(p.herramientas);
  f.fortalezas.value = listaAtexto(p.fortalezas);
  f.idiomas.value = idiomasAtexto(p.idiomas);

  f.respuestasExtra.value = extrasAtexto(p.respuestas_extra || {});

  // Guardamos el perfil original para preservar campos no editados explicitamente
  // (experiencia y estudios se preservan tal cual desde aqui).
  window._perfilOriginal = p;
}

// ─── GUARDAR ────────────────────────────────────────────────────
async function guardar() {
  const original = window._perfilOriginal || {};
  const edadNum = f.edad.value.trim() ? Number(f.edad.value) : null;

  const perfil = {
    ...original,
    nombre: f.nombre.value.trim(),
    edad: Number.isFinite(edadNum) ? edadNum : null,
    ciudad: f.ciudad.value.trim(),
    comuna: f.comuna.value.trim(),
    telefono: f.telefono.value.trim(),
    email: f.email.value.trim(),
    nacionalidad: f.nacionalidad.value.trim(),
    redes: {
      linkedin: f.linkedin.value.trim(),
      portafolio_web: f.portfolio.value.trim(),
      behance: f.behance.value.trim(),
    },
    perfil_profesional: f.perfilProf.value.trim(),
    motivacion: f.motivacion.value.trim(),
    disponibilidad: f.disponibilidad.value.trim(),
    expectativa_sueldo: f.sueldo.value.trim(),
    modalidad_preferida: f.modalidad.value.trim(),
    habilidades: textoAlista(f.habilidades.value),
    herramientas: textoAlista(f.herramientas.value),
    fortalezas: textoAlista(f.fortalezas.value),
    idiomas: textoAidiomas(f.idiomas.value),
    // experiencia y estudios se preservan tal cual desde ...original
    respuestas_extra: textoAextras(f.respuestasExtra.value),
  };

  btnGuardar.disabled = true;
  setStatus("guardando...", "info");
  setFooter("");
  try {
    const r = await fetch(`${SERVER_URL}/aplicar_perfil`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ perfil }),
    });
    if (!r.ok) {
      const t = await r.text().catch(() => "");
      throw new Error(`HTTP ${r.status}: ${t.slice(0, 200)}`);
    }
    const data = await r.json();
    setStatus("guardado", "ok");
    setFooter(`OK. Backup: ${data.backup || "(?)"}`);
    window._perfilOriginal = perfil;
  } catch (e) {
    setStatus("error", "error");
    setFooter(`No pude guardar: ${e.message}`);
  } finally {
    btnGuardar.disabled = false;
  }
}

btnGuardar.addEventListener("click", guardar);
btnCancelar.addEventListener("click", () => window.close());

// Atajo Ctrl+S para guardar
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    guardar();
  }
});

cargar();
