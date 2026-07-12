// hl7-templates.js — HL7 template loading
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 11. HL7 Templates (loaded from server, not hardcoded)
// ─────────────────────────────────────────────────────────────────

// In-memory cache of templates fetched from /api/hl7/templates.
// Format: [ { name, description, filename }, ... ]
// The body is fetched separately when the user clicks Load Template.
let hl7TemplateList = [];

async function refreshHL7Templates() {
  // Fetch the list of available templates from the server.
  // The server reads these from hl7_templates/*.hl7 on disk, so adding
  // or editing a file and clicking Refresh is all that's needed.
  const sel = document.getElementById("hl7-template");
  const prev = sel.value;   // remember what was selected

  try {
    const res  = await fetch("/api/hl7/templates");
    hl7TemplateList = await res.json();

    sel.innerHTML = "";
    hl7TemplateList.forEach(t => {
      const opt = document.createElement("option");
      opt.value       = t.filename;   // use filename as the stable key
      opt.textContent = t.name;
      sel.appendChild(opt);
    });

    // Restore previous selection if it still exists
    if (prev && [...sel.options].some(o => o.value === prev)) {
      sel.value = prev;
    }

    // Show description for currently selected template
    updateTemplateDesc();

  } catch (e) {
    sel.innerHTML = '<option value="">(failed to load templates)</option>';
    appendLog("log-hl7-send", now(), `Could not load templates: ${e}`, "err");
  }
}

function updateTemplateDesc() {
  // Show the description of the selected template below the dropdown
  const sel      = document.getElementById("hl7-template");
  const filename = sel.value;
  const tmpl     = hl7TemplateList.find(t => t.filename === filename);
  const desc     = tmpl ? tmpl.description : "";
  document.getElementById("hl7-template-desc").textContent = desc;
}

// Wire up description update when user changes the dropdown
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("hl7-template")
    .addEventListener("change", updateTemplateDesc);

  // Fetch app version and data paths from the server
  fetch("/api/version")
    .then(r => r.json())
    .then(d => {
      document.getElementById("about-version-text").textContent = "Version " + (d.version || "?");
      if (d.app_dir) {
        const el = document.getElementById("about-app-dir");
        el.textContent = d.app_dir;
        el.title = "Configuration and log files location: " + d.app_dir;
      }
    })
    .catch(() => {});

  // Check for updates after a short delay (so the UI is fully ready first)
  setTimeout(checkForUpdate, 3000);
});

