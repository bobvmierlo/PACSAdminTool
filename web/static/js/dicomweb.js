// dicomweb.js — DICOMweb (QIDO-RS / STOW-RS / WADO-RS) tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 17. DICOMweb (QIDO-RS / STOW-RS / WADO-RS)
// ─────────────────────────────────────────────────────────────────

function showDWTab(name) {
  document.querySelectorAll("[id^='dw-subtab-']").forEach(el => el.style.display = "none");
  document.querySelectorAll("[id^='dw-tab-'][id$='-btn']").forEach(el => el.classList.remove("active"));
  document.getElementById("dw-subtab-" + name).style.display = "block";
  document.getElementById("dw-tab-" + name + "-btn").classList.add("active");
}

function dwAuthTypeChanged() {
  const type = document.getElementById("dw-auth-type").value;
  document.getElementById("dw-basic-fields").style.display  = type === "basic"  ? "" : "none";
  document.getElementById("dw-bearer-fields").style.display = type === "bearer" ? "" : "none";
}

function _dwCfg() {
  return {
    base_url:  document.getElementById("dw-base-url").value.trim(),
    auth_type: document.getElementById("dw-auth-type").value,
    username:  document.getElementById("dw-username").value.trim(),
    password:  document.getElementById("dw-password").value,
    token:     document.getElementById("dw-token").value.trim(),
  };
}

// ── Preset management ─────────────────────────────────────────────

