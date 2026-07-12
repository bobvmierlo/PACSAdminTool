// cfind.js — C-FIND / Query-Retrieve tab (incl. CSV export, history, presets)
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 6. C-FIND
// ─────────────────────────────────────────────────────────────────

let cfindResults = [];  // keep results for retrieve and detail popup

function cfindMethodChanged() {
  const method = document.querySelector('input[name="cfind-method"]:checked').value;
  document.getElementById("cfind-move-row").style.display = method === "move" ? "" : "none";
  document.getElementById("cfind-get-row").style.display  = method === "get"  ? "" : "none";
}

function cfindSelectAll(checked) {
  document.querySelectorAll("#cfind-tbody input[type=checkbox]").forEach(cb => {
    cb.checked = checked;
    cb.closest("tr").classList.toggle("selected", checked);
  });
  cfindUpdateSelCount();
}

function cfindUpdateSelCount() {
  const n = document.querySelectorAll("#cfind-tbody input[type=checkbox]:checked").length;
  document.getElementById("cfind-sel-count").textContent = n > 0 ? `${n} selected` : "";
  // Keep the header select-all checkbox in sync
  const total = document.querySelectorAll("#cfind-tbody input[type=checkbox]").length;
  const allChk = document.getElementById("cfind-chk-all");
  if (allChk) allChk.checked = total > 0 && n === total;
}

async function doCFind() {
  const ae = getAE("cfind");
  if (!ae) return;
  clearTable("cfind-tbody");
  cfindResults = [];
  cfindUpdateSelCount();
  appendLog("log-cfind", now(), `C-FIND → ${ae.ae_title}@${ae.host}:${ae.port}`);

  const res  = await fetch("/api/dicom/find", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...ae,
      query_level: document.getElementById("cfind-level").value,
      query_model: document.getElementById("cfind-model").value,
      patient_id:  document.getElementById("cfind-pid").value,
      patient_name: document.getElementById("cfind-pname").value,
      accession:   document.getElementById("cfind-acc").value,
      study_date:  cfindDateRange(),
      modality:    document.getElementById("cfind-mod").value,
      study_uid:   document.getElementById("cfind-suid").value,
    }),
  });
  const data = await res.json();
  appendLog("log-cfind", now(), data.message, data.ok ? "ok" : "err");

  cfindResults = data.results || [];
  if (data.ok) _cfindHistorySave();
  const tbody = document.getElementById("cfind-tbody");
  cfindResults.forEach((r, i) => {
    const tr  = document.createElement("tr");
    const chk = document.createElement("input");
    chk.type  = "checkbox";
    chk.style.cursor = "pointer";
    chk.addEventListener("change", () => {
      tr.classList.toggle("selected", chk.checked);
      cfindUpdateSelCount();
    });
    const tdChk = document.createElement("td");
    tdChk.style.cssText = "text-align:center; width:32px";
    tdChk.appendChild(chk);
    tr.appendChild(tdChk);

    const cells = [
      r.PatientID, r.PatientName, formatDicomDate(r.StudyDate), r.Modality,
      r.Accession, r.Description,
    ];
    cells.forEach(v => {
      const td = document.createElement("td");
      td.textContent = v;
      tr.appendChild(td);
    });
    const tdUid = document.createElement("td");
    tdUid.style.cssText = "font-family:Consolas;font-size:11px";
    tdUid.textContent = r.StudyUID;
    tr.appendChild(tdUid);

    // Click on the row (not the checkbox) → show tag modal
    tr.addEventListener("click", e => {
      if (e.target.type === "checkbox") return;
      showTagModal("C-FIND Result", r.tags);
    });
    tbody.appendChild(tr);
  });
}

// Unified retrieve: handles both C-MOVE (single or bulk) and C-GET
async function doRetrieve() {
  const method = document.querySelector('input[name="cfind-method"]:checked').value;
  const ae     = getAE("cfind");
  if (!ae) return;

  // Collect selected study UIDs
  const uids = [];
  document.querySelectorAll("#cfind-tbody input[type=checkbox]:checked").forEach(cb => {
    const idx = [...cb.closest("tbody").querySelectorAll("input[type=checkbox]")].indexOf(cb);
    if (cfindResults[idx]) uids.push(cfindResults[idx].StudyUID);
  });
  if (uids.length === 0) { toast(i18n("cfind.select_row_first"), "warn"); return; }

  const model = document.getElementById("cfind-model").value;

  if (method === "move") {
    const dest    = document.getElementById("cfind-movedest").value.trim();
    const localAE = (appConfig.local_ae || {}).ae_title || "PACSADMIN";
    // If C-MOVE destination is our local SCP, make sure it's running first
    if (dest === localAE) {
      const ready = await _ensureScpRunningForMove();
      if (!ready) return;
    }
    appendLog("log-cfind", now(),
              `C-MOVE → dest=${dest}  studies=${uids.length}`);
    const movePromises = uids.map(uid =>
      fetch("/api/dicom/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...ae, study_uid: uid, move_dest: dest, query_model: model }),
      }).then(r => r.json())
    );
    Promise.all(movePromises).then(results => {
      const allOk = results.every(r => r.ok);
      if (allOk) {
        appendLog("log-cfind", now(), "C-MOVE started — switching to DICOM Receiver", "ok");
        showTab("scp");
        setTimeout(loadSCPStudies, 1500);
      }
    }).catch(() => {});
  } else {
    const saveDir = document.getElementById("cfind-getdir").value.trim();
    appendLog("log-cfind", now(),
              `C-GET → save_dir=${saveDir}  studies=${uids.length}`);
    for (const uid of uids) {
      fetch("/api/dicom/get", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...ae, study_uid: uid, save_dir: saveDir, query_model: model }),
      });
    }
  }
}

