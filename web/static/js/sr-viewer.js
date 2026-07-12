// sr-viewer.js — SR Viewer tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 18. SR Viewer
// ─────────────────────────────────────────────────────────────────

let _srRawTags  = [];   // flat list (for tag modal + filter search)
let _srContent  = [];   // nested tree from backend

const _SR_NEMA_URL = "https://dicom.nema.org/medical/dicom/current/output/chtml/part16/chapter_D.html";

// Map value-type → CSS badge class
function _srTypeClass(type) {
  const map = {
    CONTAINER: "sr-type-container",
    NUM:       "sr-type-num",
    CODE:      "sr-type-code",
    TEXT:      "sr-type-text",
    IMAGE:     "sr-type-image",
    UIDREF:    "sr-type-uid",
    PNAME:     "sr-type-pname",
    DATE:      "sr-type-date",
    TIME:      "sr-type-date",
    DATETIME:  "sr-type-date",
    SCOORD:    "sr-type-scoord",
    SCOORD3D:  "sr-type-scoord",
    TCOORD:    "sr-type-scoord",
    COMPOSITE: "sr-type-composite",
    WAVEFORM:  "sr-type-composite",
  };
  return map[type] || "sr-type-other";
}

// Render the concept name, optionally as a NEMA link (DCM scheme only)
function _srConceptHtml(concept, codeVal, codeScheme) {
  if (!concept) return "";
  if (codeScheme === "DCM" && codeVal) {
    return `<a class="sr-concept-link" href="${_SR_NEMA_URL}" target="_blank"
               rel="noopener noreferrer"
               title="${escapeHtml(i18n("sr_viewer.nema_link_title"))}"
               onclick="event.stopPropagation()">${escapeHtml(concept)}</a>`;
  }
  return `<span class="sr-concept-name">${escapeHtml(concept)}</span>`;
}

// Recursively build DOM tree nodes
function _srRenderNode(node, container) {
  const isContainer = node.type === "CONTAINER";
  const typeBadge   = `<span class="sr-badge ${_srTypeClass(node.type)}">${escapeHtml(node.type || "")}</span>`;
  const relBadge    = node.relationship
    ? `<span class="sr-badge sr-rel-badge">${escapeHtml(node.relationship)}</span>`
    : "";
  const conceptHtml = _srConceptHtml(
    node.concept, node.concept_code_value, node.concept_code_scheme
  );

  if (isContainer) {
    const block = document.createElement("div");
    block.className = "sr-block";

    const hdr = document.createElement("div");
    hdr.className = "sr-container-hdr";
    hdr.innerHTML =
      `<span class="seq-arrow">▼</span>` +
      typeBadge + relBadge +
      `<span class="sr-concept-wrap">${conceptHtml}</span>` +
      (node.value ? `<span class="sr-container-value">${escapeHtml(node.value)}</span>` : "");
    block.appendChild(hdr);

    const childWrap = document.createElement("div");
    childWrap.className = "sr-children";
    block.appendChild(childWrap);
    container.appendChild(block);

    hdr.addEventListener("click", e => {
      if (e.target.tagName === "A") return;
      const open = childWrap.style.display !== "none";
      childWrap.style.display = open ? "none" : "";
      hdr.querySelector(".seq-arrow").textContent = open ? "▶" : "▼";
    });

    if (node.children) {
      node.children.forEach(child => _srRenderNode(child, childWrap));
    }
  } else {
    const row = document.createElement("div");
    row.className = "sr-row";
    row.innerHTML =
      typeBadge + relBadge +
      `<span class="sr-concept-wrap">${conceptHtml}</span>` +
      (node.value ? `<span class="sr-value">${escapeHtml(node.value)}</span>` : "");
    container.appendChild(row);
  }
}

// Render the full tree
function renderSRTree(nodes) {
  const treeDiv = document.getElementById("sr-tree");
  treeDiv.innerHTML = "";
  if (!nodes || !nodes.length) {
    treeDiv.innerHTML = `<div class="sr-empty">${i18n("sr_viewer.empty")}</div>`;
    return;
  }
  nodes.forEach(n => _srRenderNode(n, treeDiv));
  document.getElementById("sr-item-count").textContent =
    i18n("sr_viewer.item_count", {n: _srRawTags.length});
}

