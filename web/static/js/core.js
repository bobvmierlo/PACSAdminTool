// core.js — i18n, date/time helpers, dialogs, toasts, clipboard, AE health, dark mode, log-box + input helpers
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 0. Internationalisation (i18n)
// ─────────────────────────────────────────────────────────────────

let _i18n = {};  // full translation dict for the current language

/** Resolve a dot-notation key like "cfind.run" from the _i18n dict. */
function i18n(key, kwargs) {
  const parts = key.split(".");
  let val = _i18n;
  for (const p of parts) {
    if (val && typeof val === "object") val = val[p];
    else return key;
  }
  if (typeof val !== "string") return key;
  if (kwargs) {
    for (const [k, v] of Object.entries(kwargs)) {
      val = val.split(`{${k}}`).join(v);
    }
  }
  return val;
}

/** Apply translations to all elements with data-i18n attributes. */
function applyTranslations() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    const text = i18n(key);
    if (text !== key) el.textContent = text;
  });
  // Re-apply the WebSocket status label so language changes don't reset it
  // to "connecting…". _applyWsStatus is defined in the Socket.IO section.
  if (typeof _applyWsStatus === "function") {
    if (typeof socket !== "undefined" && socket.connected) {
      _applyWsStatus("connected");
    } else if (typeof socket !== "undefined" && !socket.connected) {
      // Could be disconnected or still trying to connect on first load
      _applyWsStatus(document.getElementById("offline-overlay")?.classList.contains("visible")
        ? "reconnecting" : "connecting");
    }
  }
  document.querySelectorAll("[data-i18n-html]").forEach(el => {
    const key = el.getAttribute("data-i18n-html");
    const text = i18n(key);
    if (text !== key) el.innerHTML = text;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    const key = el.getAttribute("data-i18n-placeholder");
    const text = i18n(key);
    if (text !== key) el.placeholder = text;
  });
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    const key = el.getAttribute("data-i18n-title");
    const text = i18n(key);
    if (text !== key) el.title = text;
  });
  // Update page title
  const titleKey = document.querySelector("title")?.getAttribute("data-i18n");
  if (titleKey) document.title = i18n(titleKey);
}

/** Fetch translations from the server and apply them. */
async function loadTranslations() {
  try {
    const res = await fetch("/api/translations");
    _i18n = await res.json();
    applyTranslations();
  } catch (e) {
    console.warn("Could not load translations:", e);
  }
}

/** Populate the language selector in Settings. */
async function loadLanguageOptions() {
  try {
    const res = await fetch("/api/locale/languages");
    const langs = await res.json();
    const sel = document.getElementById("set-language");
    sel.innerHTML = "";
    langs.forEach(l => {
      const opt = document.createElement("option");
      opt.value = l.code;
      opt.textContent = l.name;
      sel.appendChild(opt);
    });
    // Set current language
    const curRes = await fetch("/api/locale/current");
    const cur = await curRes.json();
    sel.value = cur.language;
  } catch (e) {
    console.warn("Could not load languages:", e);
  }
}

// ─────────────────────────────────────────────────────────────────
// 0b. Date / Time helpers
// ─────────────────────────────────────────────────────────────────

/** Today as YYYY-MM-DD, suitable for setting an <input type="date"> value. */
function todayInputDate() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

/** YYYY-MM-DD (HTML date input) → YYYYMMDD (DICOM). Returns "" when empty. */
function dateToDisom(val) { return val ? val.replace(/-/g, "") : ""; }

/** HH:MM[:SS] (HTML time input) → HHMMSS (DICOM). Returns "" when empty. */
function timeToDisom(val) {
  if (!val) return "";
  const p = val.split(":");
  return (p[0]||"00").padStart(2,"0") + (p[1]||"00").padStart(2,"0") + (p[2]||"00").padStart(2,"0");
}

/** YYYYMMDD (DICOM) → YYYY-MM-DD (HTML date input). Returns "" when invalid. */
function dicomDateToInput(val) {
  return (val && val.length >= 8) ? `${val.slice(0,4)}-${val.slice(4,6)}-${val.slice(6,8)}` : "";
}

/** HHMMSS (DICOM) → HH:MM:SS (HTML time input). Returns "" when invalid. */
function dicomTimeToInput(val) {
  if (!val || val.length < 4) return "";
  return `${val.slice(0,2)}:${val.slice(2,4)}:${(val.slice(4,6)||"00")}`;
}

/**
 * Build a DICOM date-range string from the two C-FIND date pickers.
 * Returns: "" | "YYYYMMDD" | "YYYYMMDD-YYYYMMDD" | "YYYYMMDD-" | "-YYYYMMDD"
 */