function dwRefreshPresets() {
  const sysPresets  = appConfig.dicomweb_presets   || [];
  const userPresets = userSettings.dicomweb_presets || [];
  const sel  = document.getElementById("dw-preset-select");
  const prev = sel.value;
  sel.innerHTML = `<option value="">${i18n("dicomweb.load_preset")}</option>`;
  if (sysPresets.length > 0) {
    const grp = document.createElement("optgroup");
    grp.label = i18n("settings.system_presets");
    sysPresets.forEach(p => {
      const opt = document.createElement("option");
      opt.value = "sys:" + p.name;
      opt.textContent = p.name;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  }
  if (userPresets.length > 0) {
    const grp = document.createElement("optgroup");
    grp.label = i18n("settings.user_presets");
    userPresets.forEach(p => {
      const opt = document.createElement("option");
      opt.value = "usr:" + p.name;
      opt.textContent = p.name;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  }
  sel.value = prev;
}

function dwLoadPreset() {
  const val = document.getElementById("dw-preset-select").value;
  if (!val) return;
  let p;
  if (val.startsWith("usr:")) {
    const name = val.slice(4);
    p = (userSettings.dicomweb_presets || []).find(x => x.name === name);
  } else {
    const name = val.startsWith("sys:") ? val.slice(4) : val;
    p = (appConfig.dicomweb_presets || []).find(x => x.name === name);
  }
  if (!p) return;
  document.getElementById("dw-base-url").value  = p.base_url  || "";
  document.getElementById("dw-auth-type").value = p.auth_type || "none";
  document.getElementById("dw-username").value  = p.username  || "";
  document.getElementById("dw-password").value  = p.password  || "";
  document.getElementById("dw-token").value     = p.token     || "";
  dwAuthTypeChanged();
}

async function dwSavePreset() {
  const name = await _dialog({
    title:   i18n("dicomweb.preset_name_prompt"),
    message: "",
    input:   { defaultValue: "", placeholder: i18n("dicomweb.preset_name_prompt") },
    buttons: [
      { text: i18n("common.ok"),     value: "__input__", className: "btn primary" },
      { text: i18n("common.cancel"), value: null,        className: "btn" },
    ],
  });
  if (!name || !name.trim()) return;
  const trimmed = name.trim();
  const preset  = { name: trimmed, ..._dwCfg() };

  // Ask where to save when a user is logged in
  let toSystem = true;
  if (_currentUser) {
    const dest = await _dialog({
      title:   i18n("settings.preset_save_choice"),
      message: "",
      buttons: [
        { text: i18n("settings.save_to_system"),     value: "system", className: "btn primary" },
        { text: i18n("settings.save_to_my_presets"), value: "mine",   className: "btn" },
        { text: i18n("common.cancel"),               value: null,     className: "btn" },
      ],
    });
    if (dest === null) return;
    toSystem = dest === "system";
  }

  if (toSystem) {
    if (!appConfig.dicomweb_presets) appConfig.dicomweb_presets = [];
    appConfig.dicomweb_presets = appConfig.dicomweb_presets.filter(p => p.name !== trimmed);
    appConfig.dicomweb_presets.push(preset);
    await _patchConfig({ dicomweb_presets: appConfig.dicomweb_presets });
  } else {
    if (!userSettings.dicomweb_presets) userSettings.dicomweb_presets = [];
    userSettings.dicomweb_presets = userSettings.dicomweb_presets.filter(p => p.name !== trimmed);
    userSettings.dicomweb_presets.push(preset);
    await _patchUserSettings({ dicomweb_presets: userSettings.dicomweb_presets });
  }

  dwRefreshPresets();
  document.getElementById("dw-preset-select").value = (toSystem ? "sys:" : "usr:") + trimmed;
  toast(i18n("dicomweb.preset_saved"), "ok");
}

async function dwDeletePreset() {
  const sel  = document.getElementById("dw-preset-select");
  const val  = sel.value; // "sys:name" or "usr:name"
  if (!val) return;
  const isUser = val.startsWith("usr:");
  const name   = val.replace(/^(sys:|usr:)/, "");
  const delOk = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: i18n("dicomweb.preset_delete_confirm").replace("{name}", name),
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!delOk) return;

  if (isUser) {
    userSettings.dicomweb_presets = (userSettings.dicomweb_presets || []).filter(p => p.name !== name);
    await _patchUserSettings({ dicomweb_presets: userSettings.dicomweb_presets });
  } else {
    appConfig.dicomweb_presets = (appConfig.dicomweb_presets || []).filter(p => p.name !== name);
    await _patchConfig({ dicomweb_presets: appConfig.dicomweb_presets });
  }
  dwRefreshPresets();
  toast(i18n("dicomweb.preset_deleted"), "ok");
}

// ── Connection test ───────────────────────────────────────────────

async function dwTestConnection() {
  const cfg = _dwCfg();
  if (!cfg.base_url) { toast(i18n("dicomweb.no_url"), "warn"); return; }
  const statusEl = document.getElementById("dw-test-status");
  statusEl.textContent = "…";
  statusEl.style.color = "#888";
  try {
    const res  = await fetch("/api/dicomweb/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = "✓ " + i18n("dicomweb.test_ok");
      statusEl.style.color = "#15803d";
    } else {
      statusEl.textContent = "✗ " + (data.error || "failed");
      statusEl.style.color = "#dc2626";
    }
  } catch (e) {
    statusEl.textContent = "✗ " + e;
    statusEl.style.color = "#dc2626";
  }
}

// ── QIDO-RS ───────────────────────────────────────────────────────

function dwQIDOLevelChanged() {
  const level = document.getElementById("dw-qido-level").value;
  document.getElementById("dw-qido-study-uid-field").style.display  =
    ["series","instances"].includes(level) ? "" : "none";
  document.getElementById("dw-qido-series-uid-field").style.display =
    level === "instances" ? "" : "none";
}

async function doQIDO() {
  const cfg = _dwCfg();
  if (!cfg.base_url) { toast(i18n("dicomweb.no_url"), "warn"); return; }

  const level     = document.getElementById("dw-qido-level").value;
  const studyUid  = document.getElementById("dw-qido-study-uid").value.trim();
  const seriesUid = document.getElementById("dw-qido-series-uid").value.trim();
  const limit     = document.getElementById("dw-qido-limit").value.trim();

  const params = {};
  const patId  = document.getElementById("dw-qido-patient-id").value.trim();
  const patNm  = document.getElementById("dw-qido-patient-name").value.trim();
  const stDate = document.getElementById("dw-qido-study-date").value.trim();
  const modal  = document.getElementById("dw-qido-modality").value.trim();
  const acc    = document.getElementById("dw-qido-accession").value.trim();
  if (patId)  params["00100020"] = patId;
  if (patNm)  params["00100010"] = patNm;
  if (stDate) params["00080020"] = stDate;
  if (modal) {
    // Studies level uses ModalitiesInStudy; series/instances use Modality
    params[level === "studies" ? "00080061" : "00080060"] = modal;
  }
  if (acc)   params["00080050"] = acc;
  if (limit) params["limit"]    = limit;

  // Request useful fields to be returned
  params["includefield"] =
    "00100020,00100010,00080020,00080050,00080061,00080060,0020000D," +
    "00201206,00201208,00081030,0008103E,0020000E";

  const countEl = document.getElementById("dw-qido-count");
  countEl.textContent = "…";

  try {
    const res  = await fetch("/api/dicomweb/qido", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...cfg, level, study_uid: studyUid,
                             series_uid: seriesUid, params }),
    });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || "QIDO-RS failed", "err");
      countEl.textContent = "";
      return;
    }
    _dwRenderQIDO(data.results, level);
    countEl.textContent = i18n("dicomweb.results_count", { n: data.count });
  } catch (e) {
    toast("" + e, "err");
    countEl.textContent = "";
  }
}