// Filter: show a flat table of matches instead of the tree
function filterSRTree() {
  const q = document.getElementById("sr-filter").value.trim().toLowerCase();
  const treeDiv = document.getElementById("sr-tree");
  if (!q) {
    renderSRTree(_srContent);
    return;
  }
  const matches = _srRawTags.filter(item =>
    [item.concept, item.value, item.type, item.relationship]
      .some(v => String(v || "").toLowerCase().includes(q))
  );
  treeDiv.innerHTML = "";
  if (!matches.length) {
    treeDiv.innerHTML = `<div class="sr-empty">${i18n("sr_viewer.empty")}</div>`;
    document.getElementById("sr-item-count").textContent = i18n("sr_viewer.filter_matches", {n: 0});
    return;
  }
  const table = document.createElement("table");
  table.className = "sr-flat-table";
  table.innerHTML = `<thead><tr>
    <th>Type</th><th>Relationship</th><th>Concept</th><th>Value</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  matches.forEach(item => {
    const tr = document.createElement("tr");
    const conceptHtml = _srConceptHtml(
      item.concept, item.concept_code_value, item.concept_code_scheme
    );
    tr.innerHTML =
      `<td><span class="sr-badge ${_srTypeClass(item.type)}">${escapeHtml(item.type || "")}</span></td>` +
      `<td style="font-size:11px; color:#666">${escapeHtml(item.relationship || "")}</td>` +
      `<td>${conceptHtml}</td>` +
      `<td style="word-break:break-word">${escapeHtml(item.value || "")}</td>`;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  treeDiv.appendChild(table);
  document.getElementById("sr-item-count").textContent =
    i18n("sr_viewer.filter_matches", {n: matches.length});
}

// Expand or collapse all CONTAINER nodes
function srExpandAll(open) {
  document.querySelectorAll("#sr-tree .sr-container-hdr").forEach(hdr => {
    const childWrap = hdr.nextElementSibling;
    if (!childWrap) return;
    childWrap.style.display = open ? "" : "none";
    const arrow = hdr.querySelector(".seq-arrow");
    if (arrow) arrow.textContent = open ? "▼" : "▶";
  });
}

function toggleSRInfo() {
  const body  = document.getElementById("sr-info-body");
  const arrow = document.getElementById("sr-info-arrow");
  const open  = body.style.display === "none";
  body.style.display = open ? "" : "none";
  arrow.textContent  = open ? "▼" : "▶";
}

function srFileSelected() {
  const f = document.getElementById("sr-file-input").files[0];
  document.getElementById("sr-filename").textContent = f ? f.name : "";
}

async function doSRRead() {
  const input = document.getElementById("sr-file-input");
  if (!input.files.length) {
    appendLog("log-sr", now(), i18n("sr_viewer.no_file"), "warn");
    return;
  }
  const f = input.files[0];
  appendLog("log-sr", now(), `Parsing: ${f.name}`);
  document.getElementById("sr-tree").innerHTML = "";
  document.getElementById("sr-item-count").textContent = "";
  document.getElementById("sr-filter").value = "";
  document.getElementById("sr-meta").textContent = "";
  _srRawTags = [];
  _srContent = [];

  const fd = new FormData();
  fd.append("file", f);

  try {
    const res  = await fetch("/api/dicom/sr/read", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) {
      appendLog("log-sr", now(), `Error: ${data.error}`, "err");
      return;
    }

    // Build meta summary
    const m = data.meta || {};
    const metaEl = document.getElementById("sr-meta");
    const metaParts = [];
    if (data.title) metaParts.push(`<span class="sr-meta-title">${escapeHtml(data.title)}</span>`);
    if (m.SOPClassName || m.SOPClassUID) metaParts.push(escapeHtml(m.SOPClassName || m.SOPClassUID));
    const patient = [m.PatientName, m.PatientID ? `[${m.PatientID}]` : ""].filter(Boolean).join(" ");
    if (patient) metaParts.push(escapeHtml(patient));
    if (m.StudyDate) metaParts.push(escapeHtml(m.StudyDate));
    metaEl.innerHTML = metaParts.join("  ·  ");

    // Store data
    _srRawTags = data.flat    || [];
    _srContent = data.content || [];

    // Render interactive tree
    renderSRTree(_srContent);

    const n = _srRawTags.length;
    appendLog("log-sr", now(), i18n("sr_viewer.parsed_ok", {n}), "ok");

    if (data.errors && data.errors.length) {
      data.errors.forEach(e => appendLog("log-sr", now(), `Warning: ${e}`, "warn"));
    }
  } catch (e) {
    appendLog("log-sr", now(), `Error: ${e}`, "err");
  }
}

function srViewRawTags() {
  if (!_srRawTags.length) {
    appendLog("log-sr", now(), i18n("sr_viewer.no_parsed"), "warn");
    return;
  }
  const tags = _srRawTags.map(item => ({
    tag:     "  ".repeat(item.depth) + (item.type || ""),
    keyword: item.concept || "",
    vr:      item.relationship || "",
    value:   item.value || "",
  }));
  showTagModal(i18n("sr_viewer.tags_title"), tags);
}

