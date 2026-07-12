// inspector.js — Inspector & Editor tab (inspect, sub-tabs, diff)
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// DICOM File Inspector
// ─────────────────────────────────────────────────────────────────

let _inspectorTags = [];

function inspectorFileSelected() {
  const f    = document.getElementById("inspector-file-input").files[0];
  const fnEl = document.getElementById("inspector-filename");
  if (fnEl) fnEl.textContent = f ? f.name : "";
  const mc = document.getElementById("inspector-meta-card");
  if (mc) mc.style.display = "none";
}

async function doInspect() {
  const input = document.getElementById("inspector-file-input");
  if (!input.files || !input.files[0]) {
    toast("Select a DICOM file first.", "warn");
    return;
  }
  _inspectorSetFile(input.files[0]);
  document.getElementById("tag-editor-card").style.display = "none";
  _tagEdits = {};
  const fd = new FormData();
  fd.append("file", input.files[0]);
  try {
    const res  = await fetch("/api/dicom/inspect", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) { toast("Error: " + data.error, "err"); return; }

    _inspectorTags = data.tags || [];
    const grid = document.getElementById("inspector-meta-grid");
    grid.innerHTML = "";
    const m = data.meta || {};
    [
      ["Filename",          m.filename],
      ["Patient Name",      m.PatientName],
      ["Patient ID",        m.PatientID],
      ["Modality",          m.Modality],
      ["Study Date",        m.StudyDate],
      ["SOP Class UID",     m.SOPClassUID],
      ["Transfer Syntax",   m.TransferSyntaxUID],
    ].forEach(([label, val]) => {
      if (!val) return;
      const div = document.createElement("div");
      div.className = "field";
      div.innerHTML = `<label style="color:#888;font-size:11px">${label}</label>
                       <span style="font-size:13px">${val}</span>`;
      grid.appendChild(div);
    });
    document.getElementById("inspector-meta-card").style.display = "";
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

function inspectorShowTags() {
  showTagModal("DICOM Inspector", _inspectorTags);
}

// ── Tag Editor ────────────────────────────────────────────────────

let _tagEdits       = {};  // { "(GGGG,EEEE)": newValue }
let _inspectorFile  = null; // the raw File object for the inspector

// Called after a successful doInspect()
function _inspectorSetFile(file) { _inspectorFile = file; }

function openTagEditor() {
  if (!_inspectorTags.length) { toast(i18n("tag_editor.parse_first"), "warn"); return; }
  _tagEdits = {};
  _populateTagEditorAEDropdown();
  const card = document.getElementById("tag-editor-card");
  const filter = document.getElementById("tag-editor-filter");
  if (!card || !filter) { toast("Tag editor UI not available.", "err"); return; }
  card.style.display = "";
  filter.value = "";
  renderEditTagTable();
  card.scrollIntoView({ behavior: "smooth" });
}

function resetTagEdits() {
  _tagEdits = {};
  renderEditTagTable();
  const cnt = document.getElementById("tag-editor-change-count");
  if (cnt) cnt.textContent = "";
}

function _populateTagEditorAEDropdown() {
  const sel = document.getElementById("tag-editor-ae-select");
  const aes = (appConfig.remote_aes || []);
  sel.innerHTML = `<option value="">${i18n("tag_editor.select_preset")}</option>`;
  aes.forEach((ae, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${ae.name || ae.ae_title} (${ae.ae_title}@${ae.host}:${ae.port})`;
    sel.appendChild(opt);
  });
}

function tagEditorAEChanged() {
  const sel = document.getElementById("tag-editor-ae-select");
  const idx = parseInt(sel.value);
  if (isNaN(idx)) return;
  const ae = (appConfig.remote_aes || [])[idx];
  if (!ae) return;
  document.getElementById("tag-editor-ae-title").value = ae.ae_title || "";
  document.getElementById("tag-editor-ae-host").value  = ae.host     || "";
  document.getElementById("tag-editor-ae-port").value  = ae.port     || "";
}

// Flatten tag tree to a flat list for the editor (skip SQ children)
function _flatTagsForEditor(rows) {
  const out = [];
  rows.forEach(r => {
    out.push(r);
    // We intentionally skip sequence children — they're not editable here
  });
  return out;
}

function renderEditTagTable() {
  const q      = (document.getElementById("tag-editor-filter").value || "").toLowerCase();
  const tbody  = document.getElementById("tag-editor-tbody");
  const flat   = _flatTagsForEditor(_inspectorTags);
  const shown  = q ? flat.filter(r =>
    [r.tag, r.keyword, r.vr, r.value].some(v => String(v).toLowerCase().includes(q))
  ) : flat;

  tbody.innerHTML = "";
  shown.forEach(r => {
    if (r.children) return; // skip SQ headers
    const edited    = Object.prototype.hasOwnProperty.call(_tagEdits, r.tag);
    const dispValue = edited ? _tagEdits[r.tag] : r.value;
    const tr = document.createElement("tr");
    if (edited) tr.style.background = "#fffbeb";
    tr.innerHTML =
      `<td style="font-family:Consolas;font-size:11px">${r.tag}</td>` +
      `<td style="font-size:12px">${escapeHtml(r.keyword)}</td>` +
      `<td style="font-size:11px;color:#6b7280">${r.vr}</td>` +
      `<td id="tev-${r.tag}" style="max-width:320px;word-break:break-all;font-size:12px">${escapeHtml(dispValue)}</td>` +
      `<td><button class="btn" style="font-size:10px;padding:1px 7px" onclick="editTagInline('${r.tag}','${r.vr}')">${i18n("tag_editor.edit_btn")}</button></td>`;
    tbody.appendChild(tr);
  });

  const n = Object.keys(_tagEdits).length;
  const cntEl = document.getElementById("tag-editor-change-count");
  if (cntEl) cntEl.textContent = n ? i18n("tag_editor.changes_pending", { n }) : "";
}

function editTagInline(tag, vr) {
  const cell = document.getElementById("tev-" + tag);
  if (!cell) return;
  if (cell.querySelector("input")) return; // already editing
  const current = cell.textContent;
  cell.innerHTML = "";
  const input = document.createElement("input");
  input.value = current;
  input.style.cssText = "width:100%; font-size:12px; padding:2px 4px; box-sizing:border-box";
  const save = () => {
    _tagEdits[tag] = input.value;
    renderEditTagTable();
  };
  input.addEventListener("blur", save);
  input.addEventListener("keydown", e => { if (e.key === "Enter") { input.blur(); } });
  cell.appendChild(input);
  input.focus();
}

async function downloadEdited() {
  if (!_inspectorFile) { toast(i18n("tag_editor.no_file"), "warn"); return; }
  const status = document.getElementById("tag-editor-status");
  status.textContent = i18n("tag_editor.preparing");
  const fd = new FormData();
  fd.append("file", _inspectorFile);
  fd.append("edits", JSON.stringify(
    Object.entries(_tagEdits).map(([tag, value]) => ({ tag, value }))
  ));
  try {
    const res = await fetch("/api/dicom/edit", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      status.textContent = "Error: " + (err.error || res.statusText);
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href     = URL.createObjectURL(blob);
    a.download = _inspectorFile.name || "edited.dcm";
    a.click();
    URL.revokeObjectURL(a.href);
    status.textContent = i18n("tag_editor.downloaded");
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

async function sendEditedToPACS() {
  if (!_inspectorFile) { toast(i18n("tag_editor.no_file"), "warn"); return; }
  const aeTitle = document.getElementById("tag-editor-ae-title").value.trim();
  const host    = document.getElementById("tag-editor-ae-host").value.trim();
  const portStr = document.getElementById("tag-editor-ae-port").value.trim();
  const port    = parsePort(portStr);
  if (!aeTitle || !host || port === null) {
    toast(i18n("tag_editor.fill_ae_fields"), "warn");
    return;
  }
  const status = document.getElementById("tag-editor-status");
  status.textContent = i18n("tag_editor.sending");
  const fd = new FormData();
  fd.append("file",     _inspectorFile);
  fd.append("edits",    JSON.stringify(
    Object.entries(_tagEdits).map(([tag, value]) => ({ tag, value }))
  ));
  fd.append("ae_title", aeTitle);
  fd.append("host",     host);
  fd.append("port",     port);
  try {
    const res  = await fetch("/api/dicom/edit-and-store", { method: "POST", body: fd });
    const data = await res.json();
    status.textContent = data.ok ? `Sent: ${data.message}` : `Error: ${data.error || data.message}`;
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

// ─────────────────────────────────────────────────────────────────
// Inspector sub-tab switcher
// ─────────────────────────────────────────────────────────────────

function showInspectorSubTab(name) {
  ["edit", "diff"].forEach(n => {
    document.getElementById("inspector-subtab-" + n).classList.toggle("active", n === name);
    document.getElementById("inspector-subtab-btn-" + n).classList.toggle("active", n === name);
  });
}

// ─────────────────────────────────────────────────────────────────
// DICOM Diff
// ─────────────────────────────────────────────────────────────────

function diffFileChanged(side) {
  const input = document.getElementById("diff-file-" + side);
  const span  = document.getElementById("diff-filename-" + side);
  span.textContent = (input.files && input.files[0]) ? input.files[0].name
                                                      : i18n("diff.no_file");
}

let _diffLastRows = null, _diffLastSummary = null;

async function doDiff() {
  const fa = document.getElementById("diff-file-a").files[0];
  const fb = document.getElementById("diff-file-b").files[0];
  if (!fa || !fb) { toast(i18n("diff.select_both"), "warn"); return; }

  const fd = new FormData();
  fd.append("file_a", fa);
  fd.append("file_b", fb);

  try {
    const res  = await fetch("/api/dicom/diff", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) { toast("Error: " + data.error, "err"); return; }
    _diffLastRows    = data.rows;
    _diffLastSummary = data.summary;
    _renderDiffResults();
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

function _renderDiffResults() {
  if (!_diffLastRows) return;
  const rows     = _diffLastRows;
  const summary  = _diffLastSummary;
  const onlyDiff = document.getElementById("diff-only-changes").checked;
  const visible  = onlyDiff ? rows.filter(r => r.status !== "same") : rows;

  const s = summary;
  document.getElementById("diff-summary").textContent =
    i18n("diff.summary", s) ||
    `${s.different} changed · ${s.only_a} only in A · ${s.only_b} only in B · ${s.same} identical`;

  const tbody = document.getElementById("diff-tbody");
  tbody.innerHTML = "";
  if (!visible.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:#888;padding:16px">${i18n("diff.no_results")}</td></tr>`;
  } else {
    const colours = { different: "#fffbeb", only_a: "#fff0f0", only_b: "#f0fff4", same: "" };
    const labels  = {
      different: () => i18n("diff.status_different"),
      only_a:    () => i18n("diff.status_only_a"),
      only_b:    () => i18n("diff.status_only_b"),
      same:      () => i18n("diff.status_same"),
    };
    visible.forEach(r => {
      const tr = document.createElement("tr");
      tr.style.background = colours[r.status] || "";
      tr.innerHTML =
        `<td style="font-family:Consolas;font-size:11px">${r.tag}</td>` +
        `<td style="font-size:12px">${escapeHtml(r.keyword)}</td>` +
        `<td style="font-size:11px;color:#6b7280">${r.vr}</td>` +
        `<td style="font-size:12px;max-width:260px;word-break:break-all">${escapeHtml(r.value_a)}</td>` +
        `<td style="font-size:12px;max-width:260px;word-break:break-all">${escapeHtml(r.value_b)}</td>` +
        `<td style="font-size:11px;white-space:nowrap">${labels[r.status]?.() || r.status}</td>`;
      tbody.appendChild(tr);
    });
  }
  document.getElementById("diff-results-card").style.display = "";
}