function _dwTag(obj, tag) {
  if (!obj || !obj[tag]) return "";
  const t = obj[tag];
  if (!t.Value || t.Value.length === 0) return "";
  const v = t.Value[0];
  if (typeof v === "object" && v !== null) {
    return v.Alphabetic || v.Ideographic || v.Phonetic || JSON.stringify(v);
  }
  if (Array.isArray(t.Value)) return t.Value.join("\\");
  return String(v);
}

function _dwRenderQIDO(results, level) {
  const tbody = document.getElementById("dw-qido-tbody");
  const wrap  = document.getElementById("dw-qido-results-wrap");
  tbody.innerHTML = "";
  wrap.style.display = "block";

  if (!results || results.length === 0) {
    tbody.innerHTML =
      `<tr><td colspan="8" style="text-align:center;color:#888;padding:16px">` +
      escapeHtml(i18n("dicomweb.no_results")) + `</td></tr>`;
    return;
  }

  results.forEach(r => {
    const patId   = _dwTag(r, "00100020");
    const patName = _dwTag(r, "00100010");
    const date    = _dwTag(r, "00080020");
    const modal   = _dwTag(r, "00080061") || _dwTag(r, "00080060");
    const acc     = _dwTag(r, "00080050");
    const desc    = _dwTag(r, "00081030") || _dwTag(r, "0008103E");
    const nSeries = _dwTag(r, "00201206") || _dwTag(r, "00201208") || "";
    const uid     = _dwTag(r, "0020000D") || _dwTag(r, "0020000E");

    const dateFmt = date.length === 8
      ? `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}`
      : date;

    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    tr.title = i18n("dicomweb.row_click_hint");
    tr.innerHTML =
      `<td>${escapeHtml(patId)}</td>` +
      `<td>${escapeHtml(patName)}</td>` +
      `<td>${escapeHtml(dateFmt)}</td>` +
      `<td>${escapeHtml(modal)}</td>` +
      `<td>${escapeHtml(acc)}</td>` +
      `<td>${escapeHtml(desc)}</td>` +
      `<td>${escapeHtml(nSeries)}</td>` +
      `<td style="font-size:11px;color:#888;word-break:break-all;max-width:180px;` +
      `overflow:hidden;text-overflow:ellipsis" title="${escapeHtml(uid)}">` +
      `${escapeHtml(uid)}</td>`;

    tr.addEventListener("click", () => {
      // Copy study UID to WADO-RS and the QIDO study-uid field
      const studyUid = _dwTag(r, "0020000D");
      if (studyUid) {
        document.getElementById("dw-wado-study-uid").value  = studyUid;
        document.getElementById("dw-qido-study-uid").value  = studyUid;
      }
    });
    tbody.appendChild(tr);
  });
}

