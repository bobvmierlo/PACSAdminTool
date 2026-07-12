// commit-iocm.js — Storage Commitment and IOCM tabs
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 9. Storage Commitment
// ─────────────────────────────────────────────────────────────────

async function doCommit() {
  const ae   = getAE("commit");
  if (!ae) return;
  const raw  = document.getElementById("commit-uids").value;
  const uids = raw.split("\n").map(s => s.trim()).filter(Boolean);
  if (!uids.length) { toast(i18n("commit.enter_uid"), "warn"); return; }
  appendLog("log-commit", now(), `N-ACTION → ${ae.ae_title} (${uids.length} UIDs)`);
  const res  = await fetch("/api/dicom/commit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...ae, uids }),
  });
  const data = await res.json();
  appendLog("log-commit", now(), data.message, data.ok ? "ok" : "err");
}

// ─────────────────────────────────────────────────────────────────
// 10. IOCM
// ─────────────────────────────────────────────────────────────────

async function doIOCM() {
  const ae = getAE("iocm");
  if (!ae) return;
  appendLog("log-iocm", now(), `IOCM → ${ae.ae_title}`);
  const res  = await fetch("/api/dicom/iocm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...ae,
      study_uid:    document.getElementById("iocm-suid").value,
      series_uid:   document.getElementById("iocm-seruid").value,
      sop_class_uid: document.getElementById("iocm-sopclass").value,
      sop_inst_uid:  document.getElementById("iocm-sopinst").value,
      availability:  document.getElementById("iocm-avail").value,
    }),
  });
  const data = await res.json();
  appendLog("log-iocm", now(), data.message, data.ok ? "ok" : "err");
}

