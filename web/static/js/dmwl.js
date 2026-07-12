// dmwl.js — DMWL (Modality Worklist) tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 8. DMWL
// ─────────────────────────────────────────────────────────────────

let dmwlResults = [];

async function doDMWL() {
  const ae = getAE("dmwl");
  if (!ae) return;
  clearTable("dmwl-tbody");
  dmwlResults = [];
  appendLog("log-dmwl", now(), `DMWL → ${ae.ae_title}@${ae.host}:${ae.port}`);

  const res  = await fetch("/api/dicom/dmwl", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...ae,
      patient_id:   document.getElementById("dmwl-pid").value,
      patient_name: document.getElementById("dmwl-pname").value,
      study_date:   dateToDisom(document.getElementById("dmwl-date").value),
      modality:     document.getElementById("dmwl-mod").value,
      accession:    document.getElementById("dmwl-acc").value,
      station_aet:  document.getElementById("dmwl-aet").value,
      calling_aet:  document.getElementById("dmwl-calling-aet").value,
    }),
  });
  const data = await res.json();
  appendLog("log-dmwl", now(), data.message, data.ok ? "ok" : "err");

  dmwlResults = data.results || [];
  document.getElementById("dmwl-count").textContent = `${dmwlResults.length} item(s)`;
  const tbody = document.getElementById("dmwl-tbody");
  dmwlResults.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.PatientID}</td><td>${r.PatientName}</td><td>${r.Accession}</td>
      <td>${r.Modality}</td><td>${formatDicomDate(r.ScheduledDate)}</td><td>${r.StationAET}</td><td>${r.Procedure}</td>`;
    tr.onclick = () => showTagModal(`Worklist: ${r.PatientName} / ${r.PatientID}`, r.tags);
    tbody.appendChild(tr);
  });
}

function exportDMWLCsv() {
  if (!dmwlResults.length) { toast(i18n("dmwl.no_results"), "warn"); return; }
  const header = "PatientID,PatientName,Accession,Modality,ScheduledDate,StationAET,Procedure\n";
  const rows   = dmwlResults.map(r =>
    [r.PatientID, r.PatientName, r.Accession, r.Modality,
     r.ScheduledDate, r.StationAET, r.Procedure].map(v => `"${v}"`).join(",")
  ).join("\n");
  downloadText("worklist.csv", header + rows, "text/csv");
}

