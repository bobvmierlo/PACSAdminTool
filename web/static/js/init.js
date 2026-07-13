// init.js — Page initialisation — MUST be loaded last
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 17. Initialisation – runs when the page first loads
// ─────────────────────────────────────────────────────────────────

(async function init() {
  // Load translations first so all UI strings are available
  await loadTranslations();

  // Load language options for the settings dropdown
  await loadLanguageOptions();

  // Build AE selector widgets for every tab that needs one
  [
    ["ae-cfind",  "cfind"],
    ["ae-cstore", "cstore"],
    ["ae-dmwl",   "dmwl"],
    ["ae-commit", "commit"],
    ["ae-iocm",   "iocm"],
  ].forEach(([containerId, prefix]) => buildAESelector(containerId, prefix));

  // Ask the server for the real expanded default save path.
  // This ensures Windows users see C:\Users\... rather than ~/DICOM_Received.
  fetch("/api/scp/default_dir")
    .then(r => r.json())
    .then(d => { document.getElementById("scp-dir").value = d.path; })
    .catch(() => { document.getElementById("scp-dir").value = "~/DICOM_Received"; });

  // Load HL7 templates from server (reads hl7_templates/*.hl7 files)
  await refreshHL7Templates();

  // Load config from server and populate all fields
  await loadConfig();

  // Populate AE dropdowns that depend on config
  _populateAnonAEDropdown();
  _populateAnonCFindDropdown();

  // Load custom anonymisation profiles
  await _loadAnonProfilesFromServer();

  // Build the help topic list
  buildHelp();

  // Restore C-FIND query history
  renderCFindHistory();

  // Restore HL7 message histories
  renderHL7OutHistory();
  renderHL7InHistory();

  // Show username + logout button (if auth is active)
  // Must be awaited so userSettings is populated before showTab() is called
  await initAuthUI();

  // ── C-FIND model/level validation ─────────────────────────────────
  // Study Root model (STUDY) does not support PATIENT query level.
  // Auto-correct incompatible combinations and warn in the log.
  const cfindLevel = document.getElementById("cfind-level");
  const cfindModel = document.getElementById("cfind-model");

  cfindModel.addEventListener("change", () => {
    if (cfindModel.value === "STUDY" && cfindLevel.value === "PATIENT") {
      cfindLevel.value = "STUDY";
      appendLog("log-cfind", now(), i18n("cfind.warn_study_root"), "warn");
    }
  });

  cfindLevel.addEventListener("change", () => {
    if (cfindLevel.value === "PATIENT" && cfindModel.value === "STUDY") {
      cfindModel.value = "PATIENT";
      appendLog("log-cfind", now(), i18n("cfind.warn_patient_level"), "warn");
    }
  });

  // ── Log box upgrades: add auto-scroll toggle to every log box ────────
  document.querySelectorAll(".log-box").forEach(box => {
    const card = box.closest(".card");
    if (!card) return;
    const h3 = card.querySelector("h3");
    if (!h3) return;
    // Replace plain <h3> with a flex header row containing the toggle
    const header = document.createElement("div");
    header.className = "log-header";
    const title = document.createElement("span");
    title.textContent = h3.textContent;
    title.setAttribute("data-i18n", h3.getAttribute("data-i18n") || "");
    title.style.cssText = h3.style.cssText || "";
    title.className = h3.className;
    header.appendChild(title);
    // Auto-scroll label + checkbox
    const toggleLabel = document.createElement("label");
    toggleLabel.className = "log-scroll-toggle";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.addEventListener("change", () => toggleLogScroll(box.id, cb.checked));
    const lbl = document.createElement("span");
    lbl.textContent = i18n("common.autoscroll");
    lbl.setAttribute("data-i18n", "common.autoscroll");
    toggleLabel.appendChild(cb);
    toggleLabel.appendChild(lbl);
    header.appendChild(toggleLabel);
    h3.parentNode.insertBefore(header, h3);
    h3.remove();
  });

  // ── AE title inputs: add maxlength counter ───────────────────────────
  document.querySelectorAll("input[id$='-ae'], input[id='set-ae-title'], input[id='new-ae-aet']").forEach(wrapAETitleInput);

  // ── Clearable inputs: search/filter fields ───────────────────────────
  ["cfind-pid","cfind-pname","cfind-acc","cfind-mod",
   "dmwl-pid","dmwl-pname","dmwl-acc","dmwl-mod","dmwl-aet",
   "dz-wl-filter-name","dz-wl-filter-id","dz-wl-filter-mod"
  ].forEach(id => makeClearable(document.getElementById(id)));

  // ── Keyboard shortcuts ────────────────────────────────────────────────
  document.addEventListener("keydown", e => {
    // Escape → close the topmost visible modal
    if (e.key === "Escape") {
      if (document.getElementById("confirm-modal")?.classList.contains("open")) {
        _dialogCancel(); return;
      }
      if (document.getElementById("dwv-overlay")?.style.display === "flex") {
        closeDwvViewer(); return;
      }
      if (document.getElementById("preview-modal")?.style.display !== "none") {
        closePreviewModal(); return;
      }
      if (document.getElementById("tag-modal")?.classList.contains("open")) {
        closeTagModal(); return;
      }
      if (document.getElementById("dz-wl-modal")?.classList.contains("open")) {
        closeDzWorklistModal(); return;
      }
      if (document.getElementById("anon-profile-modal")?.style.display === "flex") {
        closeAnonProfileManager(); return;
      }
    }

    // Enter → trigger primary tab action (not in textarea/button/select, no modals open)
    if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
      const tag = document.activeElement?.tagName;
      if (tag === "TEXTAREA" || tag === "BUTTON" || tag === "SELECT" || tag === "A") return;
      const anyModalOpen = [
        () => document.getElementById("confirm-modal")?.classList.contains("open"),
        () => document.getElementById("dwv-overlay")?.style.display === "flex",
        () => document.getElementById("preview-modal")?.style.display !== "none",
        () => document.getElementById("tag-modal")?.classList.contains("open"),
        () => document.getElementById("dz-wl-modal")?.classList.contains("open"),
        () => document.getElementById("anon-profile-modal")?.style.display === "flex",
      ].some(f => f());
      if (anyModalOpen) return;
      const tabActions = {
        cfind:     doCFind,
        dmwl:      doDMWL,
        cstore:    doCStore,
        hl7:       doHL7Send,
        inspector: doInspect,
      };
      const activeTab = localStorage.getItem("activeTab") || "dashboard";
      const fn = tabActions[activeTab];
      if (fn) { e.preventDefault(); fn(); }
    }
  });

  // ── Persist key form fields ──────────────────────────────────────────
  const _FORM_FIELDS_KEY = "pacsadmin_form_fields";
  const _PERSIST_IDS = [
    "cfind-pid","cfind-pname","cfind-acc","cfind-mod",
    "cfind-date-from","cfind-date-to","cfind-suid","cfind-extra-tags",
    "dmwl-pid","dmwl-pname","dmwl-acc","dmwl-mod","dmwl-aet","dmwl-date",
  ];
  // Restore
  try {
    const saved = JSON.parse(localStorage.getItem(_FORM_FIELDS_KEY) || "{}");
    _PERSIST_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el && saved[id] !== undefined) el.value = saved[id];
    });
  } catch { /* ignore */ }
  // Save on any change
  function _saveFormFields() {
    const snap = {};
    _PERSIST_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el) snap[id] = el.value;
    });
    try { localStorage.setItem(_FORM_FIELDS_KEY, JSON.stringify(snap)); } catch { /* ignore */ }
  }
  _PERSIST_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", _saveFormFields);
  });

  // ── Restore theme ────────────────────────────────────────────────────
  const savedTheme = localStorage.getItem("pacsadmin_theme") || "light";
  _applyTheme(savedTheme);

  // ── Restore active tab (after auth+settings loaded to respect advanced tabs) ─
  showTab(localStorage.getItem("activeTab") || "dashboard");

  // ── Resume polling any C-MOVE/C-GET/C-STORE jobs left running before a refresh ─
  resumeTrackedJobs();
})();

