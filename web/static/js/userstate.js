// userstate.js — per-user UI state kept on the server
//
// C-FIND query history, sent-HL7 history and the remembered C-FIND/DMWL
// search fields can contain patient names and IDs. They used to live in
// localStorage, which leaves them on the workstation for whoever uses the
// browser next. They are now stored per user on the server and cached here
// for synchronous reads. Anything still in localStorage from older versions
// is moved to the server once and then removed from the browser.

const _USER_STATE_LEGACY_KEYS = {
  cfind_history:   "pacsadmin_cfind_history",
  hl7_out_history: "pacsadmin_hl7_hist_out",
  form_fields:     "pacsadmin_form_fields",
};

let _userState = {};
const _userStateTimers = {};

async function userStateLoad() {
  try {
    const res = await fetch("/api/user/state");
    if (res.ok) {
      const data = await res.json();
      if (data.ok) _userState = data.state || {};
    }
  } catch { /* server unreachable — start empty */ }

  for (const [key, lsKey] of Object.entries(_USER_STATE_LEGACY_KEYS)) {
    let raw = null;
    try { raw = localStorage.getItem(lsKey); } catch { /* storage blocked */ }
    if (raw === null) continue;
    try {
      if (_userState[key] === undefined) userStateSet(key, JSON.parse(raw), true);
    } catch { /* unreadable legacy value — drop it */ }
    try { localStorage.removeItem(lsKey); } catch { /* ignore */ }
  }
  // Inbound HL7 history has been server-side for a while; drop old copies.
  try { localStorage.removeItem("pacsadmin_hl7_hist_in"); } catch { /* ignore */ }
}

function userStateGet(key, fallback) {
  return _userState[key] !== undefined ? _userState[key] : fallback;
}

// Update the cache immediately; write to the server shortly after (so a
// burst of changes, e.g. typing in a remembered field, is one request).
function userStateSet(key, value, immediate = false) {
  _userState[key] = value;
  clearTimeout(_userStateTimers[key]);
  const send = () => fetch(`/api/user/state/${encodeURIComponent(key)}`, {
    method:  "PUT",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ value }),
  }).catch(() => {});
  if (immediate) send();
  else _userStateTimers[key] = setTimeout(send, 400);
}
