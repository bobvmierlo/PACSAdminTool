// dicomize.js — DICOMize tab (PDF / images / video, DMWL + ORU workflows)
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 20. DICOMize
// ─────────────────────────────────────────────────────────────────

function showDicomizeTab(sub) {
  ["pdf", "images", "video", "mixed"].forEach(s => {
    document.getElementById(`dz-subtab-${s}`).classList.toggle("active", s === sub);
    document.getElementById(`dz-tab-${s}-btn`).classList.toggle("active", s === sub);
  });
}

function toggleDicomizePatient() {
  const body  = document.getElementById("dicomize-patient-body");
  const arrow = document.getElementById("dicomize-patient-arrow");
  const open  = body.style.display !== "none";
  body.style.display  = open ? "none" : "";
  arrow.textContent   = open ? "▶" : "▼";
}

function dzGenerateUID() {
  // Generate a simple UID using crypto.randomUUID if available, else Math.random
  let uid;
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    const u = crypto.randomUUID().replace(/-/g, "");
    uid = "2.25." + BigInt("0x" + u).toString();
  } else {
    uid = "2.25." + Math.floor(Math.random() * 1e18).toString();
  }
  document.getElementById("dz-study-uid").value = uid;
}

function _dzGetMetadata(seriesDescId) {
  const fd = new FormData();
  const add = (key, id) => fd.append(key, document.getElementById(id)?.value || "");
  add("patient_name",      "dz-patient-name");
  add("patient_id",        "dz-patient-id");
  fd.append("patient_dob", dateToDisom(document.getElementById("dz-patient-dob")?.value || ""));
  add("patient_sex",       "dz-patient-sex");
  add("study_uid",         "dz-study-uid");
  fd.append("study_date",  dateToDisom(document.getElementById("dz-study-date")?.value || ""));
  fd.append("study_time",  timeToDisom(document.getElementById("dz-study-time")?.value || ""));
  add("study_description", "dz-study-desc");
  add("accession_number",  "dz-accession");
  add("institution_name",  "dz-institution");
  if (seriesDescId) add("series_description", seriesDescId);
  return fd;
}

function _dzGetAE(prefix) {
  return {
    ae_title: document.getElementById(`dz-${prefix}-ae-title`)?.value || "",
    ae_host:  document.getElementById(`dz-${prefix}-ae-host`)?.value  || "",
    ae_port:  document.getElementById(`dz-${prefix}-ae-port`)?.value  || "",
  };
}

// Populate AE fields from config preset
function dzFillAE(prefix) {
  const sel = document.getElementById(`dz-${prefix}-ae-preset`);
  const val = sel?.value || "";
  if (!val) return;
  let ae;
  if (val.startsWith("usr:")) {
    ae = (userSettings.remote_aes || []).find(a => a.name === val.slice(4));
  } else {
    const name = val.startsWith("sys:") ? val.slice(4) : val;
    ae = (appConfig.remote_aes || []).find(a => a.name === name);
  }
  if (!ae) return;
  document.getElementById(`dz-${prefix}-ae-title`).value = ae.ae_title || "";
  document.getElementById(`dz-${prefix}-ae-host`).value  = ae.host     || "";
  document.getElementById(`dz-${prefix}-ae-port`).value  = ae.port     || "";
}

// ── Drag-and-drop helpers ─────────────────────────────────────────

function _dzDragOver(event, zoneId) {
  event.preventDefault();
  document.getElementById(zoneId)?.classList.add("dragover");
}

function _dzDragLeave(zoneId) {
  document.getElementById(zoneId)?.classList.remove("dragover");
}

function _dzDrop(event, inputId) {
  event.preventDefault();
  const zoneId = event.currentTarget.id;
  document.getElementById(zoneId)?.classList.remove("dragover");
  const input = document.getElementById(inputId);
  if (!input || !event.dataTransfer.files.length) return;
  const dt = new DataTransfer();
  Array.from(event.dataTransfer.files).forEach(f => dt.items.add(f));
  input.files = dt.files;
  input.dispatchEvent(new Event("change"));
}

// ── FPS row toggle ─────────────────────────────────────────────────

function _dzToggleFps(prefix) {
  const fmt = document.querySelector(`input[name="dz-${prefix}-video-format"]:checked`)?.value;
  const row = document.getElementById(`dz-${prefix}-fps-row`);
  if (row) row.style.display = fmt === "multiframe" ? "flex" : "none";
}

// ── Source selector (Manual / DMWL / ORU IAN) ────────────────────

function dzSetSource(src) {
  ["manual", "dmwl", "cfind", "oruian"].forEach(s => {
    const btn   = document.getElementById(`dz-src-btn-${s}`);
    const panel = document.getElementById(`dz-src-panel-${s}`);
    if (btn)   btn.classList.toggle("active", s === src);
    if (panel) panel.style.display = (s === src && s !== "manual") ? "" : "none";
  });
  if (src === "oruian") {
    _dzOruIanPopulateTemplates();
    _dzPopulateHl7Servers();
  }
  if (src === "dmwl" || src === "cfind") {
    dzLoadPresets();
  }
}

function _dzPopulateHl7Servers() {
  const sel = document.getElementById("dz-oruian-server-preset");
  if (!sel) return;
  const servers = (appConfig.hl7_servers || []).concat(
    (userSettings.hl7_servers || []).map(s => ({...s, _user: true}))
  );
  sel.innerHTML = `<option value="">— manual —</option>`;
  servers.forEach(s => {
    const opt = document.createElement("option");
    opt.value       = JSON.stringify({host: s.host, port: s.port});
    opt.textContent = s.name || `${s.host}:${s.port}`;
    sel.appendChild(opt);
  });
}

function dzOruIanFillServer() {
  const sel = document.getElementById("dz-oruian-server-preset");
  if (!sel?.value) return;
  try {
    const s = JSON.parse(sel.value);
    if (s.host) document.getElementById("dz-oruian-host").value = s.host;
    if (s.port) document.getElementById("dz-oruian-port").value = s.port;
  } catch (_) {}
}

// ── DMWL inline query ─────────────────────────────────────────────

function dzSrcDmwlFillAE() {
  const val = document.getElementById("dz-src-dmwl-preset").value;
  if (!val) return;
  let ae;
  if (val.startsWith("usr:")) {
    ae = (userSettings.remote_aes || []).find(a => a.name === val.slice(4));
  } else {
    const name = val.startsWith("sys:") ? val.slice(4) : val;
    ae = (appConfig.remote_aes || []).find(a => a.name === name);
  }
  if (!ae) return;
  document.getElementById("dz-src-dmwl-aet").value  = ae.ae_title || "";
  document.getElementById("dz-src-dmwl-host").value = ae.host     || "";
  document.getElementById("dz-src-dmwl-port").value = ae.port     || "";
}

