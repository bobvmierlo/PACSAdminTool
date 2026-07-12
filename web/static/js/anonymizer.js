// anonymizer.js — Anonymizer tab incl. profile manager
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// DICOM Anonymizer
// ─────────────────────────────────────────────────────────────────

let _anonFiles = [];

function anonFilesSelected() {
  const input = document.getElementById("anon-file-input");
  _anonFiles  = Array.from(input.files || []);
  renderAnonList();
}

function anonClearFiles() {
  _anonFiles = [];
  document.getElementById("anon-file-input").value = "";
  renderAnonList();
}

function renderAnonList() {
  const box = document.getElementById("anon-filelist");
  const cnt = document.getElementById("anon-count");
  cnt.textContent = `${_anonFiles.length} file(s) selected`;
  box.innerHTML = _anonFiles.map(f => f.name).join("<br>");
}

// ── Anonymizer: Retrieve from PACS helpers ───────────────────────

let _anonCFindResults = [];
let _anonCFindSelectedIdx = -1;

function _populateAnonCFindDropdown() {
  const sel = document.getElementById("anon-cfind-ae-select");
  if (!sel) return;
  const aes = appConfig.remote_aes || [];
  sel.innerHTML = '<option value="">Select preset…</option>';
  aes.forEach((ae, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${ae.name || ae.ae_title} (${ae.ae_title}@${ae.host}:${ae.port})`;
    sel.appendChild(opt);
  });
}

function anonCFindAEChanged() {
  const sel = document.getElementById("anon-cfind-ae-select");
  const idx = parseInt(sel.value);
  if (isNaN(idx)) return;
  const ae = (appConfig.remote_aes || [])[idx];
  if (!ae) return;
  document.getElementById("anon-cfind-aet").value  = ae.ae_title || "";
  document.getElementById("anon-cfind-host").value = ae.host     || "";
  document.getElementById("anon-cfind-port").value = ae.port     || "";
}

async function anonCFindSearch() {
  const aet    = document.getElementById("anon-cfind-aet").value.trim();
  const host   = document.getElementById("anon-cfind-host").value.trim();
  const port   = document.getElementById("anon-cfind-port").value.trim();
  const name   = document.getElementById("anon-cfind-name").value.trim() || "*";
  const pid    = document.getElementById("anon-cfind-pid").value.trim();
  const date   = dateToDisom(document.getElementById("anon-cfind-date").value.trim());
  const status = document.getElementById("anon-cfind-status");
  const tbody  = document.getElementById("anon-cfind-tbody");
  const resDiv = document.getElementById("anon-cfind-results");
  const btn    = document.getElementById("anon-cfind-retrieve-btn");

  if (!host || !port || !aet) { status.textContent = "Enter AE Title, Host and Port first."; return; }
  status.textContent = "Searching…";
  resDiv.style.display = "none";
  btn.disabled = true;
  _anonCFindResults = [];
  _anonCFindSelectedIdx = -1;

  try {
    const res  = await fetch("/api/dicom/find", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ ae_title: aet, host, port: parseInt(port, 10),
        patient_name: name, patient_id: pid, study_date: date,
        query_level: "STUDY", query_model: "S" }),
    });
    const data = await res.json();
    if (!data.ok) { status.textContent = `Error: ${data.error || data.message || "Unknown error"}`; return; }
    _anonCFindResults = data.results || [];
    status.textContent = `${_anonCFindResults.length} study/studies found. Click a row to select.`;
    if (!_anonCFindResults.length) { resDiv.style.display = "none"; return; }
    tbody.innerHTML = _anonCFindResults.map((r, i) => `
      <tr data-idx="${i}" style="cursor:pointer; border-top:1px solid var(--border)"
          onclick="anonCFindSelect(${i})">
        <td style="padding:4px 8px">${escapeHtml(r.PatientName || "")}</td>
        <td style="padding:4px 8px">${escapeHtml(r.PatientID   || "")}</td>
        <td style="padding:4px 8px">${escapeHtml(r.StudyDate   || "")}</td>
        <td style="padding:4px 8px">${escapeHtml(r.Modality    || "")}</td>
        <td style="padding:4px 8px">${escapeHtml(r.Description || "")}</td>
      </tr>`).join("");
    resDiv.style.display = "";
  } catch (e) {
    status.textContent = `Error: ${e}`;
  }
}

function anonCFindSelect(idx) {
  _anonCFindSelectedIdx = idx;
  document.querySelectorAll("#anon-cfind-tbody tr").forEach((tr, i) => {
    tr.style.background = i === idx ? "var(--primary-light,#dbeafe)" : "";
    tr.style.fontWeight  = i === idx ? "600" : "";
  });
  document.getElementById("anon-cfind-retrieve-btn").disabled = false;
  const r = _anonCFindResults[idx];
  document.getElementById("anon-cfind-status").textContent =
    `Selected: ${r.PatientName || "?"} — ${r.Description || r.StudyDate || ""}`;
}

async function anonCFindRetrieve() {
  const r = _anonCFindResults[_anonCFindSelectedIdx];
  if (!r) { toast("Select a study first.", "warn"); return; }

  // Ensure the local SCP is running before C-MOVE
  const ready = await _ensureScpRunningForMove();
  if (!ready) return;

  const aet    = document.getElementById("anon-cfind-aet").value.trim();
  const host   = document.getElementById("anon-cfind-host").value.trim();
  const port   = document.getElementById("anon-cfind-port").value.trim();
  const dest   = (appConfig.local_ae || {}).ae_title || "PACSADMIN";
  const model  = "S";
  const status = document.getElementById("anon-cfind-retrieve-status");
  const btn    = document.getElementById("anon-cfind-retrieve-btn");

  btn.disabled = true;
  status.textContent = `Sending C-MOVE to local SCP (${dest})…`;

  try {
    const moveRes  = await fetch("/api/dicom/move", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ ae_title: aet, host, port: parseInt(port, 10),
        study_uid: r.StudyUID, move_dest: dest, query_model: model }),
    });
    const moveData = await moveRes.json();
    if (!moveData.ok) {
      status.textContent = `C-MOVE error: ${moveData.error || moveData.message}`;
      btn.disabled = false; return;
    }

    status.textContent = "C-MOVE started — waiting for files…";

    // Poll the SCP every 2 s for up to 60 s until the study appears
    const studyUid = r.StudyUID;
    let attempts = 0;
    const poll = async () => {
      attempts++;
      const scpRes  = await fetch("/api/scp/studies");
      const scpData = await scpRes.json();
      const study   = (scpData.studies || []).find(s => s.uid === studyUid);
      if (study) {
        // Load all series files as blobs into _anonFiles
        const allFiles = [];
        for (const ser of study.series) {
          const lRes  = await fetch(`/api/scp/series/list?study=${encodeURIComponent(studyUid)}&series=${encodeURIComponent(ser.uid)}`);
          const lData = await lRes.json();
          if (!lData.ok) continue;
          for (const urlStr of (lData.urls || [])) {
            const url  = new URL(urlStr, location.href);
            const path = url.searchParams.get("path") || urlStr;
            const fRes = await fetch(`/api/scp/files/raw?path=${encodeURIComponent(path)}`);
            if (!fRes.ok) continue;
            const blob = await fRes.blob();
            allFiles.push(new File([blob], path.split("/").pop() || "file.dcm", { type: "application/dicom" }));
          }
        }
        _anonFiles = allFiles;
        renderAnonList();
        document.getElementById("anon-retrieve-panel").removeAttribute("open");
        status.textContent = `${allFiles.length} file(s) loaded.`;
        btn.disabled = false;
        toast(`${allFiles.length} file(s) loaded into Anonymizer`, "ok");
      } else if (attempts < 30) {
        status.textContent = `Waiting… (${attempts * 2}s)`;
        setTimeout(poll, 2000);
      } else {
        status.textContent = "Timeout — study did not arrive within 60 s. Check DICOM Receiver.";
        btn.disabled = false;
      }
    };
    setTimeout(poll, 2000);
  } catch (e) {
    status.textContent = `Error: ${e}`;
    btn.disabled = false;
  }
}

// ── Anonymizer: "Send to PACS" AE helpers ────────────────────────
function _populateAnonAEDropdown() {
  const sel = document.getElementById("anon-ae-select");
  const aes = (appConfig.remote_aes || []);
  sel.innerHTML = '<option value="">Select a preset…</option>';
  aes.forEach((ae, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${ae.name || ae.ae_title} (${ae.ae_title}@${ae.host}:${ae.port})`;
    sel.appendChild(opt);
  });
}

