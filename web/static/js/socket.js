// socket.js — WebSocket / Socket.IO setup and global event handlers
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 1. WebSocket / Socket.IO setup
// ─────────────────────────────────────────────────────────────────

// Connect to the Socket.IO server running on the same host/port as the page.
// Socket.IO handles reconnection automatically.
const socket = io();

/**
 * Update the header status indicator.
 * Called from socket events AND after applyTranslations() so language changes
 * never reset the text back to "connecting…".
 * @param {"connected"|"reconnecting"|"disconnected"|"connecting"} state
 */
function _applyWsStatus(state) {
  const el = document.getElementById("ws-status");
  if (!el) return;
  switch (state) {
    case "connected":
      el.textContent = "⬤ " + i18n("common.connected");
      el.style.color = "#15803d";
      break;
    case "reconnecting":
      el.textContent = "⬤ " + i18n("common.reconnecting");
      el.style.color = "#b45309";
      break;
    case "disconnected":
      el.textContent = "⬤ " + i18n("common.disconnected");
      el.style.color = "#dc2626";
      break;
    default: // "connecting"
      el.textContent = "⬤ " + i18n("common.connecting");
      el.style.color = "#aaa";
  }
}

socket.on("connect", () => {
  _applyWsStatus("connected");
  // If a restart was triggered by an update, reload the page now that the
  // new server is accepting connections — don't just hide the overlay.
  if (_updInstalling) {
    location.reload();
    return;
  }
  document.getElementById("offline-overlay").classList.remove("visible");
});

socket.on("disconnect", () => {
  _applyWsStatus("disconnected");
  // Don't overwrite the update overlay (already visible with custom text).
  if (!_updInstalling) {
    document.getElementById("offline-overlay").classList.add("visible");
  }
});

// Show "reconnecting…" in the status bar while Socket.IO is attempting
// to re-establish the connection after a drop.
socket.io.on("reconnect_attempt", () => { _applyWsStatus("reconnecting"); });
socket.io.on("reconnect",         () => { /* "connect" event fires immediately after */ });

// Server pushes this when a background update download has finished.
socket.on("update_ready", data => { _onUpdateReady(data); });

// "log" events come from server._log() calls in server.py.
// We route them to the correct log box based on the "room" field.
socket.on("log", data => {
  const boxId = {
    cfind:    "log-cfind",
    cstore:   "log-cstore",
    dmwl:     "log-dmwl",
    commit:   "log-commit",
    iocm:     "log-iocm",
    hl7_send: "log-hl7-send",
    hl7_recv: "log-hl7-recv",
    scp:      "log-scp",
  }[data.room];
  if (boxId) appendLog(boxId, data.ts, data.message, data.level);
});

// "hl7_message" events fire when an HL7 message arrives at the listener.
socket.on("hl7_message", data => {
  const container = document.getElementById("hl7-recv-messages");
  const count = container.children.length + 1;

  // Build a nicely formatted block for this message
  const block = document.createElement("div");
  block.style.cssText = "border:1px solid #e0e0e0; border-radius:3px; background:#fff; padding:10px; font-size:12px";
  block.innerHTML =
    `<div style="color:#888; margin-bottom:4px; font-size:11px">[${data.ts}] From ${data.from}</div>` +
    `<pre style="font-family:Consolas; white-space:pre-wrap; color:#1a1a1a; margin:0">${escapeHtml(data.message)}</pre>`;

  // Add Inspect button — triggers the inline HL7 inspector for this message
  const msgText = data.message;
  const inspBtn = document.createElement("button");
  inspBtn.className = "btn";
  inspBtn.style.cssText = "margin-top:6px; font-size:11px; padding:2px 8px";
  inspBtn.textContent = "Inspect";
  inspBtn.setAttribute("data-i18n", "hl7.inspect_btn");
  inspBtn.onclick = () => {
    hl7ParseAndInspect(null, msgText);
    document.getElementById("hl7-recv-inspector").scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  block.appendChild(inspBtn);

  container.appendChild(block);
  container.scrollTop = container.scrollHeight;

  document.getElementById("hl7-recv-count").textContent = `${count} message(s)`;

  // Persist to inbound history
  _hl7InHistorySave({ ts: data.ts, from: data.from, message: data.message });

  // Check if this is an order message relevant to the ORU IAN workflow
  const _msg = data.message || "";
  if (/\bORM\b|\bOMG\b|\bOML\b/.test(_msg)) {
    _dzOruIanOrm = _msg;
    const fillBtn  = document.getElementById("dz-oruian-fill-btn");
    const ormPre   = document.getElementById("dz-oruian-orm-text");
    const statusEl = document.getElementById("dz-oruian-status");
    if (fillBtn)  fillBtn.style.display  = "";
    if (ormPre)  { ormPre.textContent = _msg.replace(/\r/g, "\n"); ormPre.style.display = ""; }
    const ormInspectRow = document.getElementById("dz-oruian-orm-inspect-row");
    if (ormInspectRow) ormInspectRow.style.display = "";
    if (statusEl){ statusEl.textContent = i18n("dicomize.oruian_orm_received"); statusEl.style.color = "var(--ok, green)"; }
    appendLog("log-dicomize", now(), i18n("dicomize.oruian_orm_received"), "ok");
  }
});

// Server pushes SCP/HL7 status on first connect so buttons show correctly.
socket.on("scp_status", data => updateSCPButton(data.running));
socket.on("hl7_status", data => updateHL7Button(data.running));

