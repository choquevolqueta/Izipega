// background.js — Service worker.
// - Hace que el icono abra el side panel (en vez de un popup).
// - Recibe los atajos de teclado de chrome.commands y los reenvia al panel.

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((e) => console.warn("[escritor-magico] setPanelBehavior fallo:", e));
});

// Tambien al arrancar el service worker (por si se reinstala/recarga).
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn("[escritor-magico] setPanelBehavior fallo:", e));

// ──────────────────────────────────────────────────────────────────
// ATAJOS DE TECLADO
// ──────────────────────────────────────────────────────────────────
// Mapa command -> accion que el panel reconocera.
const COMMAND_A_ACCION = {
  analizar_contexto: "analizar",
  rellenar_formulario: "rellenar",
  forzar_rellenado: "forzar",
};

async function abrirPanelEnVentanaActiva() {
  try {
    const [win] = await chrome.windows.getAll({ windowTypes: ["normal"] });
    const windowId = win?.id;
    if (windowId !== undefined) {
      await chrome.sidePanel.open({ windowId });
    }
  } catch (e) {
    // sidePanel.open requiere gesto de usuario en algunas versiones; el atajo
    // cuenta como gesto, pero si falla seguimos: el mensaje queda en storage
    // y se procesa cuando el usuario lo abra.
    console.warn("[escritor-magico] sidePanel.open fallo:", e);
  }
}

chrome.commands.onCommand.addListener(async (command) => {
  const accion = COMMAND_A_ACCION[command];
  if (!accion) return; // _execute_action lo maneja Chrome solo

  // Buffer en storage: si el panel todavia no esta cargado cuando reciba el
  // mensaje, lo leera al iniciarse.
  await chrome.storage.session.set({ accion_pendiente: accion, accion_ts: Date.now() });

  await abrirPanelEnVentanaActiva();

  // Tambien notificamos por runtime para el caso en que ya este abierto.
  // (sendMessage rechaza si no hay listeners; lo silenciamos.)
  chrome.runtime.sendMessage({ tipo: "ejecutar_accion", accion }).catch(() => {});
});