function anonAEChanged() {
  const sel = document.getElementById("anon-ae-select");
  const idx = parseInt(sel.value);
  if (isNaN(idx)) return;
  const ae = (appConfig.remote_aes || [])[idx];
  if (!ae) return;
  document.getElementById("anon-ae-title").value = ae.ae_title || "";
  document.getElementById("anon-ae-host").value  = ae.host     || "";
  document.getElementById("anon-ae-port").value  = ae.port     || "";
}

function anonProfileChanged() {
  // Nothing dynamic to do here; custom_tags are embedded at send time
}

function _buildAnonFD() {
  const profile = document.getElementById("anon-profile").value;
  const fd = new FormData();
  _anonFiles.forEach(f => fd.append("files[]", f));
  fd.append("profile",        profile);
  fd.append("patient_name",   document.getElementById("anon-patient-name").value);
  fd.append("patient_id",     document.getElementById("anon-patient-id").value);
  fd.append("remove_private", document.getElementById("anon-remove-private").checked ? "1" : "0");
  fd.append("new_uids",       document.getElementById("anon-new-uids").checked ? "1" : "0");
  if (profile === "custom") {
    fd.append("custom_tags", JSON.stringify(_anonCustomTags));
  }
  return fd;
}

async function doAnonymize() {
  if (_anonFiles.length === 0) { toast("Add at least one DICOM file first.", "warn"); return; }
  const status = document.getElementById("anon-status");
  status.textContent = "Anonymising…";
  const fd = _buildAnonFD();
  try {
    const res = await fetch("/api/dicom/anonymize", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      status.textContent = "Error: " + (err.error || res.statusText);
      return;
    }
    const blob = await res.blob();
    const cd   = res.headers.get("Content-Disposition") || "";
    const fnM  = cd.match(/filename="?([^";\n]+)"?/);
    const fn   = fnM ? fnM[1] : "anonymised.zip";
    const a    = document.createElement("a");
    a.href     = URL.createObjectURL(blob);
    a.download = fn;
    a.click();
    URL.revokeObjectURL(a.href);
    const warnCount = parseInt(res.headers.get("X-Anonymize-Warnings") || "0", 10);
    if (warnCount > 0) {
      status.textContent = `Done — downloaded ${fn}. ⚠ ${warnCount} warning(s) — see ANONYMIZATION_WARNINGS.txt in the ZIP (possible burned-in PHI).`;
      toast(`${warnCount} file(s) may contain burned-in PHI — check ANONYMIZATION_WARNINGS.txt in the ZIP.`, "warn");
    } else {
      status.textContent = `Done — downloaded ${fn}`;
    }
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

async function doAnonymizeAndSend() {
  if (_anonFiles.length === 0) { toast("Add at least one DICOM file first.", "warn"); return; }
  const aeTitle = document.getElementById("anon-ae-title").value.trim();
  const host    = document.getElementById("anon-ae-host").value.trim();
  const portStr = document.getElementById("anon-ae-port").value.trim();
  const port    = parsePort(portStr);
  if (!aeTitle || !host || port === null) {
    toast("Fill in AE Title, Host, and a valid Port before sending.", "warn"); return;
  }
  const status = document.getElementById("anon-status");
  status.textContent = "Anonymising and sending…";
  // Single request with all files so that UID remapping stays consistent
  // across the batch (all files of one study get the same new StudyInstanceUID).
  const fd = _buildAnonFD();
  fd.append("ae_title", aeTitle);
  fd.append("host",     host);
  fd.append("port",     port);
  try {
    const res = await fetch("/api/dicom/anonymize-and-store", { method: "POST", body: fd });
    const d   = await res.json().catch(() => ({}));
    let text  = d.message || (d.ok ? "Done." : "Error: " + (d.error || res.statusText));
    if (d.warnings && d.warnings.length) {
      text += ` ⚠ ${d.warnings.length} warning(s) — possible burned-in PHI.`;
      toast(`${d.warnings.length} file(s) may contain burned-in PHI — visual review recommended.`, "warn");
    }
    status.textContent = text;
  } catch (e) {
    status.textContent = "Error: " + e;
  }
}

// ── Anonymisation Profile Manager ─────────────────────────────────

let _anonCustomProfiles = {};  // loaded from server
let _anonCustomTags     = [];  // tags for the currently selected custom profile
let _apmEditingKey      = null; // name of profile being edited

// List of common PHI tags grouped by category, used in the profile editor
const _APM_KNOWN_TAGS = [
  { group: "Patient Identity", tags: [
    { tag: "(0010,0010)", label: "Patient Name" },
    { tag: "(0010,0020)", label: "Patient ID" },
    { tag: "(0010,0030)", label: "Patient Birth Date" },
    { tag: "(0010,0040)", label: "Patient Sex" },
    { tag: "(0010,1000)", label: "Other Patient IDs" },
    { tag: "(0010,1010)", label: "Patient Age" },
    { tag: "(0010,1020)", label: "Patient Size" },
    { tag: "(0010,1030)", label: "Patient Weight" },
    { tag: "(0010,1040)", label: "Patient Telephone Numbers" },
    { tag: "(0010,2160)", label: "Ethnic Group" },
    { tag: "(0010,21B0)", label: "Additional Patient History" },
  ]},
  { group: "Referring / Operators", tags: [
    { tag: "(0008,0090)", label: "Referring Physician Name" },
    { tag: "(0008,1048)", label: "Physician(s) of Record" },
    { tag: "(0008,1070)", label: "Operators Name" },
  ]},
  { group: "Institution", tags: [
    { tag: "(0008,0080)", label: "Institution Name" },
    { tag: "(0008,0081)", label: "Institution Address" },
    { tag: "(0008,1010)", label: "Station Name" },
  ]},
  { group: "Study & Order Info", tags: [
    { tag: "(0008,0050)", label: "Accession Number" },
    { tag: "(0020,0010)", label: "Study ID" },
    { tag: "(0032,1032)", label: "Requesting Physician" },
    { tag: "(0032,1060)", label: "Requested Procedure Description" },
    { tag: "(0032,1070)", label: "Requested Contrast Agent" },
  ]},
  { group: "Descriptions", tags: [
    { tag: "(0008,1030)", label: "Study Description" },
    { tag: "(0008,103E)", label: "Series Description" },
    { tag: "(0018,1030)", label: "Protocol Name" },
  ]},
  { group: "Scheduled Procedure", tags: [
    { tag: "(0040,0006)", label: "Scheduled Performing Physician Name" },
    { tag: "(0040,0007)", label: "Scheduled Procedure Step Description" },
    { tag: "(0040,0009)", label: "Scheduled Procedure Step ID" },
  ]},
];

async function _loadAnonProfilesFromServer() {
  try {
    const res  = await fetch("/api/dicom/anon_profiles");
    const data = await res.json();
    if (data.ok) _anonCustomProfiles = data.profiles || {};
  } catch { _anonCustomProfiles = {}; }
  _rebuildAnonProfileDropdown();
}

function _rebuildAnonProfileDropdown() {
  const sel = document.getElementById("anon-profile");
  // Remove any custom options (keep basic and full)
  Array.from(sel.options).forEach(o => {
    if (o.value !== "basic" && o.value !== "full") sel.removeChild(o);
  });
  const names = Object.keys(_anonCustomProfiles);
  if (names.length) {
    const sep = document.createElement("option");
    sep.disabled = true;
    sep.textContent = "── Custom Profiles ──";
    sel.appendChild(sep);
    names.forEach(n => {
      const opt = document.createElement("option");
      opt.value = "custom:" + n;
      opt.textContent = n;
      sel.appendChild(opt);
    });
  }
  // Keep copy-from dropdown in sync if modal is open
  if (document.getElementById("anon-profile-modal").style.display !== "none") {
    _updateApmCopyFromOptions();
  }
}

// JS tag sets matching Python _ANON_BASIC and _ANON_FULL for copy-from
const _APM_BASIC_TAGS = [
  "(0008,0050)","(0008,0080)","(0008,0081)","(0008,0090)","(0008,1010)",
  "(0008,1048)","(0008,1070)","(0010,0030)","(0010,0040)","(0010,1000)",
  "(0010,1010)","(0010,1020)","(0010,1030)","(0010,1040)","(0010,2160)",
  "(0010,21B0)","(0020,0010)","(0032,1032)","(0032,1060)",
];
const _APM_FULL_TAGS = [..._APM_BASIC_TAGS,
  "(0008,1030)","(0008,103E)","(0018,1030)","(0032,1070)",
  "(0040,0006)","(0040,0007)","(0040,0009)",
];

// Tracks checked tags in the editor (source of truth while editing)
let _apmCurrentChecked = new Set();

function _apmShowEditor() {
  document.getElementById("anon-profile-editor").style.display = "flex";
  document.getElementById("anon-profile-placeholder").style.display = "none";
}

function _apmHideEditor() {
  document.getElementById("anon-profile-editor").style.display = "none";
  document.getElementById("anon-profile-placeholder").style.display = "flex";
}

function openAnonProfileManager() {
  _apmEditingKey = null;
  _apmCurrentChecked = new Set();
  renderApmProfileList();
  _updateApmCopyFromOptions();
  _apmHideEditor();
  document.getElementById("anon-profile-modal").style.display = "flex";
}

function closeAnonProfileManager() {
  document.getElementById("anon-profile-modal").style.display = "none";
}

function _updateApmCopyFromOptions() {
  const sel = document.getElementById("apm-copy-from");
  // Remove any custom profile options (keep first 4: blank, basic, full, sep)
  while (sel.options.length > 4) sel.remove(4);
  Object.keys(_anonCustomProfiles).forEach(n => {
    const opt = document.createElement("option");
    opt.value = "custom:" + n;
    opt.textContent = n;
    sel.appendChild(opt);
  });
}

function renderApmProfileList() {
  const list = document.getElementById("anon-profile-list");
  list.innerHTML = "";
  const names = Object.keys(_anonCustomProfiles);
  if (!names.length) {
    list.innerHTML = `<div style="color:#9ca3af;font-size:12px;padding:4px 2px">${i18n("anonymizer.mgr_no_profiles")}</div>`;
    return;
  }
  names.forEach(n => {
    const btn = document.createElement("button");
    btn.style.cssText = "text-align:left; padding:6px 8px; border-radius:4px; border:1px solid transparent; background:none; cursor:pointer; font-size:12px; width:100%";
    btn.textContent = n;
    if (n === _apmEditingKey) {
      btn.style.background = "#eff6ff";
      btn.style.borderColor = "#bfdbfe";
      btn.style.color = "#1d4ed8";
    }
    btn.onmouseover = () => { if (n !== _apmEditingKey) btn.style.background = "#f9fafb"; };
    btn.onmouseout  = () => { if (n !== _apmEditingKey) btn.style.background = ""; };
    btn.onclick = () => apmEditProfile(n);
    list.appendChild(btn);
  });
}

function apmEditProfile(name) {
  _apmEditingKey = name;
  const p = _anonCustomProfiles[name] || { name, tags: [] };
  _apmCurrentChecked = new Set(p.tags || []);
  document.getElementById("apm-name").value = p.name || name;
  document.getElementById("apm-delete-btn").style.display = "";
  document.getElementById("apm-copy-from").value = "";
  document.getElementById("apm-tag-filter").value = "";
  document.getElementById("apm-status").textContent = "";
  _apmShowEditor();
  renderApmTagList();
  renderApmProfileList();
}

function anonProfileNew() {
  _apmEditingKey = null;
  _apmCurrentChecked = new Set();
  document.getElementById("apm-name").value = "";
  document.getElementById("apm-delete-btn").style.display = "none";
  document.getElementById("apm-copy-from").value = "";
  document.getElementById("apm-tag-filter").value = "";
  document.getElementById("apm-status").textContent = "";
  _apmShowEditor();
  renderApmTagList();
}

function anonProfileCopyBuiltin(which) {
  // Open a new profile editor pre-populated from a built-in profile
  anonProfileNew();
  _apmCurrentChecked = new Set(which === "full" ? _APM_FULL_TAGS : _APM_BASIC_TAGS);
  document.getElementById("apm-name").value = `${which === "full" ? "Full" : "Basic"} copy`;
  renderApmTagList();
}

function apmApplyCopyFrom() {
  const val = document.getElementById("apm-copy-from").value;
  if (!val) return;
  let tags = [];
  if (val === "basic")         tags = _APM_BASIC_TAGS;
  else if (val === "full")     tags = _APM_FULL_TAGS;
  else if (val.startsWith("custom:")) {
    const n = val.slice(7);
    tags = (_anonCustomProfiles[n] || {}).tags || [];
  }
  _apmCurrentChecked = new Set(tags);
  renderApmTagList();
  // Reset the dropdown so user can apply again if needed
  setTimeout(() => { document.getElementById("apm-copy-from").value = ""; }, 300);
}

function renderApmTagList() {
  const q         = (document.getElementById("apm-tag-filter").value || "").toLowerCase();
  const container = document.getElementById("apm-tag-list");
  container.innerHTML = "";

  _APM_KNOWN_TAGS.forEach(group => {
    const filteredTags = group.tags.filter(t =>
      !q || t.label.toLowerCase().includes(q) || t.tag.toLowerCase().includes(q)
    );
    if (!filteredTags.length) return;

    const hdr = document.createElement("div");
    hdr.style.cssText = "font-size:11px; font-weight:700; color:#6b7280; padding:8px 4px 3px; text-transform:uppercase; letter-spacing:.05em";
    hdr.textContent = group.group;
    container.appendChild(hdr);

    filteredTags.forEach(t => {
      const row = document.createElement("label");
      row.style.cssText = "display:flex; align-items:center; gap:10px; padding:5px 6px; cursor:pointer; border-radius:4px; font-size:13px; user-select:none";
      const cb = document.createElement("input");
      cb.type    = "checkbox";
      cb.value   = t.tag;
      cb.checked = _apmCurrentChecked.has(t.tag);
      cb.style.cssText = "width:16px; height:16px; flex-shrink:0; cursor:pointer; accent-color:#2b6cb0; margin:0";
      cb.addEventListener("change", () => {
        if (cb.checked) _apmCurrentChecked.add(t.tag);
        else            _apmCurrentChecked.delete(t.tag);
      });
      const labelSpan = document.createElement("span");
      labelSpan.style.flex = "1";
      labelSpan.textContent = t.label;
      const tagSpan = document.createElement("span");
      tagSpan.style.cssText = "font-family:Consolas; font-size:10px; color:#9ca3af";
      tagSpan.textContent = t.tag;
      row.appendChild(cb);
      row.appendChild(labelSpan);
      row.appendChild(tagSpan);
      row.onmouseover = () => row.style.background = "#f0f9ff";
      row.onmouseout  = () => row.style.background = "";
      container.appendChild(row);
    });
  });
}

async function anonProfileSave() {
  const name = document.getElementById("apm-name").value.trim();
  if (!name) { toast(i18n("anonymizer.mgr_err_no_name"), "warn"); return; }
  const tags = [..._apmCurrentChecked];
  const statusEl = document.getElementById("apm-status");
  try {
    const res  = await fetch("/api/dicom/anon_profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, tags }),
    });
    const data = await res.json();
    if (!data.ok) { toast(i18n("anonymizer.mgr_err_save", {error: data.error}), "err"); return; }
    if (_apmEditingKey && _apmEditingKey !== name) {
      await fetch(`/api/dicom/anon_profiles/${encodeURIComponent(_apmEditingKey)}`,
                  { method: "DELETE" });
    }
    await _loadAnonProfilesFromServer();
    _apmEditingKey = name;
    renderApmProfileList();
    statusEl.textContent = i18n("anonymizer.mgr_saved", {name});
    setTimeout(() => { statusEl.textContent = ""; }, 2500);
  } catch (e) { toast("Error: " + e, "err"); }
}

async function anonProfileDelete() {
  if (!_apmEditingKey) return;
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: i18n("anonymizer.mgr_confirm_delete", {name: _apmEditingKey}),
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  try {
    await fetch(`/api/dicom/anon_profiles/${encodeURIComponent(_apmEditingKey)}`,
                { method: "DELETE" });
    _apmEditingKey = null;
    _apmCurrentChecked = new Set();
    await _loadAnonProfilesFromServer();
    renderApmProfileList();
    _apmHideEditor();
  } catch (e) { toast("Error: " + e, "err"); }
}

// Wire up profile selection → set _anonCustomTags when a custom profile is chosen
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("anon-profile").addEventListener("change", () => {
    const v = document.getElementById("anon-profile").value;
    if (v.startsWith("custom:")) {
      const n = v.slice(7);
      _anonCustomTags = (_anonCustomProfiles[n] || {}).tags || [];
    } else {
      _anonCustomTags = [];
    }
  });
});

