// echo.js — C-ECHO
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 5. C-ECHO
// ─────────────────────────────────────────────────────────────────

async function doEcho(prefix) {
  const ae = getAE(prefix);
  if (!ae) return;
  // Sync health dot to current AE fields before pinging
  const dot = document.getElementById(prefix + "-ae-dot");
  if (dot) { dot.dataset.aeKey = _aeKey(ae); }
  _setAEHealth(ae, "busy");
  appendLog(`log-${prefix}`, now(), `C-ECHO → ${ae.ae_title}@${ae.host}:${ae.port}`);
  try {
    const res  = await fetch("/api/dicom/echo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ae),
    });
    const data = await res.json();
    _setAEHealth(ae, data.ok ? "ok" : "err");
    appendLog(`log-${prefix}`, now(), data.message, data.ok ? "ok" : "err");
  } catch (e) {
    _setAEHealth(ae, "err");
    appendLog(`log-${prefix}`, now(), "Error: " + e, "err");
  }
}