function dwClearResults() {
  document.getElementById("dw-qido-tbody").innerHTML = "";
  document.getElementById("dw-qido-results-wrap").style.display = "none";
  document.getElementById("dw-qido-count").textContent = "";
}

// ── STOW-RS ───────────────────────────────────────────────────────

let _dwSTOWFiles = [];

function dwSTOWFilesSelected() {
  _dwSTOWFiles = Array.from(document.getElementById("dw-stow-file-input").files);
  document.getElementById("dw-stow-file-count").textContent =
    i18n("dicomweb.files_selected", { n: _dwSTOWFiles.length });
  document.getElementById("dw-stow-file-list").innerHTML =
    _dwSTOWFiles.map(f =>
      `<div>${escapeHtml(f.name)} ` +
      `<span style="color:#aaa">(${(f.size/1024).toFixed(1)} KB)</span></div>`
    ).join("");
}

function dwSTOWClearFiles() {
  _dwSTOWFiles = [];
  document.getElementById("dw-stow-file-input").value = "";
  document.getElementById("dw-stow-file-count").textContent = "";
  document.getElementById("dw-stow-file-list").innerHTML    = "";
  document.getElementById("dw-stow-status").textContent     = "";
}

async function doSTOW() {
  const cfg = _dwCfg();
  if (!cfg.base_url)          { toast(i18n("dicomweb.no_url"),   "warn"); return; }
  if (!_dwSTOWFiles.length)   { toast(i18n("dicomweb.no_files"), "warn"); return; }

  const statusEl = document.getElementById("dw-stow-status");
  statusEl.textContent = i18n("dicomweb.sending");
  statusEl.style.color = "#888";

  const fd = new FormData();
  fd.append("base_url",  cfg.base_url);
  fd.append("auth_type", cfg.auth_type);
  fd.append("username",  cfg.username);
  fd.append("password",  cfg.password);
  fd.append("token",     cfg.token);
  _dwSTOWFiles.forEach(f => fd.append("files[]", f));

  try {
    const res  = await fetch("/api/dicomweb/stow", { method: "POST", body: fd });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = "✓ " + i18n("dicomweb.stow_ok", { n: data.files_sent });
      statusEl.style.color = "#15803d";
    } else {
      statusEl.textContent = "✗ " + (data.error || "failed");
      statusEl.style.color = "#dc2626";
    }
  } catch (e) {
    statusEl.textContent = "✗ " + e;
    statusEl.style.color = "#dc2626";
  }
}

// ── WADO-RS ───────────────────────────────────────────────────────

async function doWADO() {
  const cfg = _dwCfg();
  if (!cfg.base_url) { toast(i18n("dicomweb.no_url"), "warn"); return; }

  const studyUid    = document.getElementById("dw-wado-study-uid").value.trim();
  const seriesUid   = document.getElementById("dw-wado-series-uid").value.trim();
  const instanceUid = document.getElementById("dw-wado-instance-uid").value.trim();

  if (!studyUid) { toast(i18n("dicomweb.wado_no_study"), "warn"); return; }

  const statusEl = document.getElementById("dw-wado-status");
  statusEl.textContent = i18n("dicomweb.retrieving");
  statusEl.style.color = "#888";

  try {
    const res = await fetch("/api/dicomweb/wado", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...cfg, study_uid: studyUid,
                             series_uid: seriesUid, instance_uid: instanceUid }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      statusEl.textContent = "✗ " + (err.error || res.statusText);
      statusEl.style.color = "#dc2626";
      return;
    }

    const blob = await res.blob();
    const cd   = res.headers.get("Content-Disposition") || "";
    const m    = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
    const name = m ? m[1].replace(/['"]/g, "") : "wado_retrieve.zip";

    const url = URL.createObjectURL(blob);
    const a   = document.createElement("a");
    a.href    = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);

    statusEl.textContent = "✓ " + i18n("dicomweb.wado_ok");
    statusEl.style.color = "#15803d";
  } catch (e) {
    statusEl.textContent = "✗ " + e;
    statusEl.style.color = "#dc2626";
  }
}