async function dzSrcDmwlQuery() {
  const aet  = document.getElementById("dz-src-dmwl-aet").value.trim();
  const host = document.getElementById("dz-src-dmwl-host").value.trim();
  const port = document.getElementById("dz-src-dmwl-port").value.trim();
  const statusEl  = document.getElementById("dz-src-dmwl-status");
  const resultsEl = document.getElementById("dz-src-dmwl-results");
  const bodyEl    = document.getElementById("dz-src-dmwl-body");
  if (!host || !port) {
    statusEl.textContent = i18n("dicomize.oruian_no_host");
    return;
  }
  statusEl.textContent = i18n("dicomize.wl_querying") || "Querying…";
  resultsEl.style.display = "none";
  try {
    const res  = await fetch("/api/dicom/dmwl", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        host, port: parseInt(port, 10), ae_title: aet,
        patient_name: document.getElementById("dz-src-dmwl-name").value.trim() || "*",
        patient_id:   document.getElementById("dz-src-dmwl-id").value.trim()   || "",
        accession: "", modality: "", study_date: "", station_aet: "",
        scheduled_date: document.getElementById("dz-src-dmwl-date").value || "",
      }),
    });
    const data = await res.json();
    if (!data.ok) { statusEl.textContent = data.message || data.error || "Error"; return; }
    const rows = data.results || [];
    statusEl.textContent = i18n("dicomize.wl_found", {n: rows.length}) || `${rows.length} result(s)`;
    if (!rows.length) return;
    bodyEl.innerHTML = rows.map((r, idx) => `<tr style="border-bottom:1px solid var(--border); cursor:pointer"
      onclick="_dzSrcDmwlFill(${idx})"
      title="${escapeHtml(i18n("dicomize.wl_click_fill") || "Click to fill fields")}">
      <td style="padding:4px 8px">${escapeHtml(r.PatientName || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(r.PatientID   || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(r.Accession   || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(r.ScheduledDate || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(r.Procedure   || "")}</td>
    </tr>`).join("");
    resultsEl.style.display = "";
    window._dzSrcDmwlRows = rows;
  } catch (e) {
    statusEl.textContent = String(e);
  }
}

function _dzSrcDmwlFill(idx) {
  const r = (window._dzSrcDmwlRows || [])[idx];
  if (!r) return;
  const set = (id, v) => { if (v !== undefined && v !== null) document.getElementById(id).value = v; };
  set("dz-patient-name", r.PatientName);
  set("dz-patient-id",   r.PatientID);
  set("dz-patient-dob",  dicomDateToInput(r.PatientBirthDate || ""));
  set("dz-patient-sex",  r.PatientSex);
  set("dz-accession",    r.Accession);
  set("dz-study-desc",   r.Procedure);
  set("dz-study-date",   dicomDateToInput(r.ScheduledDate || ""));
  if (r.StudyInstanceUID) document.getElementById("dz-study-uid").value = r.StudyInstanceUID;
  appendLog("log-dicomize", now(), i18n("dicomize.wl_filled", {name: r.PatientName || "?"}), "ok");
}

// ── C-FIND inline query (for studies no longer on the DMWL) ──────

function dzSrcCfindFillAE() {
  const val = document.getElementById("dz-src-cfind-preset").value;
  if (!val) return;
  let ae;
  if (val.startsWith("usr:")) {
    ae = (userSettings.remote_aes || []).find(a => a.name === val.slice(4));
  } else {
    const name = val.startsWith("sys:") ? val.slice(4) : val;
    ae = (appConfig.remote_aes || []).find(a => a.name === name);
  }
  if (!ae) return;
  document.getElementById("dz-src-cfind-aet").value  = ae.ae_title || "";
  document.getElementById("dz-src-cfind-host").value = ae.host     || "";
  document.getElementById("dz-src-cfind-port").value = ae.port     || "";
}

async function dzSrcCfindQuery() {
  const aet  = document.getElementById("dz-src-cfind-aet").value.trim();
  const host = document.getElementById("dz-src-cfind-host").value.trim();
  const port = document.getElementById("dz-src-cfind-port").value.trim();
  const statusEl  = document.getElementById("dz-src-cfind-status");
  const resultsEl = document.getElementById("dz-src-cfind-results");
  const bodyEl    = document.getElementById("dz-src-cfind-body");
  if (!aet || !host || !port) {
    statusEl.textContent = i18n("dicomize.wl_need_ae");
    return;
  }
  statusEl.textContent = i18n("dicomize.wl_querying") || "Querying…";
  resultsEl.style.display = "none";
  try {
    const res  = await fetch("/api/dicom/find", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        host, port: parseInt(port, 10), ae_title: aet,
        query_level: "STUDY", query_model: "STUDY",
        patient_name: document.getElementById("dz-src-cfind-name").value.trim() || "*",
        patient_id:   document.getElementById("dz-src-cfind-id").value.trim()   || "",
        accession:    document.getElementById("dz-src-cfind-acc").value.trim()  || "",
        study_date:   dateToDisom(document.getElementById("dz-src-cfind-date").value || ""),
        modality: "", study_uid: "",
        // Not part of STUDY-level return keys, but many SCPs return them;
        // used to fill DOB / sex when available.
        extra_tags: ["PatientBirthDate", "PatientSex"],
      }),
    });
    const data = await res.json();
    if (!data.ok) { statusEl.textContent = data.message || data.error || "Error"; return; }
    const rows = data.results || [];
    statusEl.textContent = i18n("dicomize.wl_found", {n: rows.length}) || `${rows.length} result(s)`;
    if (!rows.length) return;
    bodyEl.innerHTML = rows.map((r, idx) => `<tr style="border-bottom:1px solid var(--border); cursor:pointer"
      onclick="_dzSrcCfindFill(${idx})"
      title="${escapeHtml(i18n("dicomize.wl_click_fill") || "Click to fill fields")}">
      <td style="padding:4px 8px">${escapeHtml(r.PatientName || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(r.PatientID   || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(r.Accession   || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(r.Modality    || "")}</td>
      <td style="padding:4px 8px">${escapeHtml(formatDicomDate(r.StudyDate || ""))}</td>
      <td style="padding:4px 8px">${escapeHtml(r.Description || "")}</td>
    </tr>`).join("");
    resultsEl.style.display = "";
    window._dzSrcCfindRows = rows;
  } catch (e) {
    statusEl.textContent = String(e);
  }
}

