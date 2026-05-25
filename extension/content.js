// content.js — Izipega
// Corre en cualquier sitio (matches: <all_urls>). Detecta campos del
// formulario actual, los manda al servidor local y aplica respuestas al DOM.
// Tambien sabe "leer el contexto" de la pagina (titulo + descripcion) para
// que el servidor pre-analice si estas en una oferta de trabajo o similar.

// Guard: si este content script se inyecta varias veces (por hot-reload o
// porque el popup lo asegura on-demand), no registramos listeners duplicados.
if (window.__escritor_magico_loaded) {
  // Ya inicializado: salir sin volver a registrar nada.
} else {
  window.__escritor_magico_loaded = true;

let _camposRef = {}; // id -> { tipo, elemento(s), opciones? }

// ──────────────────────────────────────────────────────────────────
// UTILIDADES
// ──────────────────────────────────────────────────────────────────
function isVisible(el) {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  if (parseFloat(style.opacity) === 0) return false;
  return true;
}

function textoLimpio(s) {
  return (s || "").replace(/\s+/g, " ").trim();
}

// Texto descriptivo "buscando arriba": <label> hermano previo, <div>/<span>/<p>
// hermano previo, o el primer texto descriptivo del padre / abuelo que no sea
// el propio input. Heuristica para sitios (chiletrabajos, formularios HTML
// rusticos) donde no hay <label for=...> ni fieldset.
function _labelPorContexto(el) {
  const MAX_LEN = 120;
  const esTextoUtil = (t) => {
    const s = textoLimpio(t || "");
    if (!s) return "";
    if (s.length < 2 || s.length > MAX_LEN) return "";
    // Descarta strings que claramente no son labels: numeros sueltos, "*", ":", "$", etc.
    if (/^[\s\d:$*().,/-]+$/.test(s)) return "";
    return s;
  };

  // 1. Hermanos PREVIOS inmediatos: typical chiletrabajos pattern
  //    <label>Pretensiones de renta</label> <input>
  //    o <div>Pretensiones de renta</div><input>
  let prev = el.previousElementSibling;
  let saltos = 0;
  while (prev && saltos < 3) {
    const tag = prev.tagName.toLowerCase();
    if (tag === "label" || tag === "div" || tag === "span" || tag === "p" || tag === "strong" || tag === "b") {
      const t = esTextoUtil(prev.innerText);
      if (t) return t;
    }
    prev = prev.previousElementSibling;
    saltos++;
  }

  // 2. Subir 1-3 niveles y buscar el primer label/div/span hermano del input
  let nodo = el.parentElement;
  let nivel = 0;
  while (nodo && nivel < 3) {
    // a) Buscar un <label> dentro del contenedor que no envuelva al input
    const labs = nodo.querySelectorAll(":scope > label, :scope > div > label");
    for (const l of labs) {
      if (!l.contains(el)) {
        const t = esTextoUtil(l.innerText);
        if (t) return t;
      }
    }
    // b) Primer hijo con texto que no sea el input
    for (const child of nodo.children) {
      if (child === el || child.contains(el)) continue;
      const tag = child.tagName.toLowerCase();
      if (["label", "legend", "strong", "b", "h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "div"].includes(tag)) {
        const t = esTextoUtil(child.innerText);
        if (t) return t;
      }
    }
    nodo = nodo.parentElement;
    nivel++;
  }
  return "";
}

// labelPrincipal: devuelve el mejor texto descriptivo del campo (el "label visible").
function labelPrincipal(el) {
  try {
    const id = el.id;
    if (id) {
      const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (lab && lab.innerText.trim()) return lab.innerText.trim();
    }
    const fs = el.closest("fieldset, [class*=Question], [class*=question], [class*=field], [class*=Field]");
    if (fs) {
      const q = fs.querySelector("legend, label, [class*=question], [class*=label]");
      if (q && q.innerText.trim()) return q.innerText.trim();
    }
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const ref = document.getElementById(labelledBy);
      if (ref && ref.innerText.trim()) return ref.innerText.trim();
    }
    // Aria-label tiene mayor prioridad que el placeholder
    const aria = (el.getAttribute("aria-label") || "").trim();
    if (aria) return aria;

    // ── Nuevo paso: heuristica de contexto (hermanos / padres) ─────
    // Esto cubre el caso chiletrabajos donde el label visible es un <div>
    // hermano del input, sin <label for=...> ni aria.
    const porContexto = _labelPorContexto(el);
    if (porContexto) return porContexto;

    // Fallback final: placeholder / title / name (menos confiables)
    return (
      el.placeholder ||
      el.title ||
      el.name ||
      ""
    ).trim();
  } catch (e) {
    return "";
  }
}

// labelDe (compat): mantiene la firma string para callers que solo necesitan
// un texto. labelEnriquecido() es el que da el detalle estructurado.
function labelDe(el) {
  return labelPrincipal(el);
}

// labelEnriquecido: devuelve TODOS los atributos del campo y su entorno
// inmediato. La IA usa esto para identificar inequivocamente que se pregunta
// y no caer en alucinaciones por un label ambiguo.
function labelEnriquecido(el) {
  const datos = {
    label: labelPrincipal(el),
    placeholder: (el.placeholder || "").trim(),
    name: (el.name || "").trim(),
    id: (el.id || "").trim(),
    aria_label: (el.getAttribute("aria-label") || "").trim(),
    aria_describedby_texto: "",
    legend: "",
    hermanos: "",
    tipo_input: (el.type || "").trim(),
  };

  try {
    const desc = el.getAttribute("aria-describedby");
    if (desc) {
      const ref = document.getElementById(desc);
      if (ref) datos.aria_describedby_texto = textoLimpio(ref.innerText).slice(0, 200);
    }
  } catch (_) {}

  try {
    const fs = el.closest("fieldset");
    if (fs) {
      const lg = fs.querySelector("legend");
      if (lg) datos.legend = textoLimpio(lg.innerText).slice(0, 200);
    }
  } catch (_) {}

  // Texto de hermanos cercanos (a veces el "label visual" no esta en un <label>)
  try {
    const padre = el.parentElement;
    if (padre) {
      const propio = (el.innerText || el.value || "").trim();
      const texto = textoLimpio(padre.innerText || "");
      const limpio = texto.replace(propio, "").trim();
      if (limpio && limpio.length < 400) datos.hermanos = limpio.slice(0, 300);
    }
  } catch (_) {}

  return datos;
}

// Setters compatibles con React/Vue (dispara eventos nativos)
function setInputValue(el, value) {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function setSelectValue(el, value) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value"
  ).set;
  setter.call(el, value);
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

// ──────────────────────────────────────────────────────────────────
// LEER CONTEXTO DE LA PAGINA
// ──────────────────────────────────────────────────────────────────
// Estrategia en capas (cae a la siguiente si la actual no encuentra nada):
// 1. Texto seleccionado por el usuario.
// 2. Modal/dialog/lightbox abierto al frente (cubre overlays sobre listas).
// 3. Selectores especificos por sitio (Indeed, LinkedIn, Computrabajo, etc).
// 4. Selectores genericos (h1/h2 + main/article + meta og:title).
// 5. Fallback duro: <title> y body recortado.

// Devuelve el primer elemento visible con texto utilizable.
function _primerVisibleConTexto(selectores, minLen = 1) {
  for (const sel of selectores) {
    try {
      for (const el of document.querySelectorAll(sel)) {
        if (isVisible(el)) {
          const t = textoLimpio(el.innerText);
          if (t.length >= minLen) return t;
        }
      }
    } catch (_) {
      /* selector invalido, sigue */
    }
  }
  return "";
}

// Devuelve {titulo, descripcion} usando selectores conocidos para el host actual.
function _contextoPorSitio() {
  const host = (location.hostname || "").toLowerCase();
  let titulo = "";
  let descripcion = "";

  if (host.includes("indeed.")) {
    titulo = _primerVisibleConTexto([
      "[data-testid='jobsearch-JobInfoHeader-title']",
      "[data-testid='simpler-jobTitle']",
      "h1.jobsearch-JobInfoHeader-title",
      "h2.jobsearch-JobInfoHeader-title",
      "h1[class*='JobInfoHeader']",
    ]);
    descripcion = _primerVisibleConTexto(
      [
        "#jobDescriptionText",
        "[id*='jobDescription']",
        "[data-testid*='jobDescription']",
        "div.jobsearch-JobComponent-description",
      ],
      80
    );
  } else if (host.includes("linkedin.")) {
    titulo = _primerVisibleConTexto([
      ".job-details-jobs-unified-top-card__job-title",
      ".jobs-unified-top-card__job-title",
      "h1.t-24",
      "h1[class*='job-title']",
    ]);
    descripcion = _primerVisibleConTexto(
      [
        ".jobs-description__content",
        ".jobs-description-content__text",
        "#job-details",
        "article.jobs-description__container",
      ],
      80
    );
  } else if (host.includes("computrabajo.")) {
    titulo = _primerVisibleConTexto([
      "h1.title", "h1.fwB", "h1.it-title", "h1",
    ]);
    descripcion = _primerVisibleConTexto(
      ["#sDesc", ".fs16.mt20", "div.detail_fs.mb40", "section.detailOffer"],
      80
    );
  } else if (host.includes("getonbrd.") || host.includes("getonboard.")) {
    titulo = _primerVisibleConTexto([
      "h1.gb-job-title", "h1.title", "h1",
    ]);
    descripcion = _primerVisibleConTexto(
      [".gb-job-description", "#job_description", "section.job-description"],
      80
    );
  } else if (host.includes("laborum.") || host.includes("trabajando.")) {
    titulo = _primerVisibleConTexto([
      "h1.job-title", "h1.titulo-aviso", "h1",
    ]);
    descripcion = _primerVisibleConTexto(
      [".job-description", ".descripcion-aviso", "section.detalle-aviso"],
      80
    );
  }

  return { titulo, descripcion };
}

// Detecta si hay un modal/dialog/lightbox abierto AL FRENTE. Devuelve el
// elemento o null. Heuristica: busca [role=dialog], [aria-modal], dialog[open],
// y clases comunes (.modal, .lightbox, .ReactModal__Content, etc.). Filtra
// los que no son visibles o son demasiado pequenos (probablemente tooltips).
function _modalAbierto() {
  const candidatos = document.querySelectorAll([
    "[role='dialog']",
    "[aria-modal='true']",
    "dialog[open]",
    ".modal.show", ".modal.in", ".modal.open",
    ".ReactModal__Content",
    "[class*='Modal'][class*='open']",
    "[class*='lightbox']",
    "[class*='Lightbox']",
    "[class*='offer-detail']",
    "[class*='job-detail-modal']",
    "[class*='Drawer'][class*='open']",
  ].join(","));
  let mejor = null;
  let mejorArea = 0;
  for (const el of candidatos) {
    if (!isVisible(el)) continue;
    const r = el.getBoundingClientRect();
    const area = r.width * r.height;
    // Tiene que cubrir al menos el 25% del viewport para considerarlo modal real
    const minArea = window.innerWidth * window.innerHeight * 0.25;
    if (area < minArea) continue;
    if (area > mejorArea) {
      mejor = el;
      mejorArea = area;
    }
  }
  return mejor;
}

function _leerDesdeContenedor(contenedor) {
  // Titulo: primer h1/h2/h3 visible dentro del contenedor
  let titulo = "";
  for (const sel of ["h1", "h2", "h3"]) {
    for (const el of contenedor.querySelectorAll(sel)) {
      if (isVisible(el)) {
        const t = textoLimpio(el.innerText);
        if (t.length >= 3) { titulo = t; break; }
      }
    }
    if (titulo) break;
  }
  // Descripcion: innerText del contenedor (excluyendo el titulo si ya lo capturamos)
  let descripcion = textoLimpio(contenedor.innerText || "");
  if (titulo && descripcion.startsWith(titulo)) {
    descripcion = descripcion.slice(titulo.length).trim();
  }
  if (!titulo) titulo = textoLimpio(document.title);
  descripcion = descripcion.slice(0, 4000);
  return { titulo, descripcion };
}

function leerContexto() {
  // 1. Texto seleccionado por el usuario
  const seleccion = textoLimpio(window.getSelection()?.toString() || "");
  if (seleccion.length > 30) {
    const lineas = seleccion.split(/\n+/).map(textoLimpio).filter(Boolean);
    const titulo = lineas[0] || "";
    const descripcion = lineas.slice(1).join("\n") || seleccion;
    return { titulo, descripcion, fuente: "seleccion" };
  }

  // 2. Modal/dialog/lightbox abierto al frente (cubre el caso de portales
  // de empleo que abren la oferta en un overlay sobre la lista de busqueda)
  const modal = _modalAbierto();
  if (modal) {
    const { titulo, descripcion } = _leerDesdeContenedor(modal);
    if (descripcion && descripcion.length > 50) {
      return { titulo, descripcion, fuente: "modal" };
    }
  }

  // 3. Selectores conocidos por sitio
  const porSitio = _contextoPorSitio();
  if (porSitio.titulo || porSitio.descripcion) {
    let { titulo, descripcion } = porSitio;
    if (!titulo) titulo = textoLimpio(document.title);
    if (!descripcion) {
      descripcion = textoLimpio(document.body?.innerText || "").slice(0, 4000);
    }
    descripcion = descripcion.slice(0, 4000);
    return { titulo, descripcion, fuente: "sitio" };
  }

  // 4. Generico: h1/h2 + main/article + meta tags
  let titulo = _primerVisibleConTexto(["h1", "h2"]);

  // og:title como complemento si el h1/h2 no aparecio o es debil
  if (!titulo) {
    const og = document.querySelector("meta[property='og:title']");
    if (og && og.content) titulo = textoLimpio(og.content);
  }

  let descripcion = _primerVisibleConTexto(
    [
      "main",
      "article",
      "[role='main']",
      "[id*='description']",
      "[id*='Description']",
      "[class*='description']",
      "[class*='Description']",
      "[class*='jobDescription']",
      "[class*='job-description']",
      "[data-testid*='description']",
    ],
    100
  );

  if (!descripcion) {
    const md = document.querySelector(
      "meta[name='description'], meta[property='og:description']"
    );
    if (md && md.content && md.content.length > 60) {
      descripcion = textoLimpio(md.content);
    }
  }

  // 5. Fallback duro
  if (!titulo) titulo = textoLimpio(document.title);
  if (!descripcion) {
    descripcion = textoLimpio(document.body?.innerText || "").slice(0, 4000);
  }
  descripcion = descripcion.slice(0, 4000);

  return { titulo, descripcion, fuente: "auto" };
}

// ──────────────────────────────────────────────────────────────────
// ESCANEAR CAMPOS DEL FORMULARIO ACTUAL
// ──────────────────────────────────────────────────────────────────
function escanearCampos() {
  const campos = [];
  _camposRef = {};
  let counter = 0;

  // RADIOS agrupados por name
  const radiosVistos = new Set();
  document.querySelectorAll("input[type='radio']").forEach((r) => {
    if (!isVisible(r)) return;
    const name = r.name || "";
    if (!name || radiosVistos.has(name)) return;
    radiosVistos.add(name);

    const grupo = Array.from(
      document.querySelectorAll(`input[type='radio'][name="${CSS.escape(name)}"]`)
    ).filter(isVisible);
    if (!grupo.length) return;

    let pregunta = "";
    const fs = grupo[0].closest("fieldset");
    if (fs) {
      const lg = fs.querySelector("legend");
      if (lg && lg.innerText.trim()) pregunta = lg.innerText.trim();
    }
    if (!pregunta) pregunta = labelDe(grupo[0]);
    if (!pregunta) return;

    const opciones = grupo.map((rr) => {
      let texto = "";
      if (rr.id) {
        const l = document.querySelector(`label[for="${CSS.escape(rr.id)}"]`);
        if (l && l.innerText.trim()) texto = l.innerText.trim();
      }
      if (!texto) texto = rr.value || "";
      return texto;
    });
    const opcionesValidas = opciones.filter((t) => t);
    if (!opcionesValidas.length) return;

    const id = `radio_${counter++}_${name}`;
    campos.push({ id, tipo: "radio", label: pregunta, opciones: opcionesValidas });
    _camposRef[id] = { tipo: "radio", elementos: grupo, opciones: opciones };
  });

  // TEXTAREAS (solo vacias)
  document.querySelectorAll("textarea").forEach((ta) => {
    if (!isVisible(ta)) return;
    if ((ta.value || "").trim()) return;
    const meta = labelEnriquecido(ta);
    if (!meta.label && !meta.placeholder && !meta.name) return;
    const id = `textarea_${counter++}`;
    campos.push({ id, tipo: "textarea", label: meta.label || meta.placeholder || meta.name, meta });
    _camposRef[id] = { tipo: "textarea", elemento: ta };
  });

  // INPUTS text/number/tel/email/url (solo vacios)
  document
    .querySelectorAll(
      "input[type='text'], input[type='number'], input[type='tel'], input[type='email'], input[type='url'], input:not([type])"
    )
    .forEach((inp) => {
      if (!isVisible(inp)) return;
      if ((inp.value || "").trim()) return;
      const meta = labelEnriquecido(inp);
      const principal = meta.label || meta.placeholder || meta.name;
      if (!principal || principal.length < 3) return;
      const id = `input_${counter++}`;
      campos.push({ id, tipo: "text", label: principal, meta });
      _camposRef[id] = { tipo: "text", elemento: inp };
    });

  // SELECTS
  document.querySelectorAll("select").forEach((sel) => {
    if (!isVisible(sel)) return;
    const pregunta = labelDe(sel);
    if (!pregunta) return;
    const skipFiller = ["seleccione", "selecciona", "elige", "select"];
    const opciones = Array.from(sel.querySelectorAll("option"))
      .map((op) => ({ val: op.value, txt: (op.innerText || "").trim() }))
      .filter(
        (o) =>
          o.val &&
          o.txt &&
          !skipFiller.some((f) => o.txt.toLowerCase().includes(f))
      )
      .map((o) => o.txt);
    if (!opciones.length) return;
    const id = `select_${counter++}`;
    campos.push({ id, tipo: "select", label: pregunta, opciones });
    _camposRef[id] = { tipo: "select", elemento: sel, opciones };
  });

  // CHECKBOXES (solo no marcados)
  document.querySelectorAll("input[type='checkbox']").forEach((cb) => {
    if (!isVisible(cb) || cb.checked) return;
    const pregunta = labelDe(cb);
    if (!pregunta) return;
    const id = `check_${counter++}`;
    campos.push({ id, tipo: "checkbox", label: pregunta });
    _camposRef[id] = { tipo: "checkbox", elemento: cb };
  });

  return campos;
}

// ──────────────────────────────────────────────────────────────────
// APLICAR RESPUESTAS AL DOM
// ──────────────────────────────────────────────────────────────────
function aplicarRespuestas(respuestas) {
  const aplicados = { text: 0, textarea: 0, radio: 0, select: 0, checkbox: 0 };
  for (const r of respuestas) {
    const ref = _camposRef[r.id];
    if (!ref) continue;
    try {
      if (r.tipo === "text" || r.tipo === "textarea") {
        if (!r.valor) continue;
        setInputValue(ref.elemento, r.valor);
        aplicados[r.tipo]++;
      } else if (r.tipo === "radio") {
        if (!r.valor) continue;
        const grupo = ref.elementos;
        const opciones = ref.opciones;
        let elegidoIdx = -1;
        const v = r.valor.toLowerCase();
        for (let i = 0; i < opciones.length; i++) {
          const o = (opciones[i] || "").toLowerCase();
          if (!o) continue;
          if (o === v || o.includes(v) || v.includes(o)) {
            elegidoIdx = i;
            break;
          }
        }
        if (elegidoIdx < 0) elegidoIdx = 0;
        grupo[elegidoIdx].click();
        aplicados.radio++;
      } else if (r.tipo === "select") {
        const opciones = ref.opciones;
        let elegida = opciones[0];
        const v = (r.valor || "").toLowerCase();
        for (const o of opciones) {
          const ol = o.toLowerCase();
          if (ol === v || ol.includes(v) || v.includes(ol)) {
            elegida = o;
            break;
          }
        }
        const opEl = Array.from(ref.elemento.querySelectorAll("option")).find(
          (op) => (op.innerText || "").trim() === elegida
        );
        if (opEl) {
          setSelectValue(ref.elemento, opEl.value);
          aplicados.select++;
        }
      } else if (r.tipo === "checkbox") {
        if (r.valor === "true" && !ref.elemento.checked) {
          ref.elemento.click();
          aplicados.checkbox++;
        }
      }
    } catch (e) {
      console.warn("[escritor-magico] aplicar fallo en", r.id, e);
    }
  }
  return aplicados;
}

function limpiarCampos() {
  document.querySelectorAll("textarea").forEach((ta) => {
    if (isVisible(ta)) setInputValue(ta, "");
  });
  document
    .querySelectorAll(
      "input[type='text'], input[type='number'], input[type='tel'], input[type='email'], input[type='url']"
    )
    .forEach((inp) => {
      if (isVisible(inp)) setInputValue(inp, "");
    });
}

// ──────────────────────────────────────────────────────────────────
// HANDLERS DE MENSAJES (desde popup)
// ──────────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  try {
    if (msg.action === "leer_contexto") {
      sendResponse({ ok: true, ...leerContexto() });
      return false;
    }
    if (msg.action === "escanear") {
      const campos = escanearCampos();
      sendResponse({ ok: true, campos });
      return false;
    }
    if (msg.action === "aplicar") {
      const aplicados = aplicarRespuestas(msg.respuestas || []);
      sendResponse({ ok: true, aplicados });
      return false;
    }
    if (msg.action === "limpiar") {
      limpiarCampos();
      sendResponse({ ok: true });
      return false;
    }
    if (msg.action === "scroll_into_view") {
      const ref = _camposRef[msg.id];
      const el = ref?.elemento || (ref?.elementos && ref.elementos[0]);
      if (el && typeof el.scrollIntoView === "function") {
        try {
          el.scrollIntoView({ behavior: "instant", block: "center" });
          sendResponse({ ok: true });
        } catch (e) {
          sendResponse({ ok: false, error: String(e) });
        }
      } else {
        sendResponse({ ok: false, error: "campo no encontrado" });
      }
      return false;
    }
    if (msg.action === "ping") {
      sendResponse({ ok: true, pong: true });
      return false;
    }
  } catch (e) {
    sendResponse({ ok: false, error: String(e) });
    return false;
  }
});

} // fin del guard __escritor_magico_loaded