// Keep old name as alias (in case any other code calls it)
async function doCMove() { return doRetrieve(); }

// ── C-FIND: CSV export ──────────────────────────────────────────
function exportCFindCSV() {
  if (!cfindResults.length) { toast("No results to export.", "warn"); return; }
  const cols = ["PatientID","PatientName","StudyDate","Modality","Accession","Description","StudyUID"];
  const esc  = v => `"${String(v).replace(/"/g, '""')}"`;
  const rows = [cols.join(",")].concat(
    cfindResults.map(r => cols.map(c => esc(r[c] ?? "")).join(","))
  );
  downloadText("cfind_results.csv", rows.join("\r\n"), "text/csv");
}

// ── C-FIND: query history (LocalStorage) ────────────────────────
const CFIND_HISTORY_KEY = "pacsadmin_cfind_history";
const CFIND_HISTORY_MAX = 10;

function _cfindHistorySave() {
  const query = {
    ae_title:     document.getElementById("cfind-ae-title")?.value ?? "",
    host:         document.getElementById("cfind-host")?.value ?? "",
    port:         document.getElementById("cfind-port")?.value ?? "",
    query_level:  document.getElementById("cfind-level").value,
    query_model:  document.getElementById("cfind-model").value,
    patient_id:      document.getElementById("cfind-pid").value,
    patient_name:    document.getElementById("cfind-pname").value,
    accession:       document.getElementById("cfind-acc").value,
    study_date_from: document.getElementById("cfind-date-from").value,
    study_date_to:   document.getElementById("cfind-date-to").value,
    modality:        document.getElementById("cfind-mod").value,
    study_uid:       document.getElementById("cfind-suid").value,
    ts: new Date().toISOString(),
  };
  const existing = _cfindHistoryLoad();
  // Deduplicate by a quick key (ignore ts)
  const key = q => `${q.host}:${q.port}|${q.patient_id}|${q.patient_name}|${q.accession}|${q.study_date_from||q.study_date||""}-${q.study_date_to||""}|${q.modality}|${q.study_uid}`;
  const deduped = existing.filter(q => key(q) !== key(query));
  deduped.unshift(query);
  try {
    localStorage.setItem(CFIND_HISTORY_KEY,
      JSON.stringify(deduped.slice(0, CFIND_HISTORY_MAX)));
  } catch { /* storage full – ignore */ }
  renderCFindHistory();
}

function _cfindHistoryLoad() {
  try { return JSON.parse(localStorage.getItem(CFIND_HISTORY_KEY) || "[]"); }
  catch { return []; }
}

function renderCFindHistory() {
  const history = _cfindHistoryLoad();
  const card    = document.getElementById("cfind-history-card");
  const ul      = document.getElementById("cfind-history-list");
  if (!history.length) { card.style.display = "none"; return; }
  card.style.display = "";
  ul.innerHTML = "";
  history.forEach((q, i) => {
    const parts = [];
    if (q.patient_id)   parts.push(`PID: ${q.patient_id}`);
    if (q.patient_name) parts.push(`Name: ${q.patient_name}`);
    if (q.accession)    parts.push(`Acc: ${q.accession}`);
    if (q.study_date)   parts.push(`Date: ${q.study_date}`);
    if (q.modality)     parts.push(`Mod: ${q.modality}`);
    if (!parts.length)  parts.push("(empty query)");
    const label = parts.join(" · ");
    const ts    = q.ts ? new Date(q.ts).toLocaleString() : "";
    const li = document.createElement("li");
    li.style.cssText = "display:flex; align-items:center; padding:4px 0; border-bottom:1px solid #f0f0f0; gap:8px";
    li.innerHTML =
      `<span style="flex:1; cursor:pointer; color:#2b6cb0" onclick="loadCFindHistory(${i})">${label}</span>` +
      `<span style="color:#aaa; font-size:11px; white-space:nowrap">${ts}</span>`;
    ul.appendChild(li);
  });
}