function _dzSrcCfindFill(idx) {
  const r = (window._dzSrcCfindRows || [])[idx];
  if (!r) return;
  const tagVal = kw => ((r.tags || []).find(t => t.keyword === kw) || {}).value || "";
  const set = (id, v) => { if (v !== undefined && v !== null) document.getElementById(id).value = v; };
  set("dz-patient-name", r.PatientName);
  set("dz-patient-id",   r.PatientID);
  set("dz-patient-dob",  dicomDateToInput(tagVal("PatientBirthDate")));
  set("dz-patient-sex",  tagVal("PatientSex"));
  set("dz-accession",    r.Accession);
  set("dz-study-desc",   r.Description);
  set("dz-study-date",   dicomDateToInput(r.StudyDate || ""));
  if (r.StudyUID) document.getElementById("dz-study-uid").value = r.StudyUID;
  appendLog("log-dicomize", now(), i18n("dicomize.wl_filled", {name: r.PatientName || "?"}), "ok");
}

// ── ORM field-map editor ───────────────────────────────────────────

function dzOrmMapSave() {
  const ta  = document.getElementById("dz-orm-map-editor");
  const st  = document.getElementById("dz-orm-map-status");
  let map;
  try { map = JSON.parse(ta.value); } catch (e) {
    st.textContent = "Invalid JSON";
    st.style.color = "var(--err,red)";
    return;
  }
  fetch("/api/config", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ orm_field_map: map }),
  }).then(r => r.json()).then(d => {
    st.textContent = d.ok ? (i18n("dicomize.orm_map_saved") || "Saved") : (d.error || "Error");
    st.style.color = d.ok ? "var(--ok,green)" : "var(--err,red)";
    if (d.ok && window.appConfig) window.appConfig.orm_field_map = map;
  }).catch(e => { st.textContent = String(e); st.style.color = "var(--err,red)"; });
}

function dzShowOrmDefaults() {
  const defaults = {
    "patient_name":      "PID.5",
    "patient_id":        "PID.3",
    "patient_dob":       "PID.7",
    "patient_sex":       "PID.8",
    "accession_number":  "OBR.2",
    "study_description": "OBR.4.2",
    "study_datetime":    "OBR.7",
    "institution":       "MSH.3"
  };
  _dialog({
    title: "Default ORM field mapping",
    message: "These are the built-in defaults used when no custom mapping is configured:\n\n" +
      Object.entries(defaults).map(([k, v]) => `  "${k}": "${v}"`).join("\n"),
    buttons: [{ text: "Close", value: null, className: "btn" }],
  });
}

function dzShowOrmFields() {
  const fields = [
    ["patient_name",      "Patient name (PascalCase → HL7 family^given^…)"],
    ["patient_id",        "Patient ID / Medical Record Number"],
    ["patient_dob",       "Date of birth (YYYYMMDD)"],
    ["patient_sex",       "Sex (M / F / O / U)"],
    ["accession_number",  "Accession number (placer order number)"],
    ["study_description", "Study / procedure description text"],
    ["study_datetime",    "Study date & time (YYYYMMDDHHMMSS)"],
    ["institution",       "Sending facility / institution name"],
  ];
  _dialog({
    title: "Available ORM mapping fields",
    message: "Use these snake_case keys in your custom mapping JSON.\n" +
      "Value is an HL7 segment reference: SEGMENT.field[.component] (1-based).\n\n" +
      fields.map(([k, d]) => `  "${k}"\n    → ${d}`).join("\n\n"),
    buttons: [{ text: "Close", value: null, className: "btn" }],
  });
}

function dzHl7Inspect(rawText) {
  if (!rawText || !rawText.trim()) { toast(i18n("hl7.no_message") || "No HL7 message to inspect.", "warn"); return; }
  const tbodyId   = "dz-hl7-parsed-tbody";
  const cardId    = "dz-hl7-inspector-card";
  const infoId    = "dz-hl7-field-info";
  const infoConId = "dz-hl7-field-info-content";
  const segments  = _hl7Parse(rawText);
  const tbody     = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  segments.forEach(({ seg, fields }) => {
    const def     = _HL7_SEGMENTS[seg];
    const segName = def ? def.name : "Unknown segment";
    const tr      = document.createElement("tr");
    tr.style.cssText = "vertical-align:top; border-bottom:1px solid #e2e8f0";
    const tdSeg = document.createElement("td");
    tdSeg.style.cssText = "padding:3px 6px; font-weight:700; white-space:nowrap; cursor:pointer; color:#2b6cb0";
    tdSeg.textContent   = seg;
    tdSeg.title         = segName;
    tdSeg.onclick       = () => _hl7ShowSegInfo(seg, infoId, infoConId);
    tr.appendChild(tdSeg);
    const tdFields = document.createElement("td");
    tdFields.style.cssText = "padding:3px 4px; word-break:break-all; line-height:1.8";
    fields.forEach((val, idx) => {
      const fieldNum = idx + 1;
      const fdDef    = def?.fields.find(f => f.seq === fieldNum);
      const chip     = document.createElement("span");
      chip.style.cssText =
        "display:inline-block; margin:1px 2px; padding:1px 5px; border-radius:3px; " +
        "border:1px solid #cbd5e0; background:#f7fafc; font-size:11px; cursor:pointer; " +
        "max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:middle";
      chip.title       = fdDef ? `${seg}.${fieldNum} — ${fdDef.name} (${fdDef.dt})` : `${seg}.${fieldNum}`;
      chip.textContent = val || (fdDef ? "—" : "");
      if (val) chip.style.background = "#ebf8ff";
      chip.onclick = () => _hl7ShowFieldInfo(seg, fieldNum, val, infoId, infoConId);
      tdFields.appendChild(chip);
    });
    tr.appendChild(tdFields);
    tbody.appendChild(tr);
  });
  const card = document.getElementById(cardId);
  if (card) { card.style.display = ""; card.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  const infoEl = document.getElementById(infoId);
  if (infoEl) infoEl.style.display = "none";
}

// Populate ORM map editor textarea when the details is opened
document.addEventListener("DOMContentLoaded", () => {
  const det = document.getElementById("dz-meta-preview-details");
  if (det) det.addEventListener("toggle", dzShowMetaPreview);
  const ormDet = document.querySelector("#dz-src-panel-oruian details");
  if (ormDet) ormDet.addEventListener("toggle", () => {
    const ta = document.getElementById("dz-orm-map-editor");
    if (ta && !ta.value) {
      const map = (window.appConfig || {}).orm_field_map || {};
      ta.value = JSON.stringify(map, null, 2);
    }
  });
});

// ── DICOM metadata preview ─────────────────────────────────────────

function dzShowMetaPreview() {
  const det = document.getElementById("dz-meta-preview-details");
  if (!det || !det.open) return;
  const get = id => (document.getElementById(id)?.value || "").trim();
  const lines = [
    ["Patient Name",      get("dz-patient-name")],
    ["Patient ID",        get("dz-patient-id")],
    ["Date of Birth",     get("dz-patient-dob")],
    ["Sex",               get("dz-patient-sex")],
    ["Study Date",        get("dz-study-date")],
    ["Study Time",        get("dz-study-time")],
    ["Study Description", get("dz-study-desc")],
    ["Accession #",       get("dz-accession")],
    ["Institution",       get("dz-institution")],
    ["Study UID",         get("dz-study-uid")],
  ].filter(([,v]) => v);
  const content = document.getElementById("dz-meta-preview-content");
  if (!content) return;
  content.innerHTML = lines.length
    ? lines.map(([k,v]) => `<div><span style="color:#888;min-width:160px;display:inline-block">${escapeHtml(k)}:</span> <strong>${escapeHtml(v)}</strong></div>`).join("")
    : `<span style="color:#aaa">${i18n("dicomize.meta_preview_empty") || "(no data entered)"}</span>`;
}

// Hook form changes to auto-refresh metadata preview
["dz-patient-name","dz-patient-id","dz-patient-dob","dz-patient-sex",
 "dz-study-date","dz-study-time","dz-study-desc","dz-accession","dz-institution","dz-study-uid"]
  .forEach(id => {
    document.addEventListener("DOMContentLoaded", () => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", dzShowMetaPreview);
    });
  });

