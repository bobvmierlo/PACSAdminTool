// help.js — Help tab
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// 15. Help tab
// ─────────────────────────────────────────────────────────────────

const HELP_SECTIONS = [
  // Order matches the tab bar: Dashboard → C-FIND → C-STORE → Receiver →
  // DMWL → Commit → IOCM → Inspector → Validator → SR Viewer → KOS → DICOMize →
  // Anonymizer → DICOMDIR → DICOMweb → HL7 → Settings → Logs → About
  ["help.section_dashboard", "help.body_dashboard",
  []],

  ["help.section_cfind", "help.body_cfind",
  [
    {label: "DICOM PS3.4 §C – Query/Retrieve Service Class (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_C"},
    {label: "PS3.4 Table C.6-1 – Study Root Attributes", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#table_C.6-1"},
    {label: "PS3.4 Table C.6-2 – Patient Root Attributes", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#table_C.6-2"},
  ]],

  ["help.section_cget", "help.body_cget",
  [
    {label: "DICOM PS3.4 §C.4.3 – C-GET Service (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#sect_C.4.3"},
    {label: "DICOM PS3.4 §C.4.2 – C-MOVE Service (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#sect_C.4.2"},
  ]],

  ["help.section_cstore", "help.body_cstore",
  [
    {label: "DICOM PS3.4 §B – Storage Service Class (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_B"},
  ]],

  ["help.section_receiver", "help.body_receiver",
  [
    {label: "DICOM PS3.4 §B – Storage Service Class (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_B"},
  ]],

  ["help.section_dmwl", "help.body_dmwl",
  [
    {label: "DICOM PS3.4 §K – Modality Worklist Management (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_K"},
  ]],

  ["help.section_commit", "help.body_commit",
  [
    {label: "DICOM PS3.4 §J – Storage Commitment Service Class (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_J"},
  ]],

  ["help.section_iocm", "help.body_iocm",
  [
    {label: "DICOM PS3.4 §KK – Instance Availability Notification (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_KK"},
  ]],

  ["help.section_inspector", "help.body_inspector", []],

  ["help.section_uid_remap", "help.body_uid_remap", []],

  ["help.section_validator", "help.body_validator",
  [
    {label: "DICOM PS3.5 §7 – Data Element Structure (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part05.html#chapter_7"},
    {label: "DICOM PS3.3 – Information Object Definitions (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html"},
  ]],

  ["help.section_sr_viewer", "help.body_sr_viewer",
  [
    {label: "DICOM PS3.3 §C.17 – Structured Reporting IODs (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#chapter_C"},
    {label: "DICOM PS3.3 §A.35 – SR Document Storage SOP Classes (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_A.35"},
    {label: "DICOM PS3.16 Chapter D – DICOM Coded Entry Resources (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/chtml/part16/chapter_D.html"},
  ]],

  ["help.section_kos_creator", "help.body_kos_creator",
  [
    {label: "DICOM PS3.3 §C.17.6 – Key Object Selection Document IOD (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_C.17.6"},
    {label: "IHE RAD TF Vol. 1 – XDS-I.b Integration Profile (IHE)", url: "https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol1.pdf"},
  ]],

  ["help.section_dicomize", "help.body_dicomize",
  [
    {label: "DICOM PS3.3 §A.45 – Encapsulated PDF Storage (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_A.45"},
    {label: "DICOM PS3.3 §A.8 – Secondary Capture Image Storage (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_A.8"},
    {label: "DICOM PS3.3 §A.32.6 – Video Photographic Image Storage (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_A.32.6"},
    {label: "DICOM PS3.3 §A.8.19 – Multi-frame True Color Secondary Capture (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_A.8.19"},
  ]],

  ["help.section_anonymizer", "help.body_anonymizer", []],

  ["help.section_dicomdir", "help.body_dicomdir",
  [
    {label: "DICOM PS3.10 §8 – DICOMDIR File (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part10.html#sect_8"},
  ]],

  ["help.section_dicomweb", "help.body_dicomweb",
  [
    {label: "DICOM PS3.18 – Web Services (NEMA)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part18.html"},
    {label: "PS3.18 §6.7 – QIDO-RS (Query)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part18.html#sect_6.7"},
    {label: "PS3.18 §6.6 – STOW-RS (Store)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part18.html#sect_6.6"},
    {label: "PS3.18 §6.5 – WADO-RS (Retrieve)", url: "https://dicom.nema.org/medical/dicom/current/output/html/part18.html#sect_6.5"},
  ]],

  ["help.section_hl7_send", "help.body_hl7_send",
  [
    {label: "ORM^O01 – Radiology Order (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ORM_O01"},
    {label: "ORU^R01 – Radiology Report (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ORU_R01"},
    {label: "ADT^A04 – Register Patient (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A04"},
    {label: "ADT^A08 – Update Patient (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A08"},
    {label: "ADT^A23 – Delete Visit (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A23"},
    {label: "SIU^S12 – Schedule Appointment (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/SIU_S12"},
    {label: "SIU^S15 – Cancel Appointment (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/SIU_S15"},
    {label: "QBP^Q22 – Patient Demographics Query (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/QBP_Q22"},
    {label: "OML^O21 – Lab Order (Caristix HL7 v2.4)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/OML_O21"},
  ]],

  ["help.section_hl7_recv", "help.body_hl7_recv",
  [
    {label: "HL7 v2.4 Message Definitions (Caristix)", url: "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents"},
    {label: "MLLP Transport Specification (HL7 TN)", url: "https://www.hl7.org/documentcenter/public/wg/inm/mllp_transport_specification.PDF"},
  ]],

  ["help.section_settings", "help.body_settings",
  []],

  ["help.section_logs", "help.body_logs",
  []],

  ["help.section_about", "help.body_about",
  [
    {label: "GitHub Releases – PACSAdminTool", url: "https://github.com/bobvmierlo/PACSAdminTool/releases"},
  ]],
];

function buildHelp() {
  const ul = document.getElementById("help-topic-list");
  HELP_SECTIONS.forEach(([title, _], i) => {
    const li = document.createElement("li");
    li.textContent = i18n(title);
    li.onclick = () => showHelp(i);
    if (i === 0) li.classList.add("active");
    ul.appendChild(li);
  });
  showHelp(0);
}

function showHelp(idx) {
  const [title, body, links] = HELP_SECTIONS[idx];
  document.getElementById("help-title").textContent = i18n(title);
  document.getElementById("help-body").textContent  = i18n(body);
  const linksDiv = document.getElementById("help-links");
  linksDiv.innerHTML = "";
  if (links && links.length) {
    const lbl = document.createElement("p");
    lbl.className = "help-links-label";
    lbl.textContent = i18n("help.official_docs_web");
    linksDiv.appendChild(lbl);
    links.forEach(({label, url}) => {
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "↗ " + label;
      linksDiv.appendChild(a);
      linksDiv.appendChild(document.createElement("br"));
    });
  }
  document.querySelectorAll("#help-topic-list li").forEach((li, i) =>
    li.classList.toggle("active", i === idx));
}

