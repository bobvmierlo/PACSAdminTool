// updater.js — Update notification banner / self-update
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────────────────
// Update notification
// ─────────────────────────────────────────────────────────────────────────────

let _updInfo          = null;   // latest /api/check-update response
let _updPollTimer     = null;   // timer for polling download progress
let _updInstalling    = false;  // true while waiting for a restart after install

async function checkForUpdate(force = false) {
  const url = force ? "/api/check-update?force=1" : "/api/check-update";
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const info = await res.json();
    _updInfo = info;
    if (info.has_update) {
      _showUpdateBanner(info);
      _showUpdateAboutCard(info);
    }
    return info;
  } catch (_) { /* silently ignore – no internet, no problem */ }
  return null;
}

async function updCheckNow() {
  const btn    = document.getElementById("btn-check-update");
  const status = document.getElementById("upd-check-status");
  btn.disabled = true;
  btn.querySelector("span").textContent = i18n("update.checking");
  status.textContent = "";

  const info = await checkForUpdate(true);

  btn.disabled = false;
  btn.querySelector("span").textContent = i18n("update.check_btn");

  if (!info) {
    status.textContent = i18n("update.status_no_github");
    status.style.color = "#dc2626";
  } else if (info.has_update) {
    status.textContent = i18n("update.status_available", { version: info.latest_version });
    status.style.color = "#15803d";
  } else if (!info.error) {
    status.textContent = i18n("update.status_uptodate");
    status.style.color = "#15803d";
  } else {
    status.textContent = i18n("update.status_failed");
    status.style.color = "#dc2626";
  }

  // Clear the status label after 5 s
  setTimeout(() => { status.textContent = ""; }, 5000);
}

function _updateDockerCmd() {
  // Returns the docker pull+restart snippet as a one-liner string.
  return "docker compose pull && docker compose up -d";
}

function _showUpdateBanner(info) {
  const banner = document.getElementById("update-banner");
  if (!banner) return;
  document.getElementById("upd-headline").textContent =
    i18n("update.headline", { version: info.latest_version });

  if (info.deployment === "docker") {
    document.getElementById("upd-subline").textContent =
      i18n("update.subline_docker");
    // Replace the "View Release" button with a docker-specific one
    const releaseBtn = document.getElementById("upd-btn-release");
    releaseBtn.textContent = i18n("update.btn_docker_how");
    releaseBtn.onclick = () => { updDismiss(); showTab("about"); };
    releaseBtn.style.display = "";
  } else {
    document.getElementById("upd-subline").textContent =
      i18n("update.subline_running", { version: info.current_version });
    if (info.can_auto_update) {
      document.getElementById("upd-btn-download").style.display = "";
    }
    document.getElementById("upd-btn-release").style.display = "";
  }

  banner.classList.add("visible");
}

function _showUpdateAboutCard(info) {
  const card = document.getElementById("about-update-card");
  if (!card) return;
  document.getElementById("auc-title").textContent =
    i18n("update.card_title_version", { version: info.latest_version });
  if (info.release_notes) {
    document.getElementById("auc-notes").textContent = info.release_notes;
  }

  if (info.deployment === "docker") {
    // Replace button row with Docker pull instructions
    const btns = card.querySelector(".auc-btns");
    btns.innerHTML =
      `<div style="font-size:12px; color:#374151; line-height:1.6">
        <strong>To update, pull the new image and restart the container:</strong><br>
        <code style="display:inline-block; margin-top:6px; padding:6px 10px;
                     background:#1e293b; color:#e2e8f0; border-radius:4px;
                     font-size:11px; letter-spacing:0.02em; user-select:all"
              title="Click to copy" onclick="navigator.clipboard.writeText('${_updateDockerCmd()}').then(()=>{this.title='Copied!';setTimeout(()=>this.title='Click to copy',2000)})"
        >${_updateDockerCmd()}</code>
      </div>
      <button class="auc-btn auc-btn-secondary" style="margin-top:8px"
              onclick="updOpenRelease()">${i18n("update.btn_release_notes")}</button>`;
  } else {
    if (info.can_auto_update) {
      document.getElementById("auc-btn-download").style.display = "";
    }
    document.getElementById("auc-btn-release").style.display = "";
  }

  card.classList.add("visible");
}

function updDismiss() {
  const banner = document.getElementById("update-banner");
  if (banner) banner.classList.remove("visible");
}

function updOpenRelease() {
  if (_updInfo && _updInfo.release_url) {
    window.open(_updInfo.release_url, "_blank", "noopener,noreferrer");
  }
}

async function updDownload() {
  if (!_updInfo) return;

  // Switch to progress view
  document.getElementById("upd-btn-download").style.display = "none";
  document.getElementById("auc-btn-download").style.display = "none";
  document.getElementById("upd-progress-wrap").style.display = "";
  document.getElementById("upd-btn-release").style.display = "none";
  document.getElementById("auc-btn-release").style.display = "none";
  document.getElementById("upd-headline").textContent = i18n("update.downloading");
  document.getElementById("auc-title").textContent     = i18n("update.downloading_card");

  try {
    const res  = await fetch("/api/apply-update", { method: "POST" });
    const data = await res.json();
    if (!data.ok) {
      _updShowError(data.error || "Download failed.");
      return;
    }
    // Poll the download state
    _updPollTimer = setInterval(_updPollProgress, 800);
  } catch (e) {
    _updShowError("Network error: " + e.message);
  }
}

async function _updPollProgress() {
  // Progress is pushed via socket.on("update_ready") when complete.
  // This function is kept as a placeholder in case polling is needed in the future.
}

