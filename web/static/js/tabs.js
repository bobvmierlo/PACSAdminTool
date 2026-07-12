// tabs.js — Tab navigation
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 2. Tab navigation
// ─────────────────────────────────────────────────────────────────

function showTab(name) {
  // If an advanced tab is requested but advanced tabs are hidden, fall back to dashboard
  if (ADVANCED_TABS.includes(name) && !userSettings.show_advanced_tabs) {
    name = "dashboard";
  }

  // Hide all panels and deactivate all buttons
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));

  // Show the chosen panel and mark its button active
  document.getElementById("tab-" + name).classList.add("active");

  // Find the button that triggered this tab and mark it active
  document.querySelectorAll(".tab-btn").forEach(b => {
    if (b.getAttribute("onclick") === `showTab('${name}')`) b.classList.add("active");
  });

  // Update mobile nav label and close the drawer
  const activeBtn = document.querySelector(`.tab-btn[onclick="showTab('${name}')"]`);
  if (activeBtn) {
    const lbl = document.getElementById("mobile-tab-label");
    if (lbl) lbl.textContent = activeBtn.textContent.trim();
  }
  document.getElementById("tab-bar").classList.remove("mobile-open");

  localStorage.setItem("activeTab", name);

  if (name === "logs")      initLogViewer();
  if (name === "dashboard") loadDashboard();
  if (name === "scp")       loadSCPStudies();
  if (name === "dicomize")  dzLoadPresets();
}

function applyAdvancedTabVisibility() {
  const show = userSettings.show_advanced_tabs || false;
  document.querySelectorAll(".tab-btn[data-advanced='true']").forEach(btn => {
    btn.style.display = show ? "" : "none";
  });
  const toggle = document.getElementById("advanced-tabs-toggle");
  if (toggle) {
    toggle.textContent = show ? "\u25BE Advanced" : "\u25B8 Advanced";
    toggle.title = i18n("settings.advanced_tabs_hint");
  }
  // Sync the My Preferences checkbox
  _syncAdvancedTabsCheckbox();
  // If the currently active tab is now hidden, switch to dashboard
  const activeTab = localStorage.getItem("activeTab") || "dashboard";
  if (ADVANCED_TABS.includes(activeTab) && !show) {
    showTab("dashboard");
  }
}

// Called by the "▸ Advanced" button in the tab bar (toggles)
async function toggleAdvancedTabs() {
  userSettings.show_advanced_tabs = !userSettings.show_advanced_tabs;
  _syncAdvancedTabsCheckbox();
  applyAdvancedTabVisibility();
  await _patchUserSettings({ show_advanced_tabs: userSettings.show_advanced_tabs });
}

// Called by the checkbox in My Preferences (reads checkbox state directly)
async function setAdvancedTabsFromCheckbox(cb) {
  userSettings.show_advanced_tabs = cb.checked;
  applyAdvancedTabVisibility();
  await _patchUserSettings({ show_advanced_tabs: userSettings.show_advanced_tabs });
}

function _syncAdvancedTabsCheckbox() {
  const cb = document.getElementById("pref-show-advanced-tabs");
  if (cb) cb.checked = userSettings.show_advanced_tabs || false;
}

function toggleMobileNav() {
  document.getElementById("tab-bar").classList.toggle("mobile-open");
}

function showHL7Tab(sub) {
  document.getElementById("hl7-send-panel").style.display = sub === "send" ? "block" : "none";
  document.getElementById("hl7-recv-panel").style.display = sub === "recv" ? "block" : "none";
  document.getElementById("hl7-send-btn").classList.toggle("active", sub === "send");
  document.getElementById("hl7-recv-btn").classList.toggle("active", sub === "recv");
}