function cfindDateRange() {
  const from = dateToDisom(document.getElementById("cfind-date-from").value);
  const to   = dateToDisom(document.getElementById("cfind-date-to").value);
  if (from && to && from === to) return from;
  if (from && to) return `${from}-${to}`;
  if (from)       return `${from}-`;
  if (to)         return `-${to}`;
  return "";
}

// ─────────────────────────────────────────────────────────────────
// 0c. Custom confirm / choice dialog
// ─────────────────────────────────────────────────────────────────

let _dialogResolve = null;

/**
 * Show a branded modal dialog instead of the native browser confirm/prompt.
 * Returns a Promise that resolves to the chosen button's `value`.
 * Resolves to `null` when dismissed via backdrop click or Escape.
 *
 * @param {object}   opts
 * @param {string}   opts.title      - Dialog title
 * @param {string}   [opts.message]  - Body text (supports newlines)
 * @param {object[]} opts.buttons    - Array of {text, value, className}.
 *                                     Use value "__input__" to return the input field's current text.
 * @param {object}   [opts.input]    - When present, shows a text field: {placeholder, defaultValue}
 */
function _dialog({ title, message = "", buttons, input }) {
  return new Promise(resolve => {
    // Dismiss any previously open dialog without resolving to a value
    if (_dialogResolve) { _dialogResolve(null); _dialogResolve = null; }
    _dialogResolve = resolve;

    document.getElementById("confirm-modal-title").textContent   = title;
    document.getElementById("confirm-modal-message").textContent = message;
    const msgEl = document.getElementById("confirm-modal-message");
    msgEl.style.display = message ? "" : "none";

    const inputEl = document.getElementById("confirm-modal-input");
    if (input) {
      inputEl.type        = input.type         || "text";
      inputEl.value       = input.defaultValue || "";
      inputEl.placeholder = input.placeholder  || "";
      inputEl.style.display = "";
      // Submit on Enter key inside the input
      inputEl.onkeydown = e => {
        if (e.key === "Enter") {
          e.preventDefault();
          // Click the first button (primary action)
          document.getElementById("confirm-modal-buttons").querySelector("button")?.click();
        }
      };
      requestAnimationFrame(() => inputEl.focus());
    } else {
      inputEl.type = "text";
      inputEl.style.display = "none";
      inputEl.onkeydown = null;
    }

    const container = document.getElementById("confirm-modal-buttons");
    container.innerHTML = "";
    buttons.forEach(({ text, value, className = "btn" }) => {
      const btn = document.createElement("button");
      btn.className   = className;
      btn.textContent = text;
      btn.onclick = () => {
        document.getElementById("confirm-modal").classList.remove("open");
        const r = _dialogResolve; _dialogResolve = null;
        r(value === "__input__" ? inputEl.value.trim() : value);
      };
      container.appendChild(btn);
    });

    document.getElementById("confirm-modal").classList.add("open");
  });
}

