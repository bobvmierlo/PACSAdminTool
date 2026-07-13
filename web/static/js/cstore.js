// cstore.js — C-STORE tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 7. C-STORE
// ─────────────────────────────────────────────────────────────────

function updateFileList() {
  const input = document.getElementById("cstore-files");
  const list  = document.getElementById("cstore-filelist");
  const count = document.getElementById("cstore-count");
  list.innerHTML = [...input.files].map(f => f.name).join("<br>");
  count.textContent = `${input.files.length} file(s) selected`;
}

function clearStoreFiles() {
  document.getElementById("cstore-files").value = "";
  document.getElementById("cstore-filelist").innerHTML = "";
  document.getElementById("cstore-count").textContent = "0 files selected";
}

async function doCStore() {
  const ae    = getAE("cstore");
  if (!ae) return;
  const input = document.getElementById("cstore-files");
  if (!input.files.length) { toast(i18n("cstore.no_files"), "warn"); return; }

  // Build a FormData object (the standard way to upload files via fetch)
  const form = new FormData();
  form.append("ae_title", ae.ae_title);
  form.append("host",     ae.host);
  form.append("port",     ae.port);
  [...input.files].forEach(f => form.append("files[]", f));

  appendLog("log-cstore", now(), `Uploading ${input.files.length} file(s) to server…`);
  const res  = await fetch("/api/dicom/store", { method: "POST", body: form });
  const data = await res.json();
  appendLog("log-cstore", now(), data.message, data.ok ? "ok" : "err");
  // Further progress lines will arrive via WebSocket
  trackJob(data.job_id, "log-cstore");
}