// ── XHR upload with progress bar ──────────────────────────────────

function _dzUpload(url, fd, progressId, barId, { binary = false } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const progressEl = document.getElementById(progressId);
    const barEl      = document.getElementById(barId);
    if (progressEl) progressEl.style.display = "";
    if (barEl)      barEl.style.width = "0%";
    if (binary) xhr.responseType = "arraybuffer";
    xhr.upload.addEventListener("progress", e => {
      if (e.lengthComputable && barEl) {
        barEl.style.width = `${Math.round(e.loaded / e.total * 100)}%`;
      }
    });
    xhr.addEventListener("load", () => {
      if (progressEl) progressEl.style.display = "none";
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr);
      } else {
        reject(new Error(`HTTP ${xhr.status}`));
      }
    });
    xhr.addEventListener("error", () => {
      if (progressEl) progressEl.style.display = "none";
      reject(new Error("Network error"));
    });
    xhr.open("POST", url);
    xhr.send(fd);
  });
}

// ── Duplicate study check ──────────────────────────────────────────

async function dzCheckDuplicate(studyUid, ae) {
  if (!studyUid) return true;
  try {
    const res  = await fetch("/api/dicomize/check-duplicate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ study_instance_uid: studyUid, ...ae }),
    });
    const data = await res.json();
    if (!data.ok || !data.exists) return true;
    return confirm(i18n("dicomize.duplicate_warning",
      {count: data.count, uid: studyUid}) ||
      `Study UID already exists in PACS (${data.count} instance(s)). Send anyway?`);
  } catch (_) { return true; }
}

