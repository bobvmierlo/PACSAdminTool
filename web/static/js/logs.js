// logs.js — Log viewer tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// Log Viewer
// ─────────────────────────────────────────────────────────────────

let _logRefreshTimer   = null;
let _logViewerReady    = false;   // true once file list has been loaded

async function initLogViewer() {
  if (_logViewerReady) return;   // already initialised – just re-use current selection
  try {
    const res  = await fetch("/api/logs/files");
    const data = await res.json();
    if (!data.ok) return;
    const sel = document.getElementById("log-file-select");
    sel.innerHTML = "";
    for (const f of data.files) {
      const opt  = document.createElement("option");
      opt.value  = f.name;
      const kb   = f.size < 1024
                   ? f.size + " B"
                   : f.size < 1048576
                     ? (f.size / 1024).toFixed(1) + " KB"
                     : (f.size / 1048576).toFixed(1) + " MB";
      opt.textContent = `${f.name}  (${kb})`;
      sel.appendChild(opt);
    }
    _logViewerReady = true;
    if (data.files.length > 0) loadLogContent();
  } catch (e) {
    console.error("Log viewer init error:", e);
  }
}

async function loadLogContent() {
  const file   = document.getElementById("log-file-select").value;
  const lines  = document.getElementById("log-lines-select").value;
  const filter = document.getElementById("log-filter-input").value.trim();
  const level  = document.getElementById("log-level-select").value;
  if (!file) return;

  let url = `/api/logs/content?file=${encodeURIComponent(file)}&lines=${lines}`;
  if (filter) url += `&filter=${encodeURIComponent(filter)}`;

  const box  = document.getElementById("log-viewer-content");
  const meta = document.getElementById("log-meta");
  box.textContent = "Loading…";

  try {
    const res  = await fetch(url);
    const data = await res.json();
    if (!data.ok) {
      box.textContent = "Error: " + data.error;
      meta.textContent = "";
      return;
    }
    // Client-side level filter: log format has "  LEVEL  " as a fixed column.
    // Match "  LEVEL" (two leading spaces + level name) case-insensitively.
    let displayed = data.lines;
    if (level) {
      const token = "  " + level;
      displayed = data.lines.filter(ln => ln.toUpperCase().includes(token));
    }
    box.textContent = displayed.join("\n");
    box.scrollTop   = box.scrollHeight;
    const levelNote = level ? ` (${level} filter: ${displayed.length} shown)` : "";
    meta.textContent = `${data.returned} of ${data.total} lines${levelNote}`;
  } catch (e) {
    box.textContent = "Error loading log: " + e;
    meta.textContent = "";
  }
}

function scheduleLogRefresh() {
  clearTimeout(_logRefreshTimer);
  _logRefreshTimer = setTimeout(loadLogContent, 400);
}