function loadCFindHistory(i) {
  const q = _cfindHistoryLoad()[i];
  if (!q) return;
  if (q.patient_id)      document.getElementById("cfind-pid").value        = q.patient_id;
  if (q.patient_name)    document.getElementById("cfind-pname").value      = q.patient_name;
  if (q.accession)       document.getElementById("cfind-acc").value        = q.accession;
  if (q.study_date_from) document.getElementById("cfind-date-from").value  = q.study_date_from;
  if (q.study_date_to)   document.getElementById("cfind-date-to").value    = q.study_date_to;
  // Backward compat: old history entries stored a raw YYYYMMDD (or range) string
  if (q.study_date && !q.study_date_from && !q.study_date_to) {
    const raw = q.study_date.split("-");
    if (raw[0] && raw[0].length === 8) document.getElementById("cfind-date-from").value = dicomDateToInput(raw[0]);
    if (raw[1] && raw[1].length === 8) document.getElementById("cfind-date-to").value   = dicomDateToInput(raw[1]);
  }
  if (q.modality)     document.getElementById("cfind-mod").value   = q.modality;
  if (q.study_uid)    document.getElementById("cfind-suid").value  = q.study_uid;
  if (q.query_level)  document.getElementById("cfind-level").value = q.query_level;
  if (q.query_model)  document.getElementById("cfind-model").value = q.query_model;
}

function clearCFindHistory() {
  localStorage.removeItem(CFIND_HISTORY_KEY);
  renderCFindHistory();
}

// ── C-FIND: saved query presets (stored in user settings) ────────

function cfindRefreshPresetDropdown() {
  const presets = userSettings.cfind_presets || [];
  const sel = document.getElementById("cfind-preset-select");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '<option value="">— Load preset —</option>';
  presets.forEach(p => {
    const opt = document.createElement("option");
    opt.value       = p.name;
    opt.textContent = p.name;
    sel.appendChild(opt);
  });
  if (prev) sel.value = prev;
}

function cfindLoadPreset() {
  const name = document.getElementById("cfind-preset-select").value;
  if (!name) return;
  const p = (userSettings.cfind_presets || []).find(x => x.name === name);
  if (!p) return;
  if (p.ae_title)    document.getElementById("cfind-ae").value       = p.ae_title;
  if (p.host)        document.getElementById("cfind-host").value     = p.host;
  if (p.port)        document.getElementById("cfind-port").value     = p.port;
  if (p.query_level) document.getElementById("cfind-level").value    = p.query_level;
  if (p.query_model) document.getElementById("cfind-model").value    = p.query_model;
  document.getElementById("cfind-pid").value       = p.patient_id   || "";
  document.getElementById("cfind-pname").value     = p.patient_name || "";
  document.getElementById("cfind-acc").value       = p.accession    || "";
  document.getElementById("cfind-date-from").value = p.date_from    || "";
  document.getElementById("cfind-date-to").value   = p.date_to      || "";
  document.getElementById("cfind-mod").value       = p.modality     || "";
  document.getElementById("cfind-suid").value      = p.study_uid    || "";
}

async function cfindSavePreset() {
  const name = await _dialog({
    title:   "Save C-FIND Preset",
    message: "",
    input:   { defaultValue: "", placeholder: "Preset name" },
    buttons: [
      { text: i18n("common.ok"),     value: "__input__", className: "btn primary" },
      { text: i18n("common.cancel"), value: null,        className: "btn" },
    ],
  });
  if (!name || !name.trim()) return;
  const trimmed = name.trim();
  const preset = {
    name:         trimmed,
    ae_title:     (document.getElementById("cfind-ae")   || {}).value || "",
    host:         (document.getElementById("cfind-host") || {}).value || "",
    port:         parseInt(document.getElementById("cfind-port")?.value, 10) || 104,
    query_level:  document.getElementById("cfind-level").value,
    query_model:  document.getElementById("cfind-model").value,
    patient_id:   document.getElementById("cfind-pid").value,
    patient_name: document.getElementById("cfind-pname").value,
    accession:    document.getElementById("cfind-acc").value,
    date_from:    document.getElementById("cfind-date-from").value,
    date_to:      document.getElementById("cfind-date-to").value,
    modality:     document.getElementById("cfind-mod").value,
    study_uid:    document.getElementById("cfind-suid").value,
  };
  if (!userSettings.cfind_presets) userSettings.cfind_presets = [];
  userSettings.cfind_presets = userSettings.cfind_presets.filter(p => p.name !== trimmed);
  userSettings.cfind_presets.push(preset);
  await _patchUserSettings({ cfind_presets: userSettings.cfind_presets });
  cfindRefreshPresetDropdown();
  document.getElementById("cfind-preset-select").value = trimmed;
  toast("Preset saved.", "ok");
}

async function cfindDeletePreset() {
  const sel  = document.getElementById("cfind-preset-select");
  const name = sel.value;
  if (!name) return;
  const delOk = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete preset "${name}"?`,
    buttons: [
      { text: i18n("common.delete"), value: true, className: "btn danger" },
      { text: i18n("common.cancel"), value: null,  className: "btn" },
    ],
  });
  if (!delOk) return;
  userSettings.cfind_presets = (userSettings.cfind_presets || []).filter(p => p.name !== name);
  await _patchUserSettings({ cfind_presets: userSettings.cfind_presets });
  cfindRefreshPresetDropdown();
  toast("Preset deleted.", "ok");
}