// Populate AE preset dropdowns from config (with system + user optgroups)
function dzLoadPresets() {
  const sysPresets  = appConfig.remote_aes   || [];
  const userPresets = userSettings.remote_aes || [];
  // AE dropdowns per subtab
  ["pdf", "images", "video", "mixed"].forEach(pfx => {
    const sel = document.getElementById(`dz-${pfx}-ae-preset`);
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = `<option value=""></option>`;
    if (sysPresets.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = i18n("settings.system_presets");
      sysPresets.forEach(ae => {
        const opt = document.createElement("option");
        opt.value = "sys:" + ae.name; opt.textContent = ae.name;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }
    if (userPresets.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = i18n("settings.user_presets");
      userPresets.forEach(ae => {
        const opt = document.createElement("option");
        opt.value = "usr:" + ae.name; opt.textContent = ae.name;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }
    sel.value = prev;
  });
  // DMWL / C-FIND preset dropdowns in the source panels
  ["dz-src-dmwl-preset", "dz-src-cfind-preset"].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = `<option value=""></option>`;
    if (sysPresets.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = i18n("settings.system_presets");
      sysPresets.forEach(ae => {
        const opt = document.createElement("option");
        opt.value = "sys:" + ae.name; opt.textContent = ae.name;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }
    if (userPresets.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = i18n("settings.user_presets");
      userPresets.forEach(ae => {
        const opt = document.createElement("option");
        opt.value = "usr:" + ae.name; opt.textContent = ae.name;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }
    sel.value = prev;
  });
}

// Toggle AE panel visibility
function _dzToggleAE(prefix, show) {
  const el = document.getElementById(`dz-${prefix}-ae`);
  if (el) el.style.display = show ? "" : "none";
}

// ── PDF ──────────────────────────────────────────────────────────

function dzPDFSelected() {
  const f = document.getElementById("dz-pdf-input").files[0];
  document.getElementById("dz-pdf-filename").textContent =
    f ? f.name : i18n("dicomize.pdf_no_file");
}

async function doDicomizePDF(action) {
  const input = document.getElementById("dz-pdf-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No PDF selected."}), "warn");
    return;
  }
  if (action === "store") {
    _dzToggleAE("pdf", true);
    dzLoadPresets();
    return;
  }
  appendLog("log-dicomize", now(), i18n("dicomize.converting"));
  const fd = _dzGetMetadata("dz-pdf-series-desc");
  fd.append("document_title", document.getElementById("dz-pdf-title")?.value || "");
  fd.append("file", input.files[0]);
  try {
    const xhr = await _dzUpload("/api/dicomize/pdf", fd, "dz-pdf-progress", "dz-pdf-progress-bar", { binary: true });
    const blob = new Blob([xhr.response], { type: xhr.getResponseHeader("Content-Type") || "application/octet-stream" });
    const cd   = xhr.getResponseHeader("Content-Disposition") || "";
    const name = cd.match(/filename="?([^"]+)"?/)?.[1] || "output.dcm";
    _dzDownload(blob, name);
    appendLog("log-dicomize", now(), i18n("dicomize.download_ok"), "ok");
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

async function doDicomizePDFStore() {
  const input = document.getElementById("dz-pdf-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No PDF selected."}), "warn");
    return;
  }
  const ae = _dzGetAE("pdf");
  const studyUid = document.getElementById("dz-study-uid")?.value.trim();
  if (!await dzCheckDuplicate(studyUid, ae)) return;
  appendLog("log-dicomize", now(), i18n("dicomize.storing"));
  const fd = _dzGetMetadata("dz-pdf-series-desc");
  fd.append("document_title", document.getElementById("dz-pdf-title")?.value || "");
  fd.append("file", input.files[0]);
  fd.append("ae_title", ae.ae_title);
  fd.append("ae_host",  ae.ae_host);
  fd.append("ae_port",  ae.ae_port);
  try {
    const xhr  = await _dzUpload("/api/dicomize/pdf/store", fd, "dz-pdf-progress", "dz-pdf-progress-bar");
    const data = JSON.parse(xhr.responseText);
    if (data.ok) {
      appendLog("log-dicomize", now(), i18n("dicomize.store_ok", {message: data.message}), "ok");
    } else {
      appendLog("log-dicomize", now(), i18n("dicomize.error", {message: data.error || data.message}), "err");
    }
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

// ── Images ────────────────────────────────────────────────────────

function dzImagesSelected() {
  const files = document.getElementById("dz-images-input").files;
  document.getElementById("dz-images-filename").textContent = files.length
    ? i18n("dicomize.image_files_selected", {n: files.length})
    : i18n("dicomize.image_no_files");
}

async function doDicomizeImages(action) {
  const input = document.getElementById("dz-images-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No images selected."}), "warn");
    return;
  }
  if (action === "store") {
    _dzToggleAE("images", true);
    dzLoadPresets();
    return;
  }
  appendLog("log-dicomize", now(), i18n("dicomize.converting"));
  const fd = _dzGetMetadata("dz-images-series-desc");
  Array.from(input.files).forEach(f => fd.append("files", f));
  if (document.getElementById("dz-images-group-series")?.checked) fd.append("group_series", "1");
  try {
    const xhr  = await _dzUpload("/api/dicomize/image", fd, "dz-images-progress", "dz-images-progress-bar", { binary: true });
    const ct   = xhr.getResponseHeader("Content-Type") || "";
    const cd   = xhr.getResponseHeader("Content-Disposition") || "";
    const name = cd.match(/filename="?([^"]+)"?/)?.[1] || (ct.includes("zip") ? "images_dicom.zip" : "output.dcm");
    _dzDownload(new Blob([xhr.response], { type: ct || "application/octet-stream" }), name);
    appendLog("log-dicomize", now(), i18n("dicomize.download_ok"), "ok");
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

async function doDicomizeImagesStore() {
  const input = document.getElementById("dz-images-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No images selected."}), "warn");
    return;
  }
  const ae = _dzGetAE("images");
  const studyUid = document.getElementById("dz-study-uid")?.value.trim();
  if (!await dzCheckDuplicate(studyUid, ae)) return;
  appendLog("log-dicomize", now(), i18n("dicomize.storing"));
  const fd = _dzGetMetadata("dz-images-series-desc");
  Array.from(input.files).forEach(f => fd.append("files", f));
  if (document.getElementById("dz-images-group-series")?.checked) fd.append("group_series", "1");
  fd.append("ae_title", ae.ae_title);
  fd.append("ae_host",  ae.ae_host);
  fd.append("ae_port",  ae.ae_port);
  try {
    const xhr  = await _dzUpload("/api/dicomize/image/store", fd, "dz-images-progress", "dz-images-progress-bar");
    const data = JSON.parse(xhr.responseText);
    if (data.ok) {
      appendLog("log-dicomize", now(), i18n("dicomize.store_ok", {message: data.message}), "ok");
    } else {
      appendLog("log-dicomize", now(), i18n("dicomize.error", {message: data.error || data.message}), "err");
    }
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

// ── Video ─────────────────────────────────────────────────────────

function dzVideoSelected() {
  const f = document.getElementById("dz-video-input").files[0];
  document.getElementById("dz-video-filename").textContent =
    f ? f.name : i18n("dicomize.video_no_file");
}

function _dzVideoFormat() {
  const checked = document.querySelector('input[name="dz-video-format"]:checked');
  return checked ? checked.value : "encapsulated";
}

async function doDicomizeVideo(action) {
  const input = document.getElementById("dz-video-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No video selected."}), "warn");
    return;
  }
  if (action === "store") {
    _dzToggleAE("video", true);
    dzLoadPresets();
    return;
  }
  const fmt = _dzVideoFormat();
  appendLog("log-dicomize", now(), i18n("dicomize.converting") +
    (fmt === "multiframe" ? " (multi-frame…)" : ""));
  const fd = _dzGetMetadata("dz-video-series-desc");
  fd.append("file", input.files[0]);
  fd.append("video_format", fmt);
  if (fmt === "multiframe") {
    const fps = document.getElementById("dz-video-fps")?.value;
    if (fps) fd.append("fps_limit", fps);
  }
  try {
    const xhr  = await _dzUpload("/api/dicomize/video", fd, "dz-video-progress", "dz-video-progress-bar", { binary: true });
    const cd   = xhr.getResponseHeader("Content-Disposition") || "";
    const name = cd.match(/filename="?([^"]+)"?/)?.[1] || "output.dcm";
    _dzDownload(new Blob([xhr.response], { type: xhr.getResponseHeader("Content-Type") || "application/octet-stream" }), name);
    appendLog("log-dicomize", now(), i18n("dicomize.download_ok"), "ok");
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

