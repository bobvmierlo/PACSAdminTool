// dashboard.js — Dashboard tab (batch echo, service status, recent audit)
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// Dashboard
// ─────────────────────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const res  = await fetch("/api/dashboard");
    const data = await res.json();
    if (!data.ok) return;

    // Services
    const scpEl  = document.getElementById("dash-scp-status");
    const hl7El  = document.getElementById("dash-hl7-status");
    scpEl.className = data.scp_running ? "badge-ok" : "badge-err";
    scpEl.textContent = data.scp_running
      ? `Running (${data.scp_ae || ""})`
      : "Stopped";
    hl7El.className   = data.hl7_running ? "badge-ok" : "badge-err";
    hl7El.textContent = data.hl7_running ? "Running" : "Stopped";

    // AE table — combine system presets (from server) with user presets
    const tbody = document.getElementById("dash-ae-tbody");
    tbody.innerHTML = "";
    const noPresets = document.getElementById("dash-no-presets");
    const wrap      = document.getElementById("dash-ae-wrap");

    const sysAEs  = data.remote_aes      || [];
    const userAEs = userSettings.remote_aes || [];
    const allAEs  = [
      ...sysAEs.map(ae  => ({ ...ae,  _src: "sys" })),
      ...userAEs.map(ae => ({ ...ae,  _src: "usr" })),
    ];

    if (allAEs.length === 0) {
      noPresets.style.display = "";
      wrap.style.display      = "none";
    } else {
      noPresets.style.display = "none";
      wrap.style.display      = "";
      allAEs.forEach(ae => {
        const rowId   = `dash-ae-row-${ae._src}-${ae.ae_title}`;
        const badgeId = `dash-ae-badge-${ae._src}-${ae.ae_title}`;
        const msgId   = `dash-ae-msg-${ae._src}-${ae.ae_title}`;
        const srcBadge = ae._src === "usr"
          ? `<span style="font-size:10px;color:#888;margin-left:4px">(mine)</span>` : "";
        const tr = document.createElement("tr");
        tr.id    = rowId;
        tr.dataset.aeTitle = ae.ae_title;
        tr.dataset.host    = ae.host;
        tr.dataset.port    = ae.port;
        tr.dataset.src     = ae._src;
        tr.innerHTML = `
          <td>${escapeHtml(ae.name || "")}${srcBadge}</td>
          <td>${escapeHtml(ae.ae_title)}</td>
          <td>${escapeHtml(ae.host)}</td>
          <td>${ae.port}</td>
          <td><span class="badge-pending" id="${badgeId}">–</span></td>
          <td id="${msgId}" style="font-size:12px; color:#888"></td>`;
        tbody.appendChild(tr);
      });
    }

    // DICOMweb health section
    const sysDW  = data.dicomweb_presets      || appConfig.dicomweb_presets   || [];
    const userDW = userSettings.dicomweb_presets || [];
    const allDW  = [
      ...sysDW.map(p  => ({ ...p, _src: "sys" })),
      ...userDW.map(p => ({ ...p, _src: "usr" })),
    ];
    const dwCard  = document.getElementById("dash-dw-card");
    const dwTbody = document.getElementById("dash-dw-tbody");
    dwTbody.innerHTML = "";
    if (allDW.length === 0) {
      dwCard.style.display = "none";
    } else {
      dwCard.style.display = "";
      allDW.forEach((p, i) => {
        const srcBadge = p._src === "usr"
          ? `<span style="font-size:10px;color:#888;margin-left:4px">(mine)</span>` : "";
        const tr = document.createElement("tr");
        tr.id = `dash-dw-row-${i}`;
        tr.dataset.dwIndex = i;
        tr.innerHTML = `
          <td>${escapeHtml(p.name || "")}${srcBadge}</td>
          <td style="font-size:11px;word-break:break-all">${escapeHtml(p.base_url || "")}</td>
          <td><span class="badge-pending" id="dash-dw-badge-${i}">–</span></td>
          <td id="dash-dw-msg-${i}" style="font-size:12px; color:#888"></td>`;
        dwTbody.appendChild(tr);
      });
    }

    // Recent audit
    const auditTbody = document.getElementById("dash-audit-tbody");
    auditTbody.innerHTML = "";
    (data.recent_audit || []).forEach(entry => {
      const tr  = document.createElement("tr");
      const ts  = (entry.ts || "").replace("T", " ").substring(0, 19);
      const res = entry.result || "";
      tr.innerHTML = `
        <td style="white-space:nowrap;font-size:11px">${ts}</td>
        <td>${entry.user || "–"}</td>
        <td style="font-size:11px">${entry.ip || ""}</td>
        <td>${entry.event || ""}</td>
        <td><span class="${res === "ok" ? "badge-ok" : "badge-err"}">${res}</span></td>`;
      auditTbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Dashboard load error:", e);
  }
}

