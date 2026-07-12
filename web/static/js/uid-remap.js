// uid-remap.js — UID Remapper tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// UID Remapper
// ─────────────────────────────────────────────────────────────────

let _uidRemapFiles = [];

function uidRemapFilesSelected() {
  const input = document.getElementById("uid-remap-file-input");
  _uidRemapFiles = Array.from(input.files || []);
  document.getElementById("uid-remap-file-count").textContent =
    _uidRemapFiles.length
      ? i18n("uid_remap.files_selected", { n: _uidRemapFiles.length })
      : "";
  document.getElementById("uid-remap-preview-card").style.display = "none";
}

function _uidRemapBuildForm() {
  const fd = new FormData();
  _uidRemapFiles.forEach(f => fd.append("files", f));
  fd.append("level",  document.getElementById("uid-remap-level").value);
  fd.append("prefix", document.getElementById("uid-remap-prefix").value.trim() || "2.25.");
  return fd;
}

async function doUIDRemapPreview() {
  if (!_uidRemapFiles.length) { toast(i18n("uid_remap.no_files"), "warn"); return; }
  const status = document.getElementById("uid-remap-status");
  status.textContent = i18n("uid_remap.preparing");
  try {
    const res  = await fetch("/api/dicom/uid-remap/preview",
                             { method: "POST", body: _uidRemapBuildForm() });
    const data = await res.json();
    if (!data.ok) { status.textContent = "Error: " + data.error; return; }
    _renderUIDRemapPreview(data.mapping);
    status.textContent = "";
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

function _renderUIDRemapPreview(mapping) {
  const tbody = document.getElementById("uid-remap-preview-tbody");
  tbody.innerHTML = "";
  let hasRows = false;
  mapping.forEach(entry => {
    entry.changes.forEach((ch, i) => {
      hasRows = true;
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td style="font-size:12px">${i === 0 ? escapeHtml(entry.file) : ""}</td>` +
        `<td style="font-size:11px;font-family:Consolas">${ch.tag} ${escapeHtml(ch.name)}</td>` +
        `<td style="font-size:11px;font-family:Consolas;word-break:break-all;max-width:220px;color:#dc2626">${escapeHtml(ch.old)}</td>` +
        `<td style="font-size:11px;font-family:Consolas;word-break:break-all;max-width:220px;color:#16a34a">${escapeHtml(ch.new)}</td>`;
      tbody.appendChild(tr);
    });
  });
  if (!hasRows) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:#888;padding:16px">${i18n("uid_remap.preview_none")}</td></tr>`;
  }
  document.getElementById("uid-remap-preview-card").style.display = "";
  document.getElementById("uid-remap-preview-card").scrollIntoView({ behavior: "smooth" });
}

async function doUIDRemapDownload() {
  if (!_uidRemapFiles.length) { toast(i18n("uid_remap.no_files"), "warn"); return; }
  const status = document.getElementById("uid-remap-status");
  status.textContent = i18n("uid_remap.preparing");
  try {
    const res = await fetch("/api/dicom/uid-remap", { method: "POST", body: _uidRemapBuildForm() });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      status.textContent = "Error: " + (err.error || res.statusText);
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "uid_remapped.zip";
    a.click();
    URL.revokeObjectURL(a.href);
    status.textContent = i18n("uid_remap.done");
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

