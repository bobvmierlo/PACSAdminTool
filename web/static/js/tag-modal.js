// tag-modal.js — DICOM tag detail modal
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 14. DICOM Tag Detail Modal
// ─────────────────────────────────────────────────────────────────

let allTags = [];  // full tag list for the currently open modal

function showTagModal(title, tags) {
  allTags = tags || [];
  document.getElementById("tag-modal-title").textContent = title;
  document.getElementById("tag-filter").value = "";
  renderTagTable(allTags);
  document.getElementById("tag-modal").classList.add("open");
}

function closeTagModal() {
  document.getElementById("tag-modal").classList.remove("open");
}

// Close modal if user clicks the dark backdrop
document.getElementById("tag-modal").addEventListener("click", e => {
  if (e.target === e.currentTarget) closeTagModal();
});

// Flatten the tag tree into a plain list for search/filter
function _flattenTagTree(rows, out = []) {
  rows.forEach(r => {
    out.push(r);
    if (r.children) r.children.forEach(item => _flattenTagTree(item, out));
  });
  return out;
}

function filterTags() {
  const q = document.getElementById("tag-filter").value.toLowerCase();
  if (!q) {
    renderTagTree(allTags, document.getElementById("tag-tbody"), 0);
    const flat = _flattenTagTree(allTags);
    document.getElementById("tag-count").textContent = `${flat.length} tag(s)`;
    return;
  }
  // Flat search across all nodes including inside sequences
  const flat = _flattenTagTree(allTags);
  const matches = flat.filter(r =>
    [r.tag, r.keyword, r.vr, r.value].some(v => String(v).toLowerCase().includes(q)));
  const tbody = document.getElementById("tag-tbody");
  tbody.innerHTML = "";
  matches.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = _tagRowHTML(r, 0);
    tbody.appendChild(tr);
  });
  document.getElementById("tag-count").textContent = `${matches.length} match(es)`;
}

// Build the HTML for a single non-sequence tag row at a given indent depth
function _tagRowHTML(r, depth) {
  const pad = depth * 16;
  return `<td style="font-family:Consolas;font-size:11px;padding-left:${pad}px">${r.tag}</td>` +
    `<td>${escapeHtml(r.keyword)}</td>` +
    `<td>${r.vr}</td>` +
    `<td style="max-width:400px;white-space:normal;word-break:break-all">${escapeHtml(r.value)}</td>`;
}

// Recursively render a tag tree into a <tbody>, collapsing sequences
function renderTagTree(rows, tbody, depth) {
  rows.forEach(r => {
    if (r.children) {
      // ── Sequence header row (clickable toggle) ──────────────────
      const pad = depth * 16;
      const hdr = document.createElement("tr");
      hdr.className = "seq-hdr";
      hdr.innerHTML =
        `<td style="font-family:Consolas;font-size:11px;padding-left:${pad}px">${r.tag}</td>` +
        `<td><span class="seq-arrow">▶</span> ${escapeHtml(r.keyword)}</td>` +
        `<td>${r.vr}</td>` +
        `<td style="color:#666">${escapeHtml(r.value)}</td>`;
      tbody.appendChild(hdr);

      // ── Wrapper row containing nested table (hidden by default) ──
      const wrapper = document.createElement("tr");
      wrapper.style.display = "none";
      const wrapTd = document.createElement("td");
      wrapTd.colSpan = 4;
      wrapTd.style.padding = "0";

      const nested = document.createElement("table");
      nested.className = "seq-nested";
      const nestedBody = document.createElement("tbody");

      r.children.forEach((itemTags, idx) => {
        // Item header: [0], [1], …
        const itemHdr = document.createElement("tr");
        itemHdr.className = "seq-item-hdr";
        const itemTd = document.createElement("td");
        itemTd.colSpan = 4;
        itemTd.style.paddingLeft = `${(depth + 1) * 16}px`;
        itemTd.textContent = `[${idx}]`;
        itemHdr.appendChild(itemTd);
        nestedBody.appendChild(itemHdr);
        // Recurse for this item's tags
        renderTagTree(itemTags, nestedBody, depth + 1);
      });

      nested.appendChild(nestedBody);
      wrapTd.appendChild(nested);
      wrapper.appendChild(wrapTd);
      tbody.appendChild(wrapper);

      // Toggle open/close on header click
      hdr.addEventListener("click", () => {
        const open = wrapper.style.display !== "none";
        wrapper.style.display = open ? "none" : "";
        hdr.querySelector(".seq-arrow").textContent = open ? "▶" : "▼";
      });
    } else {
      // ── Regular tag row ──────────────────────────────────────────
      const tr = document.createElement("tr");
      tr.innerHTML = _tagRowHTML(r, depth);
      tbody.appendChild(tr);
    }
  });
}

function renderTagTable(rows) {
  // rows is now a tree; render it starting at depth 0
  const tbody = document.getElementById("tag-tbody");
  tbody.innerHTML = "";
  renderTagTree(rows, tbody, 0);
  const flat = _flattenTagTree(rows);
  document.getElementById("tag-count").textContent = `${flat.length} tag(s)`;
}

