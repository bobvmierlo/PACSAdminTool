// session.js — idle timeout and handling of expired / revoked sessions
//
// The server ends a session after the configured period without activity
// (default 30 min) or when the user's password changed / the account was
// deleted. This file:
//   • sends the browser to the login page as soon as an API call reports
//     that the session is no longer valid, hiding the page first so no
//     patient data stays on screen;
//   • logs out on its own after the same period without mouse/keyboard
//     input, so an unattended workstation does not keep showing data;
//   • tells the server about keyboard/mouse activity (at most once a
//     minute) so typing for a long time without API calls does not expire
//     the session.

(function () {
  const _origFetch = window.fetch.bind(window);
  let _redirecting = false;
  let _lastInput   = Date.now();
  let _lastPing    = Date.now();

  function _toLogin(expired) {
    if (_redirecting) return;
    _redirecting = true;
    document.body.style.visibility = "hidden";
    const next = encodeURIComponent(location.pathname);
    location.href = `/login?next=${next}${expired ? "&expired=1" : ""}`;
  }

  window.fetch = async function (input, init) {
    const res = await _origFetch(input, init);
    if (res.status === 401) {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      if (url.startsWith("/api/") || url.startsWith(location.origin + "/api/")) {
        let reason = "";
        try { reason = (await res.clone().json()).reason || ""; } catch { /* not JSON */ }
        if (reason) _toLogin(reason === "expired");
      }
    }
    return res;
  };

  ["mousemove", "mousedown", "keydown", "wheel", "touchstart"].forEach(ev =>
    window.addEventListener(ev, () => { _lastInput = Date.now(); }, { passive: true }));

  // Called by initAuthUI() once the configured timeout is known.
  window.startIdleLogout = function (minutes) {
    const limitMs = Math.max(1, minutes || 30) * 60000;
    setInterval(async () => {
      const now = Date.now();
      if (now - _lastInput >= limitMs) {
        try { await _origFetch("/logout", { method: "POST" }); } catch { /* ignore */ }
        _toLogin(true);
        return;
      }
      if (_lastInput > _lastPing && now - _lastPing >= 60000) {
        _lastPing = now;
        window.fetch("/api/session/ping", { method: "POST" }).catch(() => {});
      }
    }, 15000);
  };
})();