async function doDicomizeVideoStore() {
  const input = document.getElementById("dz-video-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No video selected."}), "warn");
    return;
  }
  const ae = _dzGetAE("video");
  const studyUid = document.getElementById("dz-study-uid")?.value.trim();
  if (!await dzCheckDuplicate(studyUid, ae)) return;
  appendLog("log-dicomize", now(), i18n("dicomize.storing"));
  const fmt = _dzVideoFormat();
  const fd = _dzGetMetadata("dz-video-series-desc");
  fd.append("file", input.files[0]);
  fd.append("video_format", fmt);
  if (fmt === "multiframe") {
    const fps = document.getElementById("dz-video-fps")?.value;
    if (fps) fd.append("fps_limit", fps);
  }
  fd.append("ae_title", ae.ae_title);
  fd.append("ae_host",  ae.ae_host);
  fd.append("ae_port",  ae.ae_port);
  try {
    const xhr  = await _dzUpload("/api/dicomize/video/store", fd, "dz-video-progress", "dz-video-progress-bar");
    const data = JSON.parse(xhr.responseText);
    if (data.ok) {
      appendLog("log-dicomize", now(), i18n("dicomize.store_ok", {message: data.message}), "ok");
    } else {
      appendLog("log-dicomize", now(), i18n("dicomize.error", {message: data.error || data.message}), "err");
    }
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

// ── Mixed ─────────────────────────────────────────────────────────

const _DZ_IMAGE_EXTS = new Set([".jpg",".jpeg",".png",".bmp",".tiff",".tif",".webp",".jfif",".jpe"]);
const _DZ_VIDEO_EXTS = new Set([".mp4",".m4v",".mov",".avi",".mkv",".webm"]);
const _DZ_PDF_EXTS   = new Set([".pdf"]);

function _dzDetectType(filename) {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  if (_DZ_IMAGE_EXTS.has(ext)) return "image";
  if (_DZ_VIDEO_EXTS.has(ext)) return "video";
  if (_DZ_PDF_EXTS.has(ext))   return "pdf";
  return "unknown";
}

function _dzFmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes/1024).toFixed(1)} KB`;
  return `${(bytes/1048576).toFixed(1)} MB`;
}

function dzMixedSelected(source) {
  // When files come from the folder input, copy them to the main input so the
  // rest of the code (doDicomizeMixed etc.) always reads from dz-mixed-input.
  if (source === "folder") {
    const folderInput = document.getElementById("dz-mixed-folder-input");
    const mainInput   = document.getElementById("dz-mixed-input");
    if (folderInput?.files.length) {
      const dt = new DataTransfer();
      Array.from(folderInput.files).forEach(f => dt.items.add(f));
      mainInput.files = dt.files;
    }
  }
  const files = document.getElementById("dz-mixed-input").files;
  const listEl  = document.getElementById("dz-mixed-list");
  const bodyEl  = document.getElementById("dz-mixed-list-body");
  const nameEl  = document.getElementById("dz-mixed-filename");

  if (!files.length) {
    nameEl.textContent = i18n("dicomize.mixed_no_files");
    listEl.style.display = "none";
    return;
  }
  nameEl.textContent = i18n("dicomize.mixed_files_selected", {n: files.length});
  listEl.style.display = "";

  const typeBadge = {
    image:   "<span style='background:#d4edda;color:#155724;border-radius:3px;padding:1px 5px;font-size:11px'>Image</span>",
    video:   "<span style='background:#cce5ff;color:#004085;border-radius:3px;padding:1px 5px;font-size:11px'>Video</span>",
    pdf:     "<span style='background:#fff3cd;color:#856404;border-radius:3px;padding:1px 5px;font-size:11px'>PDF</span>",
    unknown: "<span style='background:#f8d7da;color:#721c24;border-radius:3px;padding:1px 5px;font-size:11px'>?</span>",
  };

  bodyEl.innerHTML = Array.from(files).map((f, idx) => {
    const t = _dzDetectType(f.name);
    return `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:4px 8px; max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</td>
      <td style="padding:4px 8px">${typeBadge[t]}</td>
      <td style="padding:4px 8px; color:#888">${_dzFmtSize(f.size)}</td>
      <td style="padding:4px 8px">
        <button class="btn" style="padding:2px 8px;font-size:11px" onclick="dzPreviewFile(${idx})"
                data-i18n="dicomize.preview_btn">Preview</button>
      </td>
    </tr>`;
  }).join("");
}

function _dzMixedVideoFormat() {
  const checked = document.querySelector('input[name="dz-mixed-video-format"]:checked');
  return checked ? checked.value : "encapsulated";
}

async function doDicomizeMixed(action) {
  const input = document.getElementById("dz-mixed-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No files selected."}), "warn");
    return;
  }
  if (action === "store") {
    _dzToggleAE("mixed", true);
    dzLoadPresets();
    return;
  }
  appendLog("log-dicomize", now(), i18n("dicomize.converting"));
  const fmt = _dzMixedVideoFormat();
  const fd = _dzGetMetadata("dz-mixed-series-desc");
  Array.from(input.files).forEach(f => fd.append("files", f));
  fd.append("video_format", fmt);
  if (document.getElementById("dz-mixed-group-series")?.checked) fd.append("group_series", "1");
  if (fmt === "multiframe") {
    const fps = document.getElementById("dz-mixed-fps")?.value;
    if (fps) fd.append("fps_limit", fps);
  }
  try {
    const xhr  = await _dzUpload("/api/dicomize/mixed", fd, "dz-mixed-progress", "dz-mixed-progress-bar", { binary: true });
    const ct   = xhr.getResponseHeader("Content-Type") || "";
    const cd   = xhr.getResponseHeader("Content-Disposition") || "";
    const name = cd.match(/filename="?([^"]+)"?/)?.[1] || (ct.includes("zip") ? "mixed_dicom.zip" : "output.dcm");
    _dzDownload(new Blob([xhr.response], { type: ct || "application/octet-stream" }), name);
    appendLog("log-dicomize", now(), i18n("dicomize.download_ok"), "ok");
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

async function doDicomizeMixedStore() {
  const input = document.getElementById("dz-mixed-input");
  if (!input.files.length) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: "No files selected."}), "warn");
    return;
  }
  const ae = _dzGetAE("mixed");
  const studyUid = document.getElementById("dz-study-uid")?.value.trim();
  if (!await dzCheckDuplicate(studyUid, ae)) return;
  appendLog("log-dicomize", now(), i18n("dicomize.storing"));
  const fmt = _dzMixedVideoFormat();
  const fd = _dzGetMetadata("dz-mixed-series-desc");
  Array.from(input.files).forEach(f => fd.append("files", f));
  fd.append("video_format", fmt);
  if (document.getElementById("dz-mixed-group-series")?.checked) fd.append("group_series", "1");
  if (fmt === "multiframe") {
    const fps = document.getElementById("dz-mixed-fps")?.value;
    if (fps) fd.append("fps_limit", fps);
  }
  fd.append("ae_title", ae.ae_title);
  fd.append("ae_host",  ae.ae_host);
  fd.append("ae_port",  ae.ae_port);
  try {
    const xhr  = await _dzUpload("/api/dicomize/mixed/store", fd, "dz-mixed-progress", "dz-mixed-progress-bar");
    const data = JSON.parse(xhr.responseText);
    if (data.ok) {
      appendLog("log-dicomize", now(), i18n("dicomize.store_ok", {message: data.message}), "ok");
    } else {
      appendLog("log-dicomize", now(), i18n("dicomize.error", {message: data.error || data.message}), "err");
    }
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

// ── Source-file preview modal ─────────────────────────────────────

let _dzPreviewUrl = null;

function dzPreviewFile(idx) {
  const input = document.getElementById("dz-mixed-input");
  const file  = input?.files[idx];
  if (!file) return;

  if (_dzPreviewUrl) { URL.revokeObjectURL(_dzPreviewUrl); _dzPreviewUrl = null; }
  _dzPreviewUrl = URL.createObjectURL(file);

  const content = document.getElementById("dz-preview-content");
  const t = _dzDetectType(file.name);

  if (t === "image") {
    content.innerHTML = `<img src="${_dzPreviewUrl}" style="max-width:100%;max-height:73vh;object-fit:contain;border-radius:4px" alt="${escapeHtml(file.name)}">`;
  } else if (t === "video") {
    content.innerHTML = `<video src="${_dzPreviewUrl}" controls style="max-width:100%;max-height:73vh;border-radius:4px"></video>`;
  } else if (t === "pdf") {
    content.innerHTML = `<iframe src="${_dzPreviewUrl}" style="width:100%;height:73vh;border:none;border-radius:4px" title="${escapeHtml(file.name)}"></iframe>`;
  } else {
    content.innerHTML = `<p style="color:#888">${escapeHtml(i18n("dicomize.preview_unsupported"))}</p>`;
  }

  document.getElementById("dz-preview-title").textContent = file.name;
  document.getElementById("dz-preview-modal").classList.add("open");
}

function closeDzPreview() {
  document.getElementById("dz-preview-modal").classList.remove("open");
  document.getElementById("dz-preview-content").innerHTML = "";
  if (_dzPreviewUrl) { URL.revokeObjectURL(_dzPreviewUrl); _dzPreviewUrl = null; }
}

// ── ORU IAN → ORM workflow ─────────────────────────────────────────

let _dzOruIanOrm = null;   // Last ORM message received via HL7 listener


async function _dzOruIanPopulateTemplates() {
  const sel = document.getElementById("dz-oruian-template");
  try {
    const res = await fetch("/api/hl7/templates");
    const list = await res.json();
    const prev = sel.value;
    sel.innerHTML = `<option value="">${escapeHtml(i18n("dicomize.oruian_template_placeholder"))}</option>`;
    list.forEach(t => {
      const opt = document.createElement("option");
      opt.value = t.filename;
      opt.textContent = t.name;
      sel.appendChild(opt);
    });
    sel.value = prev;
  } catch (e) { /* non-critical */ }
}

async function dzOruIanLoadTemplate() {
  const filename = document.getElementById("dz-oruian-template").value;
  if (!filename) return;
  try {
    const res  = await fetch(`/api/hl7/templates/${encodeURIComponent(filename)}`);
    const tmpl = await res.json();
    document.getElementById("dz-oruian-msg").value = (tmpl.body || "").replace(/\r/g, "\n");
    document.getElementById("dz-oruian-preview").style.display = "none";
  } catch (e) { /* non-critical */ }
}

function dzOruIanInsert(placeholder) {
  const ta = document.getElementById("dz-oruian-msg");
  const s  = ta.selectionStart, e = ta.selectionEnd;
  ta.value = ta.value.slice(0, s) + placeholder + ta.value.slice(e);
  ta.selectionStart = ta.selectionEnd = s + placeholder.length;
  ta.focus();
}

function _dzOruIanFill(body) {
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");
  const dt  = `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const msgId = "MSG" + dt + Math.random().toString(36).slice(2,6).toUpperCase();
  const get = id => (document.getElementById(id)?.value || "").trim();
  return body
    .replace(/\{\{patient_name\}\}/g,      get("dz-patient-name"))
    .replace(/\{\{patient_id\}\}/g,        get("dz-patient-id"))
    .replace(/\{\{patient_dob\}\}/g,       dateToDisom(get("dz-patient-dob")))
    .replace(/\{\{patient_sex\}\}/g,       get("dz-patient-sex"))
    .replace(/\{\{accession_number\}\}/g,  get("dz-accession"))
    .replace(/\{\{study_uid\}\}/g,         get("dz-study-uid"))
    .replace(/\{\{study_date\}\}/g,        dateToDisom(get("dz-study-date")) || dt.slice(0,8))
    .replace(/\{\{study_time\}\}/g,        timeToDisom(get("dz-study-time")) || dt.slice(8,14))
    .replace(/\{\{study_description\}\}/g, get("dz-study-desc"))
    .replace(/\{\{institution_name\}\}/g,  get("dz-institution"))
    .replace(/\{\{datetime\}\}/g,          dt)
    .replace(/\{\{date\}\}/g,              dt.slice(0,8))
    .replace(/\{\{time\}\}/g,              dt.slice(8,14))
    .replace(/\{\{msg_id\}\}/g,            msgId);
}

