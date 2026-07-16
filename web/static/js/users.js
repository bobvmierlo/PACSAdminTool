// users.js — General utilities, user management, auth UI helpers
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 18. General utilities
// ─────────────────────────────────────────────────────────────────

// Append a line to a log box div
function appendLog(boxId, ts, message, level = "dim") {
  const box  = document.getElementById(boxId);
  if (!box) return;
  const span = document.createElement("span");
  span.className = "log-" + level;
  span.textContent = `[${ts}] ${message}\n`;
  box.appendChild(span);
  if (box.dataset.autoscroll !== "false") box.scrollTop = box.scrollHeight;
}

function clearTable(tbodyId) {
  document.getElementById(tbodyId).innerHTML = "";
}

// Current time as HH:MM:SS string
function now() {
  return new Date().toTimeString().slice(0, 8);
}

// Escape HTML special characters to prevent XSS when inserting user/server data
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Trigger a browser download of a text string as a file
function downloadText(filename, content, mimeType = "text/plain") {
  const a   = document.createElement("a");
  a.href    = URL.createObjectURL(new Blob([content], { type: mimeType }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ─────────────────────────────────────────────────────────────────
// User management (Settings tab)
// ─────────────────────────────────────────────────────────────────

async function loadUsers() {
  const res = await fetch("/api/users");
  if (!res.ok) return;
  const data = await res.json();
  if (!data.ok) return;
  document.getElementById("user-mgmt-card").style.display = "";
  const tbody = document.getElementById("users-tbody");
  tbody.innerHTML = "";
  data.users.forEach(u => {
    const tr = document.createElement("tr");
    const created = u.created_at ? u.created_at.slice(0, 10) : "";
    // Own password is changed via My Preferences (needs current password)
    const resetBtn = u.username === (_currentUser?.username)
      ? ""
      : `<button class="btn" style="padding:2px 8px; font-size:11px; margin-right:6px"
          onclick="resetUserPassword('${u.username}')">${escapeHtml(i18n("settings.reset_password"))}</button>`;
    tr.innerHTML =
      `<td>${u.username}</td><td>${u.role}</td><td>${created}</td>` +
      `<td>${resetBtn}<button class="btn danger" style="padding:2px 8px; font-size:11px"
          onclick="deleteUser('${u.username}', this)">Delete</button></td>`;
    tbody.appendChild(tr);
  });
}

async function addUser() {
  const username = document.getElementById("new-user-name").value.trim();
  const password = document.getElementById("new-user-pass").value;
  const role     = document.getElementById("new-user-role").value;
  const status   = document.getElementById("new-user-status");
  if (!username || !password) { status.textContent = "Username and password required."; status.style.color = "#dc2626"; return; }
  const res  = await fetch("/api/users", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ username, password, role }),
  });
  const data = await res.json();
  if (data.ok) {
    status.textContent = `User '${username}' created.`;
    status.style.color = "#16a34a";
    document.getElementById("new-user-name").value = "";
    document.getElementById("new-user-pass").value = "";
    loadUsers();
  } else {
    status.textContent = data.error || "Failed.";
    status.style.color = "#dc2626";
  }
}

async function deleteUser(username, btn) {
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete user '${username}'?`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  btn.disabled = true;
  const res  = await fetch(`/api/users/${encodeURIComponent(username)}`, { method: "DELETE" });
  const data = await res.json();
  if (data.ok) {
    loadUsers();
  } else {
    toast(data.error || "Delete failed.", "err");
    btn.disabled = false;
  }
}

// Admin: reset another user's password via a prompt dialog
async function resetUserPassword(username) {
  const newPass = await _dialog({
    title:   i18n("settings.reset_password"),
    message: i18n("settings.reset_password_prompt", {username}),
    input:   { defaultValue: "", placeholder: "min 8 chars", type: "password" },
    buttons: [
      { text: i18n("common.ok"),     value: "__input__", className: "btn primary" },
      { text: i18n("common.cancel"), value: null,        className: "btn" },
    ],
  });
  if (newPass === null || newPass === undefined) return;
  if (newPass.length < 8) { toast(i18n("settings.pw_too_short"), "err"); return; }
  const res  = await fetch(`/api/users/${encodeURIComponent(username)}/password`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ password: newPass }),
  });
  const data = await res.json();
  if (data.ok) toast(i18n("settings.pw_reset_ok", {username}), "ok");
  else         toast(data.error || "Failed.", "err");
}

// ─────────────────────────────────────────────────────────────────
// Change my own password (My Preferences card)
// ─────────────────────────────────────────────────────────────────

async function changeMyPassword() {
  const current = document.getElementById("my-pw-current").value;
  const newPass = document.getElementById("my-pw-new").value;
  const confirm = document.getElementById("my-pw-confirm").value;
  const status  = document.getElementById("my-pw-status");
  const fail = msg => { status.textContent = msg; status.style.color = "#dc2626"; };
  if (!_currentUser)          { fail("Not signed in."); return; }
  if (!current)               { fail(i18n("settings.pw_current_required")); return; }
  if (newPass.length < 8)     { fail(i18n("settings.pw_too_short")); return; }
  if (newPass !== confirm)    { fail(i18n("settings.pw_mismatch")); return; }
  const res  = await fetch(`/api/users/${encodeURIComponent(_currentUser.username)}/password`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ password: newPass, current_password: current }),
  });
  const data = await res.json();
  if (data.ok) {
    status.textContent = i18n("settings.pw_changed");
    status.style.color = "#16a34a";
    ["my-pw-current", "my-pw-new", "my-pw-confirm"].forEach(id => {
      document.getElementById(id).value = "";
    });
  } else {
    fail(data.error || "Failed.");
  }
}

// ─────────────────────────────────────────────────────────────────
// Auth UI helpers
// ─────────────────────────────────────────────────────────────────

function _applyAdminSettingsUI() {
  const wrap = document.getElementById("admin-settings-wrap");
  if (!wrap) return;
  // Read-only when a non-admin user is logged in.
  // null _currentUser means auth is not configured → full access.
  const readOnly = _currentUser !== null && _currentUser.role !== "admin";
  const notice = document.getElementById("admin-settings-notice");
  if (notice) notice.style.display = readOnly ? "flex" : "none";
  wrap.querySelectorAll("input, select, textarea, button").forEach(el => {
    el.disabled = readOnly;
  });
}

async function initAuthUI() {
  try {
    const meRes = await fetch("/api/me");
    if (meRes.ok) {
      const me = await meRes.json();
      _currentUser = me;
      const el = document.getElementById("header-user");
      el.textContent = me.username;
      el.style.display = "";
      document.getElementById("btn-logout").style.display = "";
      // Load user management table for admins
      if (me.role === "admin") loadUsers();

      // Fetch and apply per-user settings
      try {
        const settingsRes = await fetch("/api/user/settings");
        if (settingsRes.ok) {
          const sd = await settingsRes.json();
          if (sd.ok) userSettings = sd.settings;
        }
      } catch { /* ignore – keep defaults */ }

      // Refresh preset dropdowns now that userSettings is populated
      refreshAllPresetDropdowns();
      dwRefreshPresets();
    }
  } catch { /* auth not active or request failed – ignore */ }

  // Apply advanced tab visibility (runs regardless of auth state)
  applyAdvancedTabVisibility();
  renderMyPreferences();
  _applyAdminSettingsUI();
}

async function doLogout() {
  await fetch("/logout", { method: "POST" });
  location.href = "/login";
}

