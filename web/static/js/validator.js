// validator.js — DICOM file validator tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────
// 16. DICOM File Validator
// ─────────────────────────────────────────────────────────────────

function validatorFileSelected() {
  const f = document.getElementById("validator-file-input").files[0];
  document.getElementById("validator-filename").textContent = f ? f.name : "";
  document.getElementById("validator-summary-card").style.display  = "none";
  document.getElementById("validator-findings-card").style.display = "none";
}

async function doValidate() {
  const input = document.getElementById("validator-file-input");
  if (!input.files.length) {
    toast(i18n("validator.no_file"), "warn");
    return;
  }
  const fd = new FormData();
  fd.append("file", input.files[0]);
  try {
    const res  = await fetch("/api/dicom/validate", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) { toast(data.error || "Validation failed", "err"); return; }
    _renderValidatorResults(data);
  } catch (e) {
    toast("" + e, "err");
  }
}

function _renderValidatorResults(data) {
  const summary  = data.summary  || {};
  const findings = data.findings || [];
  const checks   = data.checks   || [];

  // ── summary card ───────────────────────────────────────────────
  const grid = document.getElementById("validator-summary-grid");
  grid.innerHTML = [
    ["validator.sum_patient",         summary.patient_name        || "—"],
    ["validator.sum_patient_id",      summary.patient_id          || "—"],
    ["validator.sum_study_date",      summary.study_date          || "—"],
    ["validator.sum_modality",        summary.modality            || "—"],
    ["validator.sum_sop_class",       summary.sop_class_name      || summary.sop_class_uid || "—"],
    ["validator.sum_transfer_syntax", summary.transfer_syntax_name || summary.transfer_syntax_uid || "—"],
  ].map(([key, val]) =>
    `<div class="field"><label>${i18n(key)}</label>` +
    `<span style="font-size:13px;color:#1a1a1a">${escapeHtml(String(val))}</span></div>`
  ).join("");

  const verdict = document.getElementById("validator-verdict");
  const errs = summary.errors   || 0;
  const warn = summary.warnings || 0;
  if (errs > 0) {
    verdict.style.cssText = "margin-top:12px;padding:10px 14px;border-radius:4px;font-size:13px;font-weight:600;background:#fef2f2;color:#dc2626;border:1px solid #fca5a5";
    verdict.textContent   = i18n("validator.verdict_errors", { n: errs, w: warn });
  } else if (warn > 0) {
    verdict.style.cssText = "margin-top:12px;padding:10px 14px;border-radius:4px;font-size:13px;font-weight:600;background:#fffbeb;color:#d97706;border:1px solid #fcd34d";
    verdict.textContent   = i18n("validator.verdict_warnings", { n: warn });
  } else {
    verdict.style.cssText = "margin-top:12px;padding:10px 14px;border-radius:4px;font-size:13px;font-weight:600;background:#f0fdf4;color:#15803d;border:1px solid #86efac";
    verdict.textContent   = i18n("validator.verdict_ok");
  }
  document.getElementById("validator-summary-card").style.display = "block";

  // ── findings table ──────────────────────────────────────────────
  const tbody = document.getElementById("validator-findings-tbody");
  tbody.innerHTML = "";
  if (findings.length > 0) {
    findings.forEach(f => {
      const sev = f.severity || "info";
      const [colour, prefix] =
        sev === "error"   ? ["#dc2626", "✗ " + i18n("validator.severity_error")]   :
        sev === "warning" ? ["#d97706", "⚠ " + i18n("validator.severity_warning")] :
                            ["#2b6cb0", "ℹ " + i18n("validator.severity_info")];
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td style="color:${colour};font-weight:600;font-size:12px">${escapeHtml(prefix)}</td>` +
        `<td style="font-size:12px;font-family:Consolas,monospace">${escapeHtml(f.code    || "")}</td>` +
        `<td style="font-size:12px;font-family:Consolas,monospace">${escapeHtml(f.tag     || "")}</td>` +
        `<td style="font-size:12px">${escapeHtml(f.message || "")}</td>`;
      tbody.appendChild(tr);
    });
    document.getElementById("validator-findings-card").style.display = "block";
  } else {
    document.getElementById("validator-findings-card").style.display = "none";
  }

  // ── full checklist ──────────────────────────────────────────────
  const checksCard = document.getElementById("validator-checks-card");
  const checksTbody = document.getElementById("validator-checks-tbody");
  checksTbody.innerHTML = "";
  if (checks.length > 0) {
    const passing = checks.filter(c => c.status === "pass").length;
    document.getElementById("validator-checks-count").textContent =
      `${passing} / ${checks.length} passed`;
    checks.forEach(c => {
      const st = c.status || "pass";
      const [colour, icon] =
        st === "error"   ? ["#dc2626", "✗"] :
        st === "warning" ? ["#d97706", "⚠"] :
        st === "info"    ? ["#2b6cb0", "ℹ"] :
                           ["#16a34a", "✓"];
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td style="color:${colour};font-weight:700;font-size:13px;text-align:center">${icon}</td>` +
        `<td style="font-size:11px;color:#888">${escapeHtml(c.group || "")}</td>` +
        `<td style="font-size:11px;font-family:Consolas,monospace">${escapeHtml(c.tag || "")}</td>` +
        `<td style="font-size:12px">${escapeHtml(c.name || "")}</td>` +
        `<td style="font-size:11px;color:#888">${escapeHtml(c.message || "")}</td>`;
      checksTbody.appendChild(tr);
    });
    checksCard.style.display = "block";
  } else {
    checksCard.style.display = "none";
  }
}

