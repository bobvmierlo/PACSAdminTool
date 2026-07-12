// kos.js — KOS Creator tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 19. KOS Creator
// ─────────────────────────────────────────────────────────────────

function kosFilesSelected() {
  const files = document.getElementById("kos-files-input").files;
  document.getElementById("kos-file-count").textContent =
    files.length ? i18n("kos_creator.files_loaded", {n: files.length})
                 : i18n("kos_creator.no_files_loaded");
}

async function doKOSExtract() {
  const input = document.getElementById("kos-files-input");
  if (!input.files.length) {
    appendLog("log-kos", now(), i18n("kos_creator.no_files_loaded_msg"), "warn");
    return;
  }
  appendLog("log-kos", now(), i18n("kos_creator.extracting"));

  const fd = new FormData();
  Array.from(input.files).forEach(f => fd.append("files", f));

  try {
    const res  = await fetch("/api/dicom/kos/extract", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) {
      appendLog("log-kos", now(), `Error: ${data.error}`, "err");
      return;
    }
    // Populate study/patient fields
    document.getElementById("kos-study-uid").value = data.study_instance_uid || "";
    document.getElementById("kos-pid").value        = data.patient_id         || "";
    document.getElementById("kos-pname").value      = data.patient_name       || "";
    document.getElementById("kos-acc").value         = data.accession_number  || "";
    document.getElementById("kos-date").value        = dicomDateToInput(data.study_date || "");
    document.getElementById("kos-inst").value        = data.institution_name  || "";

    // Build instances textarea
    const seriesMap = data.series || {};
    const lines = ["# SeriesUID | SOPClassUID | SOPInstanceUID"];
    for (const [seriesUid, seriesData] of Object.entries(seriesMap)) {
      for (const inst of (seriesData.instances || [])) {
        lines.push(`${seriesUid}|${inst.sop_class_uid}|${inst.sop_instance_uid}`);
      }
    }
    document.getElementById("kos-instances").value = lines.join("\n");

    const nSeries = Object.keys(seriesMap).length;
    const nInst   = Object.values(seriesMap).reduce((s, sd) => s + (sd.instances || []).length, 0);
    appendLog("log-kos", now(), i18n("kos_creator.extracted_ok", {n_series: nSeries, n_inst: nInst}), "ok");
    if (data.errors && data.errors.length) {
      data.errors.forEach(e => appendLog("log-kos", now(), `Warning: ${e}`, "warn"));
    }
  } catch (e) {
    appendLog("log-kos", now(), `Error: ${e}`, "err");
  }
}

async function doKOSCreate() {
  const studyUid = document.getElementById("kos-study-uid").value.trim();
  if (!studyUid) {
    appendLog("log-kos", now(), "Study UID is required.", "warn");
    return;
  }

  // Parse instances textarea into referenced_series list
  const lines = document.getElementById("kos-instances").value.split("\n");
  const seriesMap = {};
  for (const line of lines) {
    const l = line.trim();
    if (!l || l.startsWith("#")) continue;
    const parts = l.split("|").map(p => p.trim());
    if (parts.length === 3) {
      const [seriesUid, sopClass, sopInst] = parts;
      if (!seriesMap[seriesUid]) seriesMap[seriesUid] = [];
      seriesMap[seriesUid].push({ sop_class_uid: sopClass, sop_instance_uid: sopInst });
    } else if (parts.length === 2) {
      const [seriesUid, sopInst] = parts;
      if (!seriesMap[seriesUid]) seriesMap[seriesUid] = [];
      seriesMap[seriesUid].push({ sop_class_uid: "1.2.840.10008.5.1.4.1.1.2", sop_instance_uid: sopInst });
    }
  }

  const referencedSeries = Object.entries(seriesMap).map(([uid, insts]) => ({
    series_uid: uid,
    instances: insts,
  }));

  if (!referencedSeries.length) {
    appendLog("log-kos", now(), "No valid instance lines found in the instances box.", "warn");
    return;
  }

  appendLog("log-kos", now(), i18n("kos_creator.creating"));

  const body = {
    study_instance_uid: studyUid,
    patient_id:         document.getElementById("kos-pid").value.trim(),
    patient_name:       document.getElementById("kos-pname").value.trim(),
    accession_number:   document.getElementById("kos-acc").value.trim(),
    study_date:         dateToDisom(document.getElementById("kos-date").value),
    institution_name:   document.getElementById("kos-inst").value.trim(),
    doc_title_key:      document.getElementById("kos-doc-title").value,
    referenced_series:  referencedSeries,
  };

  try {
    const res = await fetch("/api/dicom/kos/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      appendLog("log-kos", now(), `Error: ${err.error || res.statusText}`, "err");
      return;
    }

    // Trigger browser download of the returned .dcm file
    const blob     = await res.blob();
    const cd       = res.headers.get("Content-Disposition") || "";
    const fnMatch  = cd.match(/filename="?([^";\n]+)"?/);
    const filename = fnMatch ? fnMatch[1] : "KOS.dcm";
    const a        = document.createElement("a");
    a.href         = URL.createObjectURL(blob);
    a.download     = filename;
    a.click();
    URL.revokeObjectURL(a.href);
    appendLog("log-kos", now(), `KOS created and downloaded: ${filename}`, "ok");
  } catch (e) {
    appendLog("log-kos", now(), `Error: ${e}`, "err");
  }
}

