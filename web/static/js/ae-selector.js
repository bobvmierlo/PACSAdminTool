// ae-selector.js — AE Selector widget (reused across tabs)
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 4. AE Selector widget (reused across tabs)
// ─────────────────────────────────────────────────────────────────

// Each AE selector is a div that gets filled with a preset dropdown
// and manual AE title / host / port fields.
// `containerId` is the div to inject into; `prefix` is a unique ID prefix.
function buildAESelector(containerId, prefix) {
  const container = document.getElementById(containerId);
  container.innerHTML = `
    <div class="ae-selector">
      <div class="field preset-field">
        <label>${i18n("common.preset")}</label>
        <div style="display:flex;align-items:center;gap:6px">
          <select id="${prefix}-preset" onchange="loadPreset('${prefix}')">
            <option value="">${i18n("common.manual")}</option>
          </select>
          <span class="ae-dot" id="${prefix}-ae-dot" title=""></span>
        </div>
      </div>
      <div class="field"><label>${i18n("common.ae_title")}</label><input id="${prefix}-ae" value="REMOTE_AE"></div>
      <div class="field"><label>${i18n("common.host")}</label><input id="${prefix}-host" value="127.0.0.1"></div>
      <div class="field" style="max-width:90px"><label>${i18n("common.port")}</label><input id="${prefix}-port" type="number" min="1" max="65535" value="104"></div>
    </div>`;
}

// Refresh all preset <select> elements with current config
function refreshAllPresetDropdowns() {
  const sysPresets  = appConfig.remote_aes   || [];
  const userPresets = userSettings.remote_aes || [];
  document.querySelectorAll("[id$='-preset']").forEach(sel => {
    // Skip DICOMweb preset selects (handled by dwRefreshPresets)
    if (sel.id === "dw-preset-select") return;
    const current = sel.value;
    sel.innerHTML = `<option value="">${i18n("common.manual")}</option>`;
    if (sysPresets.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = i18n("settings.system_presets");
      sysPresets.forEach(ae => {
        const opt = document.createElement("option");
        opt.value = "sys:" + ae.name;
        opt.textContent = ae.name;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }
    if (userPresets.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = i18n("settings.user_presets");
      userPresets.forEach(ae => {
        const opt = document.createElement("option");
        opt.value = "usr:" + ae.name;
        opt.textContent = ae.name;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }
    sel.value = current;  // restore previous selection if still valid
  });
  cfindRefreshPresetDropdown();
}

function loadPreset(prefix) {
  const val  = document.getElementById(prefix + "-preset").value;
  if (!val) return;
  let ae;
  if (val.startsWith("usr:")) {
    const name = val.slice(4);
    ae = (userSettings.remote_aes || []).find(a => a.name === name);
  } else {
    const name = val.startsWith("sys:") ? val.slice(4) : val;
    ae = (appConfig.remote_aes || []).find(a => a.name === name);
  }
  if (!ae) return;
  document.getElementById(prefix + "-ae").value   = ae.ae_title;
  document.getElementById(prefix + "-host").value = ae.host;
  document.getElementById(prefix + "-port").value = ae.port;
  // Sync health dot key and restore any cached health state
  const dot = document.getElementById(prefix + "-ae-dot");
  if (dot) {
    const key = _aeKey(ae);
    dot.dataset.aeKey = key;
    const state = _aeHealth[key];
    dot.className = "ae-dot" + (state ? " " + state : "");
    dot.title = state === "ok" ? "Reachable" : state === "err" ? "Unreachable" : "";
  }
}

// Validate and parse a port string.  Returns the numeric port (1-65535)
// or null if the value is not a valid port number.
function parsePort(value, fallback) {
  const n = parseInt(value, 10);
  if (isNaN(n) || n < 1 || n > 65535) return null;
  return n;
}

// Read the AE fields for a given prefix into a plain object
function getAE(prefix) {
  const portStr = document.getElementById(prefix + "-port").value;
  const port = parsePort(portStr);
  if (port === null) {
    toast(i18n("common.invalid_port", {port: portStr}), "err");
    return null;
  }
  return {
    ae_title: document.getElementById(prefix + "-ae").value.trim(),
    host:     document.getElementById(prefix + "-host").value.trim(),
    port:     port,
  };
}

