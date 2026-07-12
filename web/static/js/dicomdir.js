// dicomdir.js — DICOMDIR reader and generator tabs
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// DICOMDIR Reader
// ─────────────────────────────────────────────────────────────────

function dicomdirFileSelected() {
  const f = document.getElementById("dicomdir-file-input").files[0];
  document.getElementById("dicomdir-filename").textContent = f ? f.name : "";
  document.getElementById("dicomdir-result-card").style.display = "none";
}

async function doDicomDir() {
  const input = document.getElementById("dicomdir-file-input");
  if (!input.files || !input.files[0]) { toast("Select a DICOMDIR file first.", "warn"); return; }
  const fd = new FormData();
  fd.append("file", input.files[0]);
  try {
    const res  = await fetch("/api/dicom/dicomdir", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) { toast("Error: " + data.error, "err"); return; }

    document.getElementById("dicomdir-summary").textContent =
      `${data.total_patients} patient(s) · ${data.total_instances} instance(s)`;

    const tree = document.getElementById("dicomdir-tree");
    tree.innerHTML = "";
    (data.patients || []).forEach(pat => {
      tree.appendChild(_ddNode(`👤 ${pat.PatientName || "(no name)"}  [${pat.PatientID}]`, 0, true));
      (pat.studies || []).forEach(stu => {
        const studyLabel = `📋 ${stu.StudyDate || "?"}  ${stu.StudyDescription || ""}  `
                         + `ACC: ${stu.AccessionNumber || "–"}`;
        tree.appendChild(_ddNode(studyLabel, 1, true));
        (stu.series || []).forEach(ser => {
          const serLabel = `🔷 Series ${ser.SeriesNumber || "?"}  ${ser.Modality || ""}  `
                         + `${ser.SeriesDescription || ""}`;
          tree.appendChild(_ddNode(serLabel, 2, true));
          (ser.instances || []).forEach(inst => {
            const instLabel = `  ${inst.type}  #${inst.InstanceNumber || "?"}  ${inst.SOPInstanceUID}`;
            tree.appendChild(_ddNode(instLabel, 3, false));
          });
        });
      });
    });
    document.getElementById("dicomdir-result-card").style.display = "";
  } catch (e) {
    toast("Error: " + e, "err");
  }
}

function _ddNode(text, indent, bold) {
  const div = document.createElement("div");
  div.style.cssText = `padding:2px 0 2px ${indent * 20}px; ${bold ? "font-weight:600" : "color:#555"}`;
  div.textContent   = text;
  return div;
}

// ─────────────────────────────────────────────────────────────────
// DICOMDIR Generator
// ─────────────────────────────────────────────────────────────────

// Track which input is active so we always read from the right one
let _ddGenSource = null;

function ddGenFilesSelected(source) {
  _ddGenSource = source;
  const input = document.getElementById(
    source === "folder" ? "dd-gen-folder-input" : "dd-gen-files-input"
  );
  const n = input.files ? input.files.length : 0;
  document.getElementById("dd-gen-count").textContent =
    n ? `${n} file(s) selected` : "";
}

async function doGenerateDicomDir() {
  // Pick whichever input was used last; fall back to checking both
  let input = null;
  if (_ddGenSource === "folder") {
    input = document.getElementById("dd-gen-folder-input");
  } else if (_ddGenSource === "files") {
    input = document.getElementById("dd-gen-files-input");
  } else {
    // Nothing chosen yet — check both
    const fi = document.getElementById("dd-gen-files-input");
    const di = document.getElementById("dd-gen-folder-input");
    input = (fi.files && fi.files.length) ? fi
          : (di.files && di.files.length) ? di
          : null;
  }
  if (!input || !input.files || !input.files.length) {
    toast("Select files or a folder first.", "warn");
    return;
  }
  const fd = new FormData();
  for (const f of input.files) fd.append("files[]", f);
  const btn = document.querySelector("[onclick='doGenerateDicomDir()']");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Generating…";
  try {
    const res = await fetch("/api/dicom/dicomdir/generate",
                            { method: "POST", body: fd });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      toast("Error: " + (d.error || res.statusText), "err");
      return;
    }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = "DICOMDIR_set.zip";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) {
    toast("Error: " + e, "err");
  } finally {
    btn.disabled    = false;
    btn.textContent = orig;
  }
}