function dzOruIanPreview() {
  const body   = document.getElementById("dz-oruian-msg").value;
  const filled = _dzOruIanFill(body);
  const pre    = document.getElementById("dz-oruian-preview");
  pre.textContent = filled.replace(/\r/g, "\n");
  pre.style.display = "";
}

async function dzOruIanSend() {
  const body = document.getElementById("dz-oruian-msg").value.trim();
  if (!body) {
    appendLog("log-dicomize", now(), i18n("dicomize.oruian_no_msg"), "warn");
    return;
  }
  const host = document.getElementById("dz-oruian-host").value.trim();
  const port = document.getElementById("dz-oruian-port").value.trim();
  if (!host || !port) {
    appendLog("log-dicomize", now(), i18n("dicomize.oruian_no_host"), "warn");
    return;
  }
  const filled  = _dzOruIanFill(body);
  const statusEl = document.getElementById("dz-oruian-status");
  statusEl.textContent = i18n("dicomize.oruian_sending");
  statusEl.style.color = "#888";
  appendLog("log-dicomize", now(), i18n("dicomize.oruian_sending"));

  try {
    const res  = await fetch("/api/hl7/send", {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body:    JSON.stringify({ host, port: parseInt(port, 10), message: filled }),
    });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = i18n("dicomize.oruian_ack_ok");
      statusEl.style.color = "var(--ok, green)";
      appendLog("log-dicomize", now(), i18n("dicomize.oruian_ack_ok"), "ok");
    } else {
      statusEl.textContent = `${i18n("dicomize.oruian_ack_fail")}: ${data.response}`;
      statusEl.style.color = "var(--err, red)";
      appendLog("log-dicomize", now(), `${i18n("dicomize.oruian_ack_fail")}: ${data.response}`, "err");
    }
  } catch (e) {
    statusEl.textContent = String(e);
    statusEl.style.color = "var(--err, red)";
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

async function dzOruIanFillFromOrm() {
  if (!_dzOruIanOrm) return;
  try {
    const res  = await fetch("/api/dicomize/parse-orm", {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body:    JSON.stringify({ message: _dzOruIanOrm }),
    });
    const data = await res.json();
    if (!data.ok) {
      appendLog("log-dicomize", now(), i18n("dicomize.error", {message: data.error}), "err");
      return;
    }
    const f = data.fields || {};
    if (f.patient_name)      document.getElementById("dz-patient-name").value = f.patient_name;
    if (f.patient_id)        document.getElementById("dz-patient-id").value   = f.patient_id;
    if (f.patient_dob)       document.getElementById("dz-patient-dob").value  = f.patient_dob;
    if (f.patient_sex)       document.getElementById("dz-patient-sex").value  = f.patient_sex;
    if (f.accession_number)  document.getElementById("dz-accession").value    = f.accession_number;
    if (f.study_description) document.getElementById("dz-study-desc").value   = f.study_description;
    if (f.study_date)        document.getElementById("dz-study-date").value   = f.study_date;
    if (f.study_time)        document.getElementById("dz-study-time").value   = f.study_time;
    if (f.institution)       document.getElementById("dz-institution").value  = f.institution;
    // Expand patient section if collapsed
    const body  = document.getElementById("dicomize-patient-body");
    const arrow = document.getElementById("dicomize-patient-arrow");
    if (body.style.display === "none") { body.style.display = ""; if (arrow) arrow.textContent = "▼"; }
    appendLog("log-dicomize", now(),
      i18n("dicomize.oruian_orm_filled", {name: f.patient_name || "?", acc: f.accession_number || "?"}), "ok");
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

async function dzOruIanSaveTemplate() {
  const body = document.getElementById("dz-oruian-msg").value.trim();
  if (!body) return;
  const name = prompt(i18n("dicomize.oruian_save_name_prompt") || "Template name:");
  if (!name) return;
  const desc = prompt(i18n("dicomize.oruian_save_desc_prompt") || "Description (optional):") || "";
  try {
    const res  = await fetch("/api/hl7/templates/save", {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body:    JSON.stringify({ name, description: desc, body }),
    });
    const data = await res.json();
    if (data.ok) {
      appendLog("log-dicomize", now(), i18n("dicomize.oruian_saved", {name}), "ok");
      _dzOruIanPopulateTemplates();
    } else {
      appendLog("log-dicomize", now(), i18n("dicomize.error", {message: data.error}), "err");
    }
  } catch (e) {
    appendLog("log-dicomize", now(), i18n("dicomize.error", {message: String(e)}), "err");
  }
}

// ── Worklist → DICOMize ────────────────────────────────────────────
let _dzWlResults = [];

function openDzWorklistModal() {
  dzWlLoadPresets();
  document.getElementById("dz-wl-modal").classList.add("open");
}

function closeDzWorklistModal() {
  document.getElementById("dz-wl-modal").classList.remove("open");
}

function dzWlLoadPresets() {
  const sel         = document.getElementById("dz-wl-ae-preset");
  const sysPresets  = appConfig.remote_aes   || [];
  const userPresets = userSettings.remote_aes || [];
  const prev        = sel.value;
  sel.innerHTML = '<option value=""></option>';
  if (sysPresets.length > 0) {
    const grp = document.createElement("optgroup");
    grp.label = i18n("settings.system_presets");
    sysPresets.forEach(ae => {
      const opt = document.createElement("option");
      opt.value = "sys:" + ae.name; opt.textContent = ae.name;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  }
  if (userPresets.length > 0) {
    const grp = document.createElement("optgroup");
    grp.label = i18n("settings.user_presets");
    userPresets.forEach(ae => {
      const opt = document.createElement("option");
      opt.value = "usr:" + ae.name; opt.textContent = ae.name;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  }
  sel.value = prev;
}

function dzWlFillAE() {
  const val = document.getElementById("dz-wl-ae-preset").value;
  if (!val) return;
  let ae;
  if (val.startsWith("usr:")) {
    ae = (userSettings.remote_aes || []).find(a => a.name === val.slice(4));
  } else {
    const name = val.startsWith("sys:") ? val.slice(4) : val;
    ae = (appConfig.remote_aes || []).find(a => a.name === name);
  }
  if (!ae) return;
  document.getElementById("dz-wl-host").value = ae.host      || "";
  document.getElementById("dz-wl-port").value = ae.port      || "";
  document.getElementById("dz-wl-aet").value  = ae.ae_title  || "";
}

async function dzWlQuery() {
  const host  = document.getElementById("dz-wl-host").value.trim();
  const port  = document.getElementById("dz-wl-port").value.trim();
  const aet   = document.getElementById("dz-wl-aet").value.trim();
  const pname = document.getElementById("dz-wl-filter-name").value.trim() || "*";
  const pid   = document.getElementById("dz-wl-filter-id").value.trim();
  const date  = dateToDisom(document.getElementById("dz-wl-filter-date").value.trim());
  const mod   = document.getElementById("dz-wl-filter-mod").value.trim();
  const statusEl = document.getElementById("dz-wl-status");
  const tbody    = document.getElementById("dz-wl-results-body");

  if (!host || !port || !aet) {
    statusEl.textContent = i18n("dicomize.wl_need_ae");
    return;
  }
  statusEl.textContent = i18n("dicomize.wl_querying");
  tbody.innerHTML = `<tr><td colspan="6" style="color:#888;text-align:center">${escapeHtml(i18n("dicomize.wl_querying"))}</td></tr>`;

  try {
    const res  = await fetch("/api/dicom/dmwl", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        host, port: parseInt(port, 10), ae_title: aet,
        patient_name: pname, patient_id: pid,
        accession: "", modality: mod, study_date: date, station_aet: "",
      }),
    });
    const data = await res.json();
    _dzWlResults = data.results || [];
    statusEl.textContent = data.ok
      ? i18n("dicomize.wl_found", {n: _dzWlResults.length})
      : `Error: ${escapeHtml(data.message || "")}`;

    if (!_dzWlResults.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="color:#aaa;text-align:center;padding:20px">${escapeHtml(i18n("dicomize.wl_no_results"))}</td></tr>`;
      return;
    }
    tbody.innerHTML = _dzWlResults.map((r, i) =>
      `<tr style="cursor:pointer" onclick="dzWlSelectItem(${i})">
        <td>${escapeHtml(r.PatientName  || "")}</td>
        <td>${escapeHtml(r.PatientID    || "")}</td>
        <td>${escapeHtml(r.Accession    || "")}</td>
        <td>${escapeHtml(r.Modality     || "")}</td>
        <td>${escapeHtml(r.ScheduledDate|| "")}</td>
        <td>${escapeHtml(r.Procedure    || "")}</td>
      </tr>`
    ).join("");
  } catch (e) {
    statusEl.textContent = `Error: ${e}`;
    tbody.innerHTML = "";
  }
}

function dzWlSelectItem(idx) {
  const r = _dzWlResults[idx];
  if (!r) return;

  document.getElementById("dz-patient-name").value = r.PatientName      || "";
  document.getElementById("dz-patient-id").value   = r.PatientID        || "";
  document.getElementById("dz-patient-dob").value  = dicomDateToInput(r.PatientBirthDate || "");
  document.getElementById("dz-patient-sex").value  = r.PatientSex       || "";
  document.getElementById("dz-study-date").value   = dicomDateToInput(r.ScheduledDate    || "");
  document.getElementById("dz-study-desc").value   = r.Procedure        || "";
  document.getElementById("dz-accession").value    = r.Accession        || "";
  document.getElementById("dz-institution").value  = r.InstitutionName  || "";
  if (r.StudyInstanceUID) {
    document.getElementById("dz-study-uid").value = r.StudyInstanceUID;
  }

  // Expand patient card if collapsed
  const body  = document.getElementById("dicomize-patient-body");
  const arrow = document.getElementById("dicomize-patient-arrow");
  if (body.style.display === "none") {
    body.style.display = "";
    if (arrow) arrow.textContent = "▼";
  }

  closeDzWorklistModal();
  appendLog("log-dicomize", now(),
    `Worklist: ${r.PatientName || "?"} [${r.PatientID || "?"}]  —  ${r.Procedure || ""}`, "ok");
}

// Trigger a browser download from a Blob
function _dzDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href    = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