function _onUpdateReady(data) {
  if (_updPollTimer) { clearInterval(_updPollTimer); _updPollTimer = null; }

  // Progress: 100%
  document.getElementById("upd-progress-bar").style.width = "100%";
  document.getElementById("upd-progress-wrap").style.display = "none";

  document.getElementById("upd-headline").textContent =
    i18n("update.ready", { version: (data && data.latest_version) || "new" });
  document.getElementById("auc-title").textContent =
    i18n("update.ready_card", { version: (data && data.latest_version) || "new" });

  document.getElementById("upd-btn-install").style.display = "";
  document.getElementById("auc-btn-install").style.display = "";
}

async function updInstall() {
  _updInstalling = true;
  document.getElementById("upd-headline").textContent = i18n("update.restarting");
  document.getElementById("auc-title").textContent    = i18n("update.restarting_card");
  document.getElementById("upd-btn-install").disabled = true;
  document.getElementById("auc-btn-install").disabled = true;

  // Show the update overlay BEFORE the fetch so we beat the Socket.IO
  // disconnect event (which would otherwise flash "Server Offline" first).
  document.getElementById("offline-title").textContent = i18n("offline.install_title");
  document.getElementById("offline-body").textContent =
    i18n("offline.install_body");
  document.getElementById("offline-overlay").classList.add("visible");

  // Start the health-poll fallback immediately (socket reconnect is primary).
  _pollUntilRestart();

  try {
    await fetch("/api/apply-update", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ action: "restart" }),
    });
  } catch (_) { /* expected – server exits mid-request */ }
}

function _pollUntilRestart() {
  // Two-phase: wait until the server goes DOWN, then reload when it comes back.
  // This prevents a premature reload if the server hasn't shut down yet when
  // the first poll fires (which would reload onto the still-running old version).
  //
  // The socket.on("connect") handler is the primary reload trigger; this poll
  // is a fallback for cases where the WebSocket doesn't reconnect on its own.
  const INTERVAL_MS = 2000;
  const MAX_WAIT_MS = 120000;
  const started       = Date.now();
  let   serverWasDown = false;

  const timer = setInterval(async () => {
    if (Date.now() - started > MAX_WAIT_MS) {
      clearInterval(timer);
      _updInstalling = false;
      document.getElementById("offline-body").textContent =
        i18n("offline.timeout_body");
      return;
    }
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (res.ok && serverWasDown) {
        // Server is back up after being down – reload (if socket hasn't already).
        clearInterval(timer);
        location.reload();
      }
      // res.ok but !serverWasDown → server hasn't shut down yet, keep waiting.
    } catch (_) {
      serverWasDown = true;   // server is down – next successful poll triggers reload
    }
  }, INTERVAL_MS);
}

function _updShowError(msg) {
  if (_updPollTimer) { clearInterval(_updPollTimer); _updPollTimer = null; }
  document.getElementById("upd-progress-wrap").style.display = "none";
  document.getElementById("upd-headline").textContent = i18n("update.failed");
  document.getElementById("auc-title").textContent    = i18n("update.failed_card");
  document.getElementById("upd-subline").textContent  = msg;
  document.getElementById("auc-notes").textContent    = msg;
  // Re-show the release link as fallback
  document.getElementById("upd-btn-release").style.display = "";
  document.getElementById("auc-btn-release").style.display = "";
}

async function loadHL7Template() {
  // Fetch the full body of the selected template from the server,
  // then substitute placeholders from the quick-fill fields.
  const filename = document.getElementById("hl7-template").value;
  if (!filename) { toast(i18n("hl7.no_template_selected"), "warn"); return; }

  let body;
  try {
    const res  = await fetch(`/api/hl7/templates/${encodeURIComponent(filename)}`);
    const data = await res.json();
    if (data.error) { toast(data.error, "err"); return; }
    body = data.body;   // raw template with {placeholders}
  } catch (e) {
    toast(`Could not load template: ${e}`, "err"); return;
  }

  // Build substitution values from the quick-fill fields
  const ts    = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
  const msgid = "MSG" + ts;
  const nm    = document.getElementById("hl7-pname").value || "PATIENT^TEST";
  const parts = nm.split("^");

  const subs = {
    ts,
    msgid,
    pid:             document.getElementById("hl7-pid").value   || "PID001",
    name:            nm,
    name_last:       parts[0] || "PATIENT",
    name_first:      parts[1] || "TEST",
    dob:             dateToDisom(document.getElementById("hl7-dob").value) || "19800101",
    sex:             document.getElementById("hl7-sex").value   || "U",
    acc:             document.getElementById("hl7-acc").value   || "ACC001",
    proc_code:       document.getElementById("hl7-code").value  || "RADPROC",
    proc_desc:       document.getElementById("hl7-desc").value  || "Radiology Procedure",
    modality:        document.getElementById("hl7-mod").value   || "CT",
    study_uid:       document.getElementById("hl7-suid").value  || "",
    sending_app:     document.getElementById("hl7-sapp").value  || "RIS",
    sending_fac:     document.getElementById("hl7-sfac").value  || "HOSPITAL",
    recv_app:        document.getElementById("hl7-rapp").value  || "PACS",
    recv_fac:        document.getElementById("hl7-rfac").value  || "HOSPITAL",
    assigning_auth:  document.getElementById("hl7-auth").value  || "HOSP",
  };

  // Replace every {placeholder} in the body
  let filled = body;
  for (const [key, val] of Object.entries(subs)) {
    // Use a global regex replace for each key
    filled = filled.split(`{${key}}`).join(val);
  }

  // Show \r as newlines so the editor is readable
  document.getElementById("hl7-message").value = filled.replace(/\r/g, "\n");
}

