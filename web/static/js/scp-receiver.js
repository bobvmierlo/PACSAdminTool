// scp-receiver.js — DICOM Storage SCP tab: receiver controls, viewer, studies tree
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 13. DICOM Storage SCP
// ─────────────────────────────────────────────────────────────────

let scpRunning  = false;
let scpFileCount = 0;

/**
 * Before a C-MOVE that targets the local SCP, verify the receiver is running.
 * Returns true if the user wants to proceed (receiver already running or just started).
 * Returns false if the user cancelled or the start failed.
 */
async function _ensureScpRunningForMove() {
  if (scpRunning) return true;
  const ok = await _dialog({
    title:   "DICOM Receiver not running",
    message: "The C-MOVE will send files to your local DICOM Receiver, but it is currently stopped.\n\nStart the DICOM Receiver now and continue?",
    buttons: [
      { text: "Start Receiver & Continue", value: true,  className: "btn primary" },
      { text: "Cancel",                    value: false, className: "btn" },
    ],
  });
  if (!ok) return false;
  // Switch to SCP tab so the user can see startup, then start
  showTab("scp");
  await toggleSCP();
  if (!scpRunning) {
    toast("Failed to start DICOM Receiver. Check port and settings.", "err");
    return false;
  }
  toast("DICOM Receiver started. Proceeding with C-MOVE…", "ok");
  return true;
}

async function toggleSCP() {
  if (scpRunning) {
    await fetch("/api/scp/stop", { method: "POST" });
    scpRunning = false;
  } else {
    const scpPortStr = document.getElementById("scp-port").value;
    const scpPort = parsePort(scpPortStr);
    if (scpPort === null) { toast(i18n("common.invalid_port", {port: scpPortStr}), "err"); return; }
    const res  = await fetch("/api/scp/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ae_title: document.getElementById("scp-ae").value,
        port:     scpPort,
        save_dir: document.getElementById("scp-dir").value,
      }),
    });
    const data = await res.json();
    scpRunning = data.ok;
    appendLog("log-scp", now(), data.message, data.ok ? "ok" : "err");
  }
  updateSCPButton(scpRunning);
}

// Listen for file-received log messages to update the list
let _scpStudiesRefreshTimer = null;
socket.on("log", data => {
  if (data.room === "scp" && data.message.startsWith("Stored:")) {
    scpFileCount++;
    document.getElementById("scp-count").textContent = `${scpFileCount} file(s)`;
    const list = document.getElementById("scp-filelist");
    list.innerHTML += data.message.replace("Stored:", "").trim() + "<br>";
    list.scrollTop = list.scrollHeight;
    // Debounce studies-tree refresh (1.5 s after last store) so rapid series
    // arrivals don't hammer the server with repeated list requests.
    if (document.getElementById("tab-scp").classList.contains("active")) {
      clearTimeout(_scpStudiesRefreshTimer);
      _scpStudiesRefreshTimer = setTimeout(loadSCPStudies, 1500);
    }
  }
});

function updateSCPButton(running) {
  scpRunning = running;
  const btn   = document.getElementById("scp-btn");
  const badge = document.getElementById("scp-badge");
  if (running) {
    btn.textContent = i18n("scp.stop_scp_web");
    btn.className   = "btn danger";
    badge.textContent = i18n("common.running");
    badge.className   = "badge running";
  } else {
    btn.textContent = i18n("scp.start_scp_web");
    btn.className   = "btn primary";
    badge.textContent = i18n("common.stopped");
    badge.className   = "badge stopped";
  }
}

function clearSCPList() {
  document.getElementById("scp-filelist").innerHTML = "";
  scpFileCount = 0;
  document.getElementById("scp-count").textContent = "0 files";
}