async function doBatchEcho() {
  const btn = document.getElementById("batch-echo-btn");
  btn.disabled = true;
  btn.textContent = "Testing…";
  // Clear existing results
  document.querySelectorAll("[id^='dash-ae-badge-']").forEach(el => {
    el.className   = "badge-pending";
    el.textContent = "…";
  });
  // Test system presets via server batch
  try {
    await fetch("/api/dicom/echo/batch", { method: "POST" });
  } finally {
    // btn re-enabled when batch_echo_done fires (or we do it here for user-only case)
  }
  // Test user presets directly from the frontend (one at a time)
  const userAEs = userSettings.remote_aes || [];
  for (const ae of userAEs) {
    const badge = document.getElementById(`dash-ae-badge-usr-${ae.ae_title}`);
    const msg   = document.getElementById(`dash-ae-msg-usr-${ae.ae_title}`);
    if (badge) { badge.className = "badge-pending"; badge.textContent = "…"; }
    try {
      const res  = await fetch("/api/dicom/echo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ae_title: ae.ae_title, host: ae.host, port: ae.port }),
      });
      const d = await res.json();
      if (badge) { badge.className = d.ok ? "badge-ok" : "badge-err"; badge.textContent = d.ok ? "OK" : "Fail"; }
      if (msg)   msg.textContent = d.message || "";
      _setAEHealth(ae, d.ok ? "ok" : "err");
    } catch {
      if (badge) { badge.className = "badge-err"; badge.textContent = "Err"; }
    }
  }
}

// SocketIO handlers for batch echo results (system presets only)
socket.on("batch_echo_result", data => {
  // Try both sys- prefixed ID (new) and legacy un-prefixed (fallback)
  const badge = document.getElementById(`dash-ae-badge-sys-${data.ae_title}`)
             || document.getElementById(`dash-ae-badge-${data.ae_title}`);
  const msg   = document.getElementById(`dash-ae-msg-sys-${data.ae_title}`)
             || document.getElementById(`dash-ae-msg-${data.ae_title}`);
  if (badge) {
    badge.className   = data.ok ? "badge-ok" : "badge-err";
    badge.textContent = data.ok ? "OK" : "Fail";
  }
  if (msg) msg.textContent = data.message || "";
  const ae = (appConfig.remote_aes || []).find(a => a.ae_title === data.ae_title);
  if (ae) _setAEHealth(ae, data.ok ? "ok" : "err");
});

socket.on("batch_echo_done", () => {
  const btn = document.getElementById("batch-echo-btn");
  if (btn) {
    btn.disabled = false;
    btn.textContent = i18n("dashboard.test_all") || "Test All AEs";
  }
});

async function doBatchDWTest() {
  const btn = document.getElementById("batch-dw-btn");
  btn.disabled = true;
  btn.textContent = "Testing…";
  document.querySelectorAll("[id^='dash-dw-badge-']").forEach(el => {
    el.className = "badge-pending"; el.textContent = "…";
  });
  const sysDW  = appConfig.dicomweb_presets    || [];
  const userDW = userSettings.dicomweb_presets || [];
  const allDW  = [...sysDW, ...userDW];
  for (let i = 0; i < allDW.length; i++) {
    const p     = allDW[i];
    const badge = document.getElementById(`dash-dw-badge-${i}`);
    const msg   = document.getElementById(`dash-dw-msg-${i}`);
    try {
      const res = await fetch("/api/dicomweb/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: p.base_url, auth_type: p.auth_type || "none",
          username: p.username || "", password: p.password || "", token: p.token || "",
        }),
      });
      const d = await res.json();
      if (badge) { badge.className = d.ok ? "badge-ok" : "badge-err"; badge.textContent = d.ok ? "OK" : "Fail"; }
      if (msg)   msg.textContent = d.message || (d.ok ? "" : d.error || "Failed");
    } catch (e) {
      if (badge) { badge.className = "badge-err"; badge.textContent = "Err"; }
      if (msg)   msg.textContent = String(e);
    }
  }
  btn.disabled = false;
  btn.textContent = i18n("dashboard.test_all_dw") || "Test All DICOMweb";
}

