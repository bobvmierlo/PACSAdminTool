// scp-stats.js — SCP statistics panel
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// SCP Statistics
// ─────────────────────────────────────────────────────────────────

async function loadSCPStats() {
  const info = document.getElementById("scp-stats-info");
  const modEl = document.getElementById("scp-stats-modality");
  const dateEl = document.getElementById("scp-stats-date");
  info.textContent = "Loading…";
  modEl.innerHTML = "";
  dateEl.innerHTML = "";
  try {
    const res  = await fetch("/api/scp/stats");
    const data = await res.json();
    if (!data.ok) { info.textContent = "Error: " + data.error; return; }

    const kb = data.total_bytes < 1048576
      ? (data.total_bytes / 1024).toFixed(1) + " KB"
      : (data.total_bytes / 1048576).toFixed(1) + " MB";
    info.textContent = `${data.total} file(s)  ·  ${kb} total`
      + (data.sampled < data.total ? `  (showing stats for ${data.sampled} most-recent)` : "");

    // Modality breakdown
    const mods = Object.entries(data.by_modality || {});
    if (mods.length) {
      modEl.innerHTML = `<div style="font-weight:600;font-size:12px;color:#888;margin-bottom:4px">By Modality</div>`
        + mods.map(([m, n]) =>
            `<div style="display:flex;justify-content:space-between;font-size:12px;padding:1px 0">
               <span>${m}</span><span style="color:#555">${n}</span></div>`
          ).join("");
    }

    // Date breakdown
    const dates = Object.entries(data.by_date || {});
    if (dates.length) {
      dateEl.innerHTML = `<div style="font-weight:600;font-size:12px;color:#888;margin-bottom:4px">By Study Date (most recent)</div>`
        + dates.map(([d, n]) => {
            const fmt = d.length === 8
              ? `${d.substring(0,4)}-${d.substring(4,6)}-${d.substring(6,8)}`
              : d;
            return `<div style="display:flex;justify-content:space-between;font-size:12px;padding:1px 0">
                      <span>${fmt}</span><span style="color:#555">${n}</span></div>`;
          }).join("");
    }
  } catch (e) {
    info.textContent = "Error: " + e;
  }
}