async function scpFileInspect(name) {
  try {
    const res  = await fetch(`/api/scp/files/inspect?name=${encodeURIComponent(name)}`);
    const data = await res.json();
    if (!data.ok) { toast("Error: " + data.error, "err"); return; }
    showTagModal(name, data.tags);
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

async function scpFileEdit(path) {
  toast(i18n("scp.edit_loading"), "info");
  try {
    // Fetch raw DICOM bytes and tag list in parallel
    const [rawRes, inspRes] = await Promise.all([
      fetch(`/api/scp/files/raw?path=${encodeURIComponent(path)}`),
      fetch(`/api/scp/files/inspect?name=${encodeURIComponent(path)}`),
    ]);
    if (!rawRes.ok)  { toast("Error fetching file.", "err"); return; }
    const inspData = await inspRes.json();
    if (!inspData.ok) { toast("Error: " + inspData.error, "err"); return; }

    const blob     = await rawRes.blob();
    const filename = path.split("/").pop();
    _inspectorFile = new File([blob], filename, { type: "application/dicom" });
    _inspectorTags = inspData.tags || [];
    _tagEdits      = {};

    // Populate the metadata grid the same way doInspect() does
    const grid = document.getElementById("inspector-meta-grid");
    grid.innerHTML = "";
    const m = inspData.meta || {};
    [
      ["Filename",         filename],
      ["Patient Name",     m.PatientName],
      ["Patient ID",       m.PatientID],
      ["Modality",         m.Modality],
      ["Study Date",       m.StudyDate],
      ["SOP Class UID",    m.SOPClassUID],
    ].forEach(([label, val]) => {
      if (!val) return;
      const div = document.createElement("div");
      div.className = "field";
      div.innerHTML = `<label style="color:#888;font-size:11px">${label}</label>
                       <span style="font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block">${escapeHtml(String(val))}</span>`;
      grid.appendChild(div);
    });
    const fnEl = document.getElementById("inspector-filename");
    if (fnEl) fnEl.textContent = filename;
    document.getElementById("inspector-meta-card").style.display = "";
    document.getElementById("tag-editor-card").style.display    = "none";

    // Switch to Inspector & Editor → Inspect & Edit sub-tab → open editor
    showTab("inspector");
    showInspectorSubTab("edit");
    openTagEditor();
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

async function scpSeriesEdit(studyUid, seriesUid) {
  try {
    const res  = await fetch(`/api/scp/series/list?study=${encodeURIComponent(studyUid)}&series=${encodeURIComponent(seriesUid)}`);
    const data = await res.json();
    if (!data.ok || !data.urls?.length) {
      toast(i18n("scp.edit_no_files"), "warn"); return;
    }
    // Extract the server-side path from the first file URL
    const url  = new URL(data.urls[0], location.href);
    const path = url.searchParams.get("path");
    if (!path) { toast("Could not determine file path.", "err"); return; }
    await scpFileEdit(path);
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

async function scpSeriesAnonymize(studyUid, seriesUid) {
  toast("Loading series files…", "info");
  try {
    const res  = await fetch(`/api/scp/series/list?study=${encodeURIComponent(studyUid)}&series=${encodeURIComponent(seriesUid)}`);
    const data = await res.json();
    if (!data.ok || !data.urls?.length) { toast(i18n("scp.edit_no_files"), "warn"); return; }
    const files = await Promise.all(data.urls.map(async urlStr => {
      const url  = new URL(urlStr, location.href);
      const path = url.searchParams.get("path") || urlStr;
      const r    = await fetch(`/api/scp/files/raw?path=${encodeURIComponent(path)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      return new File([blob], path.split("/").pop() || "file.dcm", { type: "application/dicom" });
    }));
    _anonFiles = files;
    renderAnonList();
    showTab("anonymizer");
    toast(`${files.length} file(s) loaded into Anonymizer`, "ok");
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

// ─────────────────────────────────────────────────────────────────
// DICOM Viewer state
// ─────────────────────────────────────────────────────────────────
// mode 'series'  → navigating through multiple .dcm files in a series
//      'file'    → navigating frames within a single multi-frame .dcm
let _previewMode        = null;   // 'series' | 'file' | null
let _previewStudy       = null;   // StudyInstanceUID  (series mode)
let _previewSeries      = null;   // SeriesInstanceUID (series mode)
let _previewFilePath    = null;   // relative path     (file mode)
let _previewFrameIdx    = 0;      // current frame / instance index
let _previewTotalFrames = 1;      // total frames / instances
let _previewLoading     = false;  // guard: prevent concurrent loads

function _previewReset() {
  _previewMode = null; _previewStudy = null; _previewSeries = null;
  _previewFilePath = null; _previewFrameIdx = 0; _previewTotalFrames = 1;
  _previewLoading = false;
}

function _previewOpenModal(title) {
  const modal  = document.getElementById("preview-modal");
  const titleEl = document.getElementById("preview-modal-title");
  const imgEl  = document.getElementById("preview-modal-img");
  const msgEl  = document.getElementById("preview-modal-msg");
  const metaEl = document.getElementById("preview-modal-meta");
  titleEl.textContent   = title;
  imgEl.style.display   = "none";
  imgEl.src             = "";
  msgEl.style.display   = "block";
  msgEl.textContent     = "Loading…";
  metaEl.textContent    = "";
  modal.style.display   = "flex";
  document.getElementById("preview-brightness").value = 100;
  document.getElementById("preview-contrast").value   = 100;
  applyPreviewFilter();
  document.getElementById("preview-frame-nav").style.display = "none";
}

function _previewShowFrame(url, idx, total) {
  _previewFrameIdx    = idx;
  _previewTotalFrames = total;
  const imgEl  = document.getElementById("preview-modal-img");
  const msgEl  = document.getElementById("preview-modal-msg");
  const nav    = document.getElementById("preview-frame-nav");
  const slider = document.getElementById("preview-frame-slider");
  const label  = document.getElementById("preview-frame-label");

  // Update navigator
  if (total > 1) {
    nav.style.display  = "flex";
    slider.max         = total - 1;
    slider.value       = idx;
    label.textContent  = `${idx + 1} / ${total}`;
  } else {
    nav.style.display  = "none";
  }

  msgEl.style.display  = "block";
  msgEl.textContent    = "Loading…";
  imgEl.style.display  = "none";

  const newImg = new Image();
  newImg.onload = () => {
    imgEl.src          = newImg.src;
    imgEl.style.display = "block";
    msgEl.style.display = "none";
    applyPreviewFilter();
    _previewLoading    = false;
  };
  newImg.onerror = async () => {
    try {
      const r = await fetch(url);
      const d = await r.json().catch(() => ({}));
      msgEl.textContent = "Cannot preview: " + (d.error || "Unknown error");
    } catch {
      msgEl.textContent = "Cannot preview (no pixel data or unsupported format).";
    }
    _previewLoading = false;
  };
  newImg.src = url + "&_=" + Date.now();
}

// Navigate to frame/instance idx  (fromSlider=true skips re-setting slider)
function previewGotoFrame(idx, fromSlider = false) {
  if (_previewLoading) return;
  idx = Math.max(0, Math.min(idx, _previewTotalFrames - 1));
  _previewLoading = true;

  let url;
  if (_previewMode === "series") {
    url = `/api/scp/series/frame?study=${encodeURIComponent(_previewStudy)}&series=${encodeURIComponent(_previewSeries)}&idx=${idx}`;
  } else {
    url = `/api/scp/files/preview?path=${encodeURIComponent(_previewFilePath)}&frame=${idx}`;
  }
  _previewShowFrame(url, idx, _previewTotalFrames);
  if (!fromSlider) {
    document.getElementById("preview-frame-slider").value = idx;
    document.getElementById("preview-frame-label").textContent = `${idx + 1} / ${_previewTotalFrames}`;
  }
}

// Open the viewer for a single .dcm file (possibly multi-frame)
async function scpFilePreview(name) {
  _previewReset();
  _previewMode     = "file";
  _previewFilePath = name;
  _previewOpenModal(name.split("/").pop());

  // Fetch metadata: frame count, W/L
  try {
    const r = await fetch(`/api/scp/files/preview?path=${encodeURIComponent(name)}&info=1`);
    const d = await r.json().catch(() => ({}));
    if (d.ok) {
      _previewTotalFrames = d.frames || 1;
      const metaEl = document.getElementById("preview-modal-meta");
      metaEl.textContent = [d.patient, d.modality, d.study_date].filter(Boolean).join("  ·  ");
    }
  } catch { /* non-critical */ }

  previewGotoFrame(0, false);
}

// Open the dwv viewer for a Study/Series stack in a full-screen iframe overlay
function viewSCPSeries(study, series, label) {
  const overlay = document.getElementById("dwv-overlay");
  const iframe  = document.getElementById("dwv-iframe");
  const url = `/static/dwv-viewer.html?study=${encodeURIComponent(study)}&series=${encodeURIComponent(series)}&title=${encodeURIComponent(label || series)}`;
  iframe.src = url;
  overlay.style.display = "flex";
}

function closeDwvViewer() {
  const overlay = document.getElementById("dwv-overlay");
  const iframe  = document.getElementById("dwv-iframe");
  overlay.style.display = "none";
  iframe.src = "about:blank"; // stop loading / free memory
}

// Mouse-wheel scrolls through frames inside the viewer
document.getElementById("preview-modal").addEventListener("wheel", e => {
  if (_previewMode === null) return;
  e.preventDefault();
  const dir = e.deltaY > 0 ? 1 : -1;
  previewGotoFrame(_previewFrameIdx + dir);
}, { passive: false });

// Keyboard arrow keys for frame navigation when modal is open
document.addEventListener("keydown", e => {
  if (document.getElementById("preview-modal").style.display === "none") return;
  if (_previewMode === null) return;
  if (e.key === "ArrowRight" || e.key === "ArrowDown") {
    e.preventDefault(); previewGotoFrame(_previewFrameIdx + 1);
  } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
    e.preventDefault(); previewGotoFrame(_previewFrameIdx - 1);
  }
});

function applyPreviewFilter() {
  const img    = document.getElementById("preview-modal-img");
  const brtEl  = document.getElementById("preview-brightness");
  const ctrEl  = document.getElementById("preview-contrast");
  const brt    = brtEl?.value ?? 100;
  const ctr    = ctrEl?.value ?? 100;
  img.style.filter = `brightness(${brt}%) contrast(${ctr}%)`;
  const bv = document.getElementById("preview-brt-val");
  const cv = document.getElementById("preview-ctr-val");
  if (bv) bv.textContent = brt;
  if (cv) cv.textContent = ctr;
}

function closePreviewModal() {
  document.getElementById("preview-modal").style.display = "none";
  document.getElementById("preview-modal-img").src = "";
  _previewReset();
}

// ─────────────────────────────────────────────────────────────────
// Received Studies tree
// ─────────────────────────────────────────────────────────────────

async function loadSCPStudies() {
  const treeEl = document.getElementById("scp-studies-tree");
  const infoEl = document.getElementById("scp-studies-info");
  infoEl.textContent = "Loading…";
  treeEl.innerHTML   = "";

  let data;
  try {
    const res = await fetch("/api/scp/studies");
    if (!res.ok && res.headers.get("content-type")?.includes("text/html")) {
      infoEl.textContent = `Error: HTTP ${res.status} from /api/scp/studies`; return;
    }
    data = await res.json();
    if (!data.ok) { infoEl.textContent = "Error: " + data.error; return; }
  } catch (e) {
    infoEl.textContent = "Error: " + e.message; return;
  }

  const studies = data.studies || [];
  const legacy  = data.legacy  || [];
  const total   = studies.reduce((s, st) => s + st.series.reduce((a, se) => a + se.count, 0), 0)
                + legacy.length;
  infoEl.textContent = `${studies.length} study / ${studies.reduce((s,st)=>s+st.series.length,0)} series / ${total} image(s)`;

  if (!studies.length && !legacy.length) {
    treeEl.innerHTML = '<div style="color:#888; font-size:12px; padding:8px 0">No studies received yet.</div>';
    return;
  }

  // ── Studies ──────────────────────────────────────────────────────
  studies.forEach(study => {
    const m = study.meta || {};
    const studyEl = document.createElement("div");
    studyEl.style.cssText = "border:1px solid #e0e0e0; border-radius:4px; margin-bottom:8px; overflow:hidden";

    // Study header
    const hdr = document.createElement("div");
    hdr.style.cssText = "background:#f8f8f8; padding:8px 12px; cursor:pointer; display:flex; align-items:center; gap:8px; user-select:none";
    const arrow = document.createElement("span");
    arrow.textContent = "▾";
    arrow.style.cssText = "font-size:11px; color:#888; transition:transform .15s";
    const info = document.createElement("span");
    info.style.cssText = "font-size:12px; flex:1";
    const name = m.PatientName ? `<strong>${escapeHtml(m.PatientName)}</strong>` : "<em style='color:#888'>Unknown Patient</em>";
    const pid  = m.PatientID ? ` [${escapeHtml(m.PatientID)}]` : "";
    const desc = m.StudyDescription ? ` — ${escapeHtml(m.StudyDescription)}` : "";
    const date = m.StudyDate ? ` <span style='color:#888'>${_fmtDicomDate(m.StudyDate)}</span>` : "";
    info.innerHTML = name + pid + desc + date;

    // Delete-study button
    const delBtn = document.createElement("button");
    delBtn.className = "btn";
    delBtn.style.cssText = "font-size:11px; padding:2px 8px; color:#dc2626; border-color:#fca5a5; flex-shrink:0";
    delBtn.textContent = "Delete Study";
    delBtn.onclick = e => { e.stopPropagation(); scpDeleteStudy(study.uid, study.series.map(s=>s.uid), studyEl); };

    hdr.appendChild(arrow);
    hdr.appendChild(info);
    hdr.appendChild(delBtn);

    // Series body
    const body = document.createElement("div");
    body.style.cssText = "padding:0 0 4px 0";

    study.series.forEach(ser => {
      const sm = ser.meta || {};
      const row = document.createElement("div");
      row.style.cssText = "display:flex; align-items:center; gap:8px; padding:6px 12px 6px 28px; border-top:1px solid #f0f0f0; font-size:12px";

      const mod = document.createElement("span");
      mod.textContent = sm.Modality || "??";
      mod.style.cssText = "background:#dbeafe; color:#1e40af; border-radius:3px; padding:0 5px; font-size:11px; font-weight:600; flex-shrink:0";

      const sdesc = document.createElement("span");
      sdesc.style.cssText = "flex:1; color:#374151; overflow:hidden; text-overflow:ellipsis; white-space:nowrap";
      sdesc.textContent = (sm.SeriesDescription || "Series " + (sm.SeriesNumber || "?")) + ` (${ser.count} img)`;

      const viewBtn = document.createElement("button");
      viewBtn.className = "btn primary";
      viewBtn.style.cssText = "font-size:11px; padding:2px 8px; flex-shrink:0";
      viewBtn.textContent = "View ▶";
      const viewLabel = (sm.Modality || "Series") + " — " + (sm.SeriesDescription || ser.uid.slice(0, 16));
      viewBtn.onclick = () => viewSCPSeries(study.uid, ser.uid, viewLabel);

      const editSer = document.createElement("button");
      editSer.className = "btn";
      editSer.style.cssText = "font-size:11px; padding:2px 8px; flex-shrink:0";
      editSer.setAttribute("data-i18n", "scp.edit_file");
      editSer.textContent = "Edit Tags…";
      editSer.onclick = () => scpSeriesEdit(study.uid, ser.uid);

      const anonSer = document.createElement("button");
      anonSer.className = "btn";
      anonSer.style.cssText = "font-size:11px; padding:2px 8px; flex-shrink:0";
      anonSer.textContent = "Anonymize…";
      anonSer.onclick = () => scpSeriesAnonymize(study.uid, ser.uid);

      const delSer = document.createElement("button");
      delSer.className = "btn";
      delSer.style.cssText = "font-size:11px; padding:2px 8px; color:#dc2626; border-color:#fca5a5; flex-shrink:0";
      delSer.textContent = "Del";
      delSer.onclick = () => scpDeleteSeries(study.uid, ser.uid, row, study.uid, studyEl, study.series.length);

      row.appendChild(mod);
      row.appendChild(sdesc);
      row.appendChild(viewBtn);
      row.appendChild(editSer);
      row.appendChild(anonSer);
      row.appendChild(delSer);
      body.appendChild(row);
    });

    // Toggle collapse
    hdr.addEventListener("click", () => {
      const collapsed = body.style.display === "none";
      body.style.display = collapsed ? "" : "none";
      arrow.style.transform = collapsed ? "" : "rotate(-90deg)";
    });

    studyEl.appendChild(hdr);
    studyEl.appendChild(body);
    treeEl.appendChild(studyEl);
  });

  // ── Legacy flat files ────────────────────────────────────────────
  if (legacy.length) {
    const legEl = document.createElement("div");
    legEl.style.cssText = "border:1px solid #e0e0e0; border-radius:4px; overflow:hidden; margin-bottom:8px";
    const legHdr = document.createElement("div");
    legHdr.style.cssText = "background:#f8f8f8; padding:8px 12px; font-size:12px; color:#555";
    legHdr.textContent   = `Legacy flat files (${legacy.length})`;
    legEl.appendChild(legHdr);
    legacy.forEach(f => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex; align-items:center; gap:8px; padding:5px 12px; border-top:1px solid #f0f0f0; font-size:12px";
      const nm = document.createElement("span");
      nm.style.flex = "1";
      nm.textContent = f.name;
      const pvBtn = document.createElement("button");
      pvBtn.className = "btn";
      pvBtn.style.cssText = "font-size:11px; padding:2px 8px";
      pvBtn.textContent = "Preview";
      pvBtn.onclick = () => scpFilePreview(f.name);
      const delBtn = document.createElement("button");
      delBtn.className = "btn";
      delBtn.style.cssText = "font-size:11px; padding:2px 8px; color:#dc2626; border-color:#fca5a5";
      delBtn.textContent = "Delete";
      delBtn.onclick = () => scpFileDelete(f.name, row);
      row.setAttribute("data-legacy-row", "1");
      row.appendChild(nm); row.appendChild(pvBtn); row.appendChild(delBtn);
      legEl.appendChild(row);
    });
    treeEl.appendChild(legEl);
  }
}

function _fmtDicomDate(d) {
  if (!d || d.length < 8) return d;
  return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`;
}

async function scpDeleteStudy(studyUid, seriesUids, rowEl) {
  const confirmed = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete entire study (${seriesUids.length} series)?\n\n${i18n("common.cannot_undo")}`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!confirmed) return;
  let ok = true;
  for (const serUid of seriesUids) {
    try {
      const r = await fetch("/api/scp/series/delete",
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ study: studyUid, series: serUid }) });
      const d = await r.json().catch(() => ({}));
      if (!d.ok) ok = false;
    } catch { ok = false; }
  }
  if (!ok) toast("Some series could not be deleted.", "err");
  rowEl.remove();
}

async function scpDeleteSeries(studyUid, serUid, rowEl) {
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete series?\n${serUid}\n\n${i18n("common.cannot_undo")}`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  try {
    const res  = await fetch("/api/scp/series/delete",
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ study: studyUid, series: serUid }) });
    const data = await res.json();
    if (!data.ok) { toast("Error: " + data.error, "err"); return; }
    rowEl.remove();
    // Reload tree so study disappears if now empty
    loadSCPStudies();
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

async function scpFileDelete(name, rowEl) {
  const ok = await _dialog({
    title:   i18n("common.confirm_delete"),
    message: `Delete "${name}"?\n${i18n("common.cannot_undo")}`,
    buttons: [
      { text: i18n("common.delete"), value: true,  className: "btn danger" },
      { text: i18n("common.cancel"), value: null,   className: "btn" },
    ],
  });
  if (!ok) return;
  try {
    const res  = await fetch("/api/scp/files/delete",
                             { method: "POST",
                               headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ name }) });
    const data = await res.json();
    if (!data.ok) { toast("Error: " + data.error, "err"); return; }
    rowEl.remove();
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