/** Dismiss the dialog as a cancellation (value = null). */
function _dialogCancel() {
  const modal = document.getElementById("confirm-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  const r = _dialogResolve; _dialogResolve = null;
  if (r) r(null);
}

// ─────────────────────────────────────────────────────────────────
// 0d. Toast notifications
// ─────────────────────────────────────────────────────────────────

/**
 * Show a non-blocking toast notification.
 * @param {string} message
 * @param {"ok"|"err"|"warn"|"info"|"dim"} level
 * @param {number} duration  milliseconds before auto-dismiss
 */
function toast(message, level = "dim", duration = 4000) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast toast-${level}`;
  el.textContent = message;
  // Click to dismiss early
  el.style.cursor = "pointer";
  el.addEventListener("click", () => dismiss());
  container.appendChild(el);
  const timer = setTimeout(dismiss, duration);
  function dismiss() {
    clearTimeout(timer);
    el.classList.add("toast-out");
    el.addEventListener("animationend", () => el.remove(), { once: true });
  }
}

// ─────────────────────────────────────────────────────────────────
// 0d. Clipboard copy helper
// ─────────────────────────────────────────────────────────────────

async function copyToClipboard(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast(i18n("common.copied"), "ok", 2000);
  } catch {
    // Fallback for non-HTTPS contexts
    try {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      toast(i18n("common.copied"), "ok", 2000);
    } catch { toast(i18n("common.copy_failed"), "err", 2500); }
  }
}

// ─────────────────────────────────────────────────────────────────
// 0e. DICOM date display formatting
// ─────────────────────────────────────────────────────────────────

/** Format YYYYMMDD for display as DD-MM-YYYY. Returns raw value if not 8 digits. */
function formatDicomDate(val) {
  if (!val || val.length !== 8 || !/^\d{8}$/.test(val)) return val || "";
  return `${val.slice(6,8)}-${val.slice(4,6)}-${val.slice(0,4)}`;
}

// ─────────────────────────────────────────────────────────────────
// 0f. AE Title character counter
// ─────────────────────────name─────────────────────────────────────

/** Wrap an AE title input with a live character counter (max 16 per DICOM). */
function wrapAETitleInput(input) {
  if (!input || input.dataset.aeTitleWrapped) return;
  input.dataset.aeTitleWrapped = "1";
  input.maxLength = 16;
  const wrap = document.createElement("div");
  wrap.className = "ae-title-wrap";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const counter = document.createElement("span");
  counter.className = "ae-title-counter";
  wrap.appendChild(counter);
  const update = () => {
    const len = input.value.length;
    counter.textContent = `${len}/16`;
    counter.classList.toggle("warn", len >= 13);
  };
  input.addEventListener("input", update);
  update();
}

// ─────────────────────────────────────────────────────────────────
// 0g. AE health tracking
// ─────────────────────────────────────────────────────────────────

const _aeHealth = {};  // key → "ok" | "err" | "busy" | null

function _aeKey(ae) { return `${ae.ae_title}@${ae.host}:${ae.port}`; }

function _setAEHealth(ae, state) {
  const key = _aeKey(ae);
  _aeHealth[key] = state;
  // Update dots already tagged with this key (e.g. from a previous loadPreset/doEcho)
  document.querySelectorAll(`.ae-dot[data-ae-key="${key}"]`).forEach(d => {
    d.className = "ae-dot" + (state ? " " + state : "");
    d.title = state === "ok" ? "Reachable" : state === "err" ? "Unreachable" : "";
  });
  // Also sweep selector dots whose current input values match this AE
  // (handles the case where a preset is loaded but data-ae-key wasn't yet set,
  //  or a user typed in fields matching a freshly-pinged AE)
  ["cfind","cstore","dmwl","commit","iocm"].forEach(prefix => {
    const aeEl   = document.getElementById(prefix + "-ae");
    const hostEl = document.getElementById(prefix + "-host");
    const portEl = document.getElementById(prefix + "-port");
    const dot    = document.getElementById(prefix + "-ae-dot");
    if (!aeEl || !hostEl || !portEl || !dot) return;
    if (_aeKey({ ae_title: aeEl.value, host: hostEl.value, port: portEl.value }) === key) {
      dot.dataset.aeKey = key;
      dot.className = "ae-dot" + (state ? " " + state : "");
      dot.title = state === "ok" ? "Reachable" : state === "err" ? "Unreachable" : "";
    }
  });
}

/** Run a C-ECHO for preset and update the health dot. */
async function pingPreset(ae) {
  _setAEHealth(ae, "busy");
  try {
    const res  = await fetch("/api/dicom/echo", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify(ae),
    });
    const data = await res.json();
    _setAEHealth(ae, data.ok ? "ok" : "err");
  } catch { _setAEHealth(ae, "err"); }
}

// ─────────────────────────────────────────────────────────────────
// 0h. Dark mode
// ─────────────────────────────────────────────────────────────────

function _applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("pacsadmin_theme", theme);
  const btn = document.getElementById("dark-mode-btn");
  if (btn) btn.textContent = theme === "dark" ? "☀ Light mode" : "☾ Dark mode";
  const hdrBtn = document.getElementById("header-theme-btn");
  if (hdrBtn) hdrBtn.textContent = theme === "dark" ? "☀" : "☾";
}

function toggleDarkMode() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  _applyTheme(current === "dark" ? "light" : "dark");
}

// ─────────────────────────────────────────────────────────────────
// 0i. Log box auto-scroll management
// ─────────────────────────────────────────────────────────────────

/** Toggle auto-scroll for a specific log box. */
function toggleLogScroll(boxId, checked) {
  const box = document.getElementById(boxId);
  if (!box) return;
  box.dataset.autoscroll = checked ? "true" : "false";
  if (checked) box.scrollTop = box.scrollHeight;
}

// ─────────────────────────────────────────────────────────────────
// 0j. Clearable input helpers
// ─────────────────────────────────────────────────────────────────

/** Wrap an input in a clearable-wrap div with a × clear button. */
function makeClearable(input) {
  if (!input || input.dataset.clearableWrapped) return;
  input.dataset.clearableWrapped = "1";
  const wrap = document.createElement("div");
  wrap.className = "clearable-wrap";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const btn = document.createElement("button");
  btn.className = "inp-clear";
  btn.type = "button";
  btn.textContent = "×";
  btn.title = "Clear";
  btn.addEventListener("click", () => {
    input.value = "";
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.focus();
    btn.style.display = "none";
  });
  wrap.appendChild(btn);
  const update = () => { btn.style.display = input.value ? "block" : "none"; };
  input.addEventListener("input", update);
  update();
}

