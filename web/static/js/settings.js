// settings.js — Config / Settings tab, user preferences, telemetry consent banner
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 3. Config / Settings
// ─────────────────────────────────────────────────────────────────

let appConfig    = {};  // full system config from /api/config
let userSettings = {};  // per-user settings from /api/user/settings
let _currentUser = null; // {username, role} or null

const ADVANCED_TABS = ["commit", "iocm", "kos_creator", "uid_remap", "dicomweb"];

/** POST a partial patch to /api/config (only the keys provided). */
async function _patchConfig(patch) {
  try {
    const res = await fetch("/api/config", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(patch),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      toast("Config save error: " + (err.error || res.statusText), "err");
    }
  } catch (e) {
    toast("Config save error: " + e, "err");
  }
}

/** POST a partial patch to /api/user/settings. No-op if not logged in. */
async function _patchUserSettings(patch) {
  if (!_currentUser) return;
  try {
    await fetch("/api/user/settings", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(patch),
    });
  } catch { /* ignore */ }
}

// Called once on page load to populate all forms with saved settings
async function loadConfig() {
  try {
    const res  = await fetch("/api/config");
    appConfig  = await res.json();
  } catch (e) {
    console.warn("Could not load config from server:", e);
    return;
  }

  // Populate settings tab
  const lae = appConfig.local_ae || {};
  document.getElementById("set-ae-title").value = lae.ae_title || "PACSADMIN";
  document.getElementById("set-ae-port").value  = lae.port     || 11112;
  const hl7 = appConfig.hl7 || {};
  document.getElementById("set-hl7-port").value         = hl7.listen_port   || 2575;
  document.getElementById("set-hl7-default-host").value = hl7.default_host  || "127.0.0.1";
  document.getElementById("set-hl7-default-port").value = hl7.default_port  || 2575;
  // Pre-fill the HL7 send form with the configured defaults
  document.getElementById("hl7-host").value = hl7.default_host || "127.0.0.1";
  document.getElementById("hl7-port").value = hl7.default_port || 2575;
  const web = appConfig.web || {};
  document.getElementById("set-web-host").value  = web.host || "0.0.0.0";
  document.getElementById("set-web-port").value  = web.port || 5000;
  document.getElementById("set-log-level").value = appConfig.log_level || "INFO";
  if (appConfig.language) {
    document.getElementById("set-language").value = appConfig.language;
  }
  const tel = appConfig.telemetry || {};
  document.getElementById("set-telemetry-enabled").checked =
    tel.enabled !== false;  // default true

  // Show the consent banner once if the user hasn't seen it yet.
  if (tel.consent_shown === false || tel.consent_shown === undefined) {
    document.getElementById("telemetry-consent").classList.add("visible");
  }

  // Set SCP / HL7 listener defaults from config
  document.getElementById("scp-ae").value          = lae.ae_title || "PACSADMIN";
  document.getElementById("scp-port").value         = lae.port     || 11112;
  document.getElementById("hl7-listen-port").value  = hl7.listen_port || 2575;

  // Pre-fill Move Destination with local AE title
  document.getElementById("cfind-movedest").value = lae.ae_title || "PACSADMIN";

  renderPresetTable();
  renderSysDWPresetsTable();
  refreshAllPresetDropdowns();
  dwRefreshPresets();
}

function renderPresetTable() {
  const tbody = document.getElementById("ae-presets-tbody");
  tbody.innerHTML = "";
  (appConfig.remote_aes || []).forEach((ae, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${ae.name}</td><td>${ae.ae_title}</td><td>${ae.host}</td><td>${ae.port}</td>` +
      `<td style="white-space:nowrap">` +
      `<button class="btn" style="padding:2px 8px; font-size:11px; margin-right:4px"
          onclick="testPreset(${i}, this)">Test</button>` +
      `<button class="btn danger" style="padding:2px 8px; font-size:11px"
          onclick="deletePreset(${i})">Delete</button>` +
      `<span id="preset-test-${i}" style="margin-left:6px; font-size:11px"></span>` +
      `</td>`;
    tbody.appendChild(tr);
  });
}

async function testPreset(i, btn) {
  const ae = (appConfig.remote_aes || [])[i];
  if (!ae) return;
  btn.disabled = true;
  const statusEl = document.getElementById(`preset-test-${i}`);
  statusEl.textContent = "…";
  statusEl.style.color = "#888";
  try {
    const res = await fetch("/api/dicom/echo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ae_title: ae.ae_title, host: ae.host, port: ae.port }),
    });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = i18n("dashboard.ae_reachable");
      statusEl.style.color = "#16a34a";
    } else {
      statusEl.textContent = i18n("dashboard.ae_failed", { message: data.message || "failed" });
      statusEl.style.color = "#dc2626";
    }
  } catch {
    statusEl.textContent = i18n("dashboard.ae_error");
    statusEl.style.color = "#dc2626";
  } finally {
    btn.disabled = false;
  }
}

async function addPreset() {
  const name = document.getElementById("new-ae-name").value.trim();
  const aet  = document.getElementById("new-ae-aet").value.trim();
  const host = document.getElementById("new-ae-host").value.trim();
  const port = parsePort(document.getElementById("new-ae-port").value);
  if (!name) { toast(i18n("settings.name_required"), "warn"); return; }
  if (port === null) { toast(i18n("common.invalid_port", {port: document.getElementById("new-ae-port").value.trim()}), "err"); return; }
  const preset = { name, ae_title: aet, host, port };
  let dest = "system";
  if (_currentUser) {
    dest = await _dialog({
      title:   i18n("settings.preset_save_choice"),
      message: "",
      buttons: [
        { text: i18n("settings.save_to_system"),     value: "system", className: "btn primary" },
        { text: i18n("settings.save_to_my_presets"), value: "mine",   className: "btn" },
        { text: i18n("common.cancel"),               value: null,     className: "btn" },
      ],
    });
    if (dest === null) return;
  }
  if (dest === "system") {
    if (!appConfig.remote_aes) appConfig.remote_aes = [];
    appConfig.remote_aes = appConfig.remote_aes.filter(a => a.name !== name);
    appConfig.remote_aes.push(preset);
    await _patchConfig({ remote_aes: appConfig.remote_aes });
  } else {
    if (!userSettings.remote_aes) userSettings.remote_aes = [];
    userSettings.remote_aes = userSettings.remote_aes.filter(a => a.name !== name);
    userSettings.remote_aes.push(preset);
    await _patchUserSettings({ remote_aes: userSettings.remote_aes });
    renderMyPreferences();
  }
  renderPresetTable();
  refreshAllPresetDropdowns();
  ["new-ae-name","new-ae-aet","new-ae-host","new-ae-port"].forEach(id =>
    document.getElementById(id).value = "");
}

async function deletePreset(i) {
  const p = appConfig.remote_aes?.[i];
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete preset "${p?.name || p?.ae_title || i}"?\n${i18n("common.cannot_undo")}`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  appConfig.remote_aes.splice(i, 1);
  await _patchConfig({ remote_aes: appConfig.remote_aes });
  renderPresetTable();
  refreshAllPresetDropdowns();
}

// ── My Preferences ───────────────────────────────────────────────────────────

function renderMyPreferences() {
  const card = document.getElementById("my-preferences-card");
  if (!card) return;
  if (!_currentUser) { card.style.display = "none"; return; }
  card.style.display = "";

  // Sync advanced-tabs checkbox
  const cb = document.getElementById("pref-show-advanced-tabs");
  if (cb) cb.checked = userSettings.show_advanced_tabs || false;

  // Render My DICOM AE Presets table
  const aeBody = document.getElementById("my-ae-presets-tbody");
  if (aeBody) {
    aeBody.innerHTML = "";
    (userSettings.remote_aes || []).forEach((ae, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${ae.name}</td><td>${ae.ae_title}</td><td>${ae.host}</td><td>${ae.port}</td>` +
        `<td><button class="btn danger" style="padding:2px 8px; font-size:11px"
            onclick="deleteMyAEPreset(${i})">Delete</button></td>`;
      aeBody.appendChild(tr);
    });
  }

  // Render My DICOMweb Presets table
  const dwBody = document.getElementById("my-dw-presets-tbody");
  if (dwBody) {
    dwBody.innerHTML = "";
    (userSettings.dicomweb_presets || []).forEach((p, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${p.name}</td><td style="word-break:break-all;font-size:12px">${p.base_url || ""}</td>` +
        `<td><button class="btn danger" style="padding:2px 8px; font-size:11px"
            onclick="deleteMyDWPreset(${i})">Delete</button></td>`;
      dwBody.appendChild(tr);
    });
  }
}

async function addMyAEPreset() {
  const name = document.getElementById("my-ae-name").value.trim();
  const aet  = document.getElementById("my-ae-aet").value.trim();
  const host = document.getElementById("my-ae-host").value.trim();
  const port = parsePort(document.getElementById("my-ae-port").value);
  if (!name) { toast(i18n("settings.name_required"), "warn"); return; }
  if (port === null) { toast(i18n("common.invalid_port", {port: document.getElementById("my-ae-port").value.trim()}), "err"); return; }
  if (!userSettings.remote_aes) userSettings.remote_aes = [];
  userSettings.remote_aes = userSettings.remote_aes.filter(a => a.name !== name);
  userSettings.remote_aes.push({ name, ae_title: aet, host, port });
  await _patchUserSettings({ remote_aes: userSettings.remote_aes });
  renderMyPreferences();
  refreshAllPresetDropdowns();
  ["my-ae-name","my-ae-aet","my-ae-host","my-ae-port"].forEach(id =>
    document.getElementById(id).value = "");
}

async function deleteMyAEPreset(i) {
  if (!userSettings.remote_aes) return;
  const p = userSettings.remote_aes[i];
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete preset "${p?.name || p?.ae_title || i}"?\n${i18n("common.cannot_undo")}`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  userSettings.remote_aes.splice(i, 1);
  await _patchUserSettings({ remote_aes: userSettings.remote_aes });
  renderMyPreferences();
  refreshAllPresetDropdowns();
}

async function addMyDWPreset() {
  const name    = document.getElementById("my-dw-name").value.trim();
  const baseUrl = document.getElementById("my-dw-url").value.trim();
  const auth    = document.getElementById("my-dw-auth").value;
  const user    = document.getElementById("my-dw-user").value.trim();
  const pass    = document.getElementById("my-dw-pass").value;
  if (!name) { toast(i18n("settings.name_required"), "warn"); return; }
  if (!baseUrl) { toast("Base URL is required.", "warn"); return; }
  const preset = { name, base_url: baseUrl, auth_type: auth, username: user, password: pass, token: auth === "bearer" ? user : "" };
  if (!userSettings.dicomweb_presets) userSettings.dicomweb_presets = [];
  userSettings.dicomweb_presets = userSettings.dicomweb_presets.filter(p => p.name !== name);
  userSettings.dicomweb_presets.push(preset);
  await _patchUserSettings({ dicomweb_presets: userSettings.dicomweb_presets });
  renderMyPreferences();
  dwRefreshPresets();
  ["my-dw-name","my-dw-url","my-dw-user","my-dw-pass"].forEach(id =>
    document.getElementById(id).value = "");
}

async function deleteMyDWPreset(i) {
  if (!userSettings.dicomweb_presets) return;
  const p = userSettings.dicomweb_presets[i];
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete preset "${p?.name || i}"?\n${i18n("common.cannot_undo")}`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  userSettings.dicomweb_presets.splice(i, 1);
  await _patchUserSettings({ dicomweb_presets: userSettings.dicomweb_presets });
  renderMyPreferences();
  dwRefreshPresets();
}

// ── System DICOMweb Presets ───────────────────────────────────────────────────

function renderSysDWPresetsTable() {
  const tbody = document.getElementById("sys-dw-presets-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  (appConfig.dicomweb_presets || []).forEach((p, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${p.name}</td>` +
      `<td style="word-break:break-all;font-size:12px">${p.base_url || ""}</td>` +
      `<td>${p.auth_type || "none"}</td>` +
      `<td><button class="btn danger" style="padding:2px 8px; font-size:11px"
          onclick="deleteSysDWPreset(${i})">Delete</button></td>`;
    tbody.appendChild(tr);
  });
}

async function addSysDWPreset() {
  const name    = document.getElementById("new-dw-name").value.trim();
  const baseUrl = document.getElementById("new-dw-url").value.trim();
  const auth    = document.getElementById("new-dw-auth").value;
  const user    = document.getElementById("new-dw-user").value.trim();
  const pass    = document.getElementById("new-dw-pass").value;
  if (!name)    { toast(i18n("settings.name_required"), "warn"); return; }
  if (!baseUrl) { toast("Base URL is required.", "warn"); return; }
  const preset = { name, base_url: baseUrl, auth_type: auth, username: user, password: pass };
  if (!appConfig.dicomweb_presets) appConfig.dicomweb_presets = [];
  appConfig.dicomweb_presets = appConfig.dicomweb_presets.filter(p => p.name !== name);
  appConfig.dicomweb_presets.push(preset);
  await _patchConfig({ dicomweb_presets: appConfig.dicomweb_presets });
  renderSysDWPresetsTable();
  dwRefreshPresets();
  ["new-dw-name", "new-dw-url", "new-dw-user", "new-dw-pass"].forEach(id =>
    document.getElementById(id).value = "");
  document.getElementById("new-dw-auth").value = "none";
}

async function deleteSysDWPreset(i) {
  if (!appConfig.dicomweb_presets) return;
  const p = appConfig.dicomweb_presets[i];
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete preset "${p?.name || i}"?\n${i18n("common.cannot_undo")}`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  appConfig.dicomweb_presets.splice(i, 1);
  await _patchConfig({ dicomweb_presets: appConfig.dicomweb_presets });
  renderSysDWPresetsTable();
  dwRefreshPresets();
}

// ── System Settings ───────────────────────────────────────────────────────────

async function saveSettings() {
  const localPort = parsePort(document.getElementById("set-ae-port").value);
  if (localPort === null) { toast(i18n("common.invalid_port", {port: document.getElementById("set-ae-port").value.trim()}), "err"); return; }
  const hl7Port = parsePort(document.getElementById("set-hl7-port").value);
  if (hl7Port === null) { toast(i18n("common.invalid_port", {port: document.getElementById("set-hl7-port").value.trim()}), "err"); return; }
  appConfig.local_ae = {
    ae_title: document.getElementById("set-ae-title").value.trim(),
    port:     localPort,
  };
  const hl7DefaultPort = parsePort(document.getElementById("set-hl7-default-port").value);
  if (hl7DefaultPort === null) { toast(i18n("common.invalid_port", {port: document.getElementById("set-hl7-default-port").value.trim()}), "err"); return; }
  appConfig.hl7 = {
    ...appConfig.hl7,
    listen_port:  hl7Port,
    default_host: document.getElementById("set-hl7-default-host").value.trim(),
    default_port: hl7DefaultPort,
  };
  const webPort = parsePort(document.getElementById("set-web-port").value);
  if (webPort === null) { toast(i18n("common.invalid_port", {port: document.getElementById("set-web-port").value.trim()}), "err"); return; }
  appConfig.web = {
    ...appConfig.web,
    host: document.getElementById("set-web-host").value.trim(),
    port: webPort,
  };
  appConfig.telemetry = {
    ...(appConfig.telemetry || {}),
    enabled: document.getElementById("set-telemetry-enabled").checked,
  };
  const patch = {
    local_ae: appConfig.local_ae,
    hl7:      appConfig.hl7,
    web:      appConfig.web,
    telemetry: appConfig.telemetry,
  };
  const res = await fetch("/api/config", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    toast(err.error || i18n("common.error"), "err");
    return;
  }
  const s = document.getElementById("save-status");
  s.textContent = i18n("settings.saved_web");
  setTimeout(() => s.textContent = "", 3000);
}

// ── Config backup: export / import ───────────────────────────────

async function exportConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) { toast("Could not fetch config.", "err"); return; }
    const cfg = await res.json();
    // Strip the telemetry anonymous_id before exporting
    if (cfg.telemetry && cfg.telemetry.anonymous_id !== undefined) {
      const tel = { ...cfg.telemetry };
      delete tel.anonymous_id;
      cfg.telemetry = tel;
    }
    const ts = new Date().toISOString().slice(0, 10);
    downloadText(`pacsadmin_config_${ts}.json`, JSON.stringify(cfg, null, 2), "application/json");
    const st = document.getElementById("config-backup-status");
    if (st) { st.textContent = "Exported."; setTimeout(() => st.textContent = "", 3000); }
  } catch (e) {
    toast("Export error: " + e, "err");
  }
}

async function importConfig(event) {
  const file = event.target.files[0];
  event.target.value = "";   // reset so same file can be re-selected
  if (!file) return;
  const st = document.getElementById("config-backup-status");
  try {
    const text = await file.text();
    const cfg  = JSON.parse(text);
    const res  = await fetch("/api/config", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(cfg),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast("Import failed: " + (data.error || res.statusText), "err");
      return;
    }
    // Reload config into UI
    await loadConfig();
    toast("Configuration imported successfully.", "ok");
    if (st) { st.textContent = "Imported."; setTimeout(() => st.textContent = "", 3000); }
  } catch (e) {
    toast("Import error: " + e, "err");
  }
}

async function saveUserPreferences() {
  const patch = {
    language:  document.getElementById("set-language").value,
    log_level: document.getElementById("set-log-level").value,
  };
  const res = await fetch("/api/config", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    toast(err.error || i18n("common.error"), "err");
    return;
  }
  Object.assign(appConfig, patch);
  const s = document.getElementById("pref-save-status");
  s.textContent = i18n("settings.saved_web");
  setTimeout(() => s.textContent = "", 3000);
  // Reload translations if language changed
  await loadTranslations();
  [["ae-cfind","cfind"],["ae-cstore","cstore"],["ae-dmwl","dmwl"],["ae-commit","commit"],["ae-iocm","iocm"]]
    .forEach(([c, p]) => buildAESelector(c, p));
  refreshAllPresetDropdowns();
  dwRefreshPresets();
}

// ─────────────────────────────────────────────────────────────────
// 3b. Telemetry consent banner
// ─────────────────────────────────────────────────────────────────

async function _saveTelemetryConsent(enabled) {
  const tel = { ...(appConfig.telemetry || {}), enabled, consent_shown: true };
  appConfig.telemetry = tel;
  document.getElementById("set-telemetry-enabled").checked = enabled;
  document.getElementById("telemetry-consent").classList.remove("visible");
  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ telemetry: tel }),
    });
  } catch (e) {
    console.warn("Could not save telemetry consent:", e);
  }
}

function telemetryAccept() {
  _saveTelemetryConsent(true);
}

function telemetryOptOut() {
  _saveTelemetryConsent(false);
}

