// hl7-inspector.js — Deep HL7 v2 message inspector (hl7inspector.com-style)
// Extracted-style plain script (shared global scope, no modules).
//
// Complements the lightweight segment/field inspector in hl7-tools.js with a
// full hierarchical drill-down: Message → Segment → Field → Repetition →
// Component → Sub-component. Every node is addressed by its HL7 position
// (e.g. PID-5.1) and named from the HL7 v2 standard. Clicking a node shows a
// detail pane with data type, optionality, cardinality, and the raw plus
// escape-decoded value. Field/component definitions are loaded at runtime from
// web/static/hl7ref/<version>.json — generated at build time from hl7apy, see
// tools/generate_hl7_reference.py — with the version chosen from MSH-12.
// ─────────────────────────────────────────────────────────────────

// ── Display labels not carried by the structural HL7 database ─────────────────
// The field/component structure (names, data types, cardinality) is loaded at
// runtime from web/static/hl7ref/<version>.json, generated at build time from
// hl7apy (see tools/generate_hl7_reference.py). hl7apy does not, however,
// provide friendly *display names* for whole segments or data types, nor prose
// descriptions of trigger events — those are not part of the structural
// database. The compact maps below supply just those human labels; unknown ids
// fall back to the raw HL7 mnemonic.

// Friendly names for whole composite data types (id → name).
const _HL7_DT_NAMES = {
  HD: "Hierarchic Designator", MSG: "Message Type", PT: "Processing Type",
  VID: "Version Identifier", EI: "Entity Identifier",
  CX: "Extended Composite ID w/ Check Digit", XPN: "Extended Person Name",
  XCN: "Extended Composite ID Number and Name", XAD: "Extended Address",
  XTN: "Extended Telecommunication Number",
  XON: "Extended Composite Name/ID for Organizations",
  CWE: "Coded With Exceptions", CNE: "Coded No Exceptions", CE: "Coded Element",
  PL: "Person Location", TQ: "Timing/Quantity", TS: "Time Stamp",
  DTM: "Date/Time", DT: "Date", TM: "Time", DR: "Date/Time Range",
  SN: "Structured Numeric", MO: "Money", CQ: "Composite Quantity w/ Units",
  CP: "Composite Price", FN: "Family Name", SAD: "Street Address",
  ELD: "Error Location and Description", ERL: "Error Location",
  SI: "Sequence ID", ST: "String", NM: "Numeric", ID: "Coded (HL7 table)",
  IS: "Coded (user table)", TX: "Text", FT: "Formatted Text",
};

// Friendly names for whole segments (id → name). Unknown / Z-segments fall
// back to the raw 3-char id.
const _HL7_SEG_NAMES = {
  MSH: "Message Header", MSA: "Message Acknowledgment", ERR: "Error",
  EVN: "Event Type", PID: "Patient Identification",
  PD1: "Patient Additional Demographic", NK1: "Next of Kin / Associated Parties",
  PV1: "Patient Visit", PV2: "Patient Visit — Additional Information",
  ROL: "Role", DB1: "Disability", OBX: "Observation / Result",
  AL1: "Patient Allergy Information", DG1: "Diagnosis", DRG: "Diagnosis Related Group",
  PR1: "Procedures", GT1: "Guarantor", IN1: "Insurance",
  IN2: "Insurance — Additional Info", IN3: "Insurance — Additional Info, Cert.",
  ACC: "Accident", UB1: "UB82 Data", UB2: "UB92 Data", NTE: "Notes and Comments",
  ORC: "Common Order", OBR: "Observation Request", RQD: "Requisition Detail",
  RQ1: "Requisition Detail — 1", RXO: "Pharmacy/Treatment Order",
  RXR: "Pharmacy/Treatment Route", RXA: "Pharmacy/Treatment Administration",
  RXE: "Pharmacy/Treatment Encoded Order", SPM: "Specimen",
  SAC: "Specimen Container Detail", TQ1: "Timing/Quantity",
  TQ2: "Timing/Quantity Relationship", FT1: "Financial Transaction",
  SCH: "Scheduling Activity Information", RGS: "Resource Group",
  AIS: "Appointment Info — Service", AIG: "Appointment Info — General Resource",
  AIL: "Appointment Info — Location Resource",
  AIP: "Appointment Info — Personnel Resource",
  QRD: "Query Definition", QRF: "Query Filter", QPD: "Query Parameter Definition",
  RCP: "Response Control Parameter", QAK: "Query Acknowledgment",
  DSC: "Continuation Pointer", PRT: "Participation",
  ZDS: "Study Instance UID (local Z-segment)",
  MRG: "Merge Patient Information", TXA: "Transcription Document Header",
  MFI: "Master File Identification", MFE: "Master File Entry",
  STF: "Staff Identification", PRA: "Practitioner Detail",
};

// hl7apy uses some "_SIMPLE" datatype suffixes internally; strip for display.
function _hl7DtName(dt) {
  if (!dt) return dt;
  const base = dt.replace(/_SIMPLE$/, "");
  return _HL7_DT_NAMES[base] || base;
}

// ── Runtime reference data (loaded from web/static/hl7ref) ────────────────────
// _hl7Ref.index : { default, versions:[...] } ; _hl7Ref.byVersion : cache.
const _hl7Ref = { index: null, byVersion: {} };

async function _hl7LoadIndex() {
  if (_hl7Ref.index) return _hl7Ref.index;
  try {
    const res = await fetch("/static/hl7ref/index.json");
    _hl7Ref.index = await res.json();
  } catch {
    _hl7Ref.index = { default: "2.5.1", versions: ["2.5.1"] };
  }
  return _hl7Ref.index;
}

// Resolve a raw MSH-12 version string to a bundled reference version.
function _hl7ResolveVersion(raw, index) {
  const want = (raw || "").trim();
  const list = index.versions || [];
  if (list.includes(want)) return want;
  // Fall back to the newest bundled version sharing the same major.minor,
  // else the index default.
  const mm = want.match(/^(\d+\.\d+)/);
  if (mm) {
    const match = list.filter(v => v.startsWith(mm[1])).sort().pop();
    if (match) return match;
  }
  return index.default;
}

async function _hl7LoadVersion(version) {
  if (_hl7Ref.byVersion[version]) return _hl7Ref.byVersion[version];
  let data = { segments: {}, datatypes: {} };
  try {
    const res = await fetch(`/static/hl7ref/${version}.json`);
    if (res.ok) data = await res.json();
  } catch { /* offline / missing — degrade to positional labels */ }
  _hl7Ref.byVersion[version] = data;
  return data;
}

// HL7 value tables (code → meaning), shared across versions. Loaded once.
async function _hl7LoadTables() {
  if (_hl7Ref.tables) return _hl7Ref.tables;
  let data = {};
  try {
    const res = await fetch("/static/hl7ref/tables.json");
    if (res.ok) data = await res.json();
  } catch { /* offline / missing — codes simply won't be decoded */ }
  _hl7Ref.tables = data;
  return data;
}

// Normalise a field's table id ("HL70038", "0038") to the tables.json key ("38").
function _hl7TableId(raw) {
  if (!raw) return null;
  const digits = String(raw).replace(/^HL7/i, "").replace(/^0+/, "");
  return digits || "0";
}

// Look up a table by a field/component table id. Returns { desc, values } or null.
function _hl7Table(model, tableRef) {
  const id = _hl7TableId(tableRef);
  return (id && model.tables && model.tables[id]) || null;
}

// Decode a single coded value against its table. Returns the meaning or null.
function _hl7DecodeCode(model, tableRef, value) {
  const t = _hl7Table(model, tableRef);
  if (!t || value == null || value === "") return null;
  return Object.prototype.hasOwnProperty.call(t.values, value) ? t.values[value] : null;
}

// Human-readable trigger-event descriptions, keyed by "CODE^EVENT".
const _HL7_MSG_TYPES = {
  "ADT^A01": "Admit / Visit Notification",
  "ADT^A02": "Transfer a Patient",
  "ADT^A03": "Discharge / End Visit",
  "ADT^A04": "Register a Patient",
  "ADT^A05": "Pre-Admit a Patient",
  "ADT^A06": "Change an Outpatient to an Inpatient",
  "ADT^A07": "Change an Inpatient to an Outpatient",
  "ADT^A08": "Update Patient Information",
  "ADT^A11": "Cancel Admit / Visit Notification",
  "ADT^A12": "Cancel Transfer",
  "ADT^A13": "Cancel Discharge / End Visit",
  "ADT^A17": "Swap Patients",
  "ADT^A23": "Delete a Patient Record",
  "ADT^A28": "Add Person Information",
  "ADT^A31": "Update Person Information",
  "ADT^A40": "Merge Patient — Patient Identifier List",
  "ADT^A44": "Move Account Information",
  "ORM^O01": "Order Message (General)",
  "ORR^O02": "Order Response",
  "OMG^O19": "General Clinical Order",
  "OMI^O23": "Imaging Order",
  "OML^O21": "Laboratory Order",
  "OML^O33": "Lab Order (Specimen-Centric)",
  "ORU^R01": "Observation Result — Unsolicited",
  "ORU^R30": "Unsolicited Point-of-Care Observation",
  "OUL^R21": "Unsolicited Laboratory Observation",
  "ACK":     "General Acknowledgment",
  "SIU^S12": "Notification of New Appointment Booking",
  "SIU^S13": "Notification of Appointment Rescheduling",
  "SIU^S14": "Notification of Appointment Modification",
  "SIU^S15": "Notification of Appointment Cancellation",
  "SIU^S17": "Notification of Appointment Deletion",
  "SIU^S26": "Notification Patient Did Not Show for Appointment",
  "MDM^T02": "Original Document Notification & Content",
  "MDM^T04": "Document Status Change Notification & Content",
  "MFN^M02": "Master File — Staff/Practitioner",
  "QRY^A19": "Patient Query",
  "RSP^K11": "Segment Pattern Response",
  "DFT^P03": "Post Detail Financial Transaction",
  "BAR^P01": "Add Patient Account",
};

// HL7 escape sequences (\X\) decoded against the message's encoding chars.
function _hl7DecodeEscapes(value, enc) {
  if (!value || value.indexOf(enc.esc) === -1) return value;
  const e = enc.esc;
  // Split on escape char pairs: \...\
  let out = "";
  let i = 0;
  while (i < value.length) {
    if (value[i] === e) {
      const end = value.indexOf(e, i + 1);
      if (end === -1) { out += value.slice(i); break; }
      const code = value.slice(i + 1, end);
      out += _hl7EscToText(code, enc);
      i = end + 1;
    } else {
      out += value[i];
      i++;
    }
  }
  return out;
}

function _hl7EscToText(code, enc) {
  if (code === "F") return enc.field;
  if (code === "S") return enc.comp;
  if (code === "T") return enc.sub;
  if (code === "R") return enc.rep;
  if (code === "E") return enc.esc;
  if (code === ".br") return "\n";
  if (code === "X" || code[0] === "X") {           // \Xdddd\ — hex bytes
    const hex = code.slice(1);
    let s = "";
    for (let k = 0; k + 1 < hex.length; k += 2) {
      const b = parseInt(hex.substr(k, 2), 16);
      if (!isNaN(b)) s += String.fromCharCode(b);
    }
    return s || "";
  }
  if (code === "H" || code === "N") return "";      // highlight on/off — drop
  return "";                                         // unknown escape — drop
}

// ── Encoding-aware parse into a structured model ─────────────────────────────
// Returns { enc, segments:[{ id, index, fields:[ { raw, reps:[ [comp...] ] } ] }] }
function _hl7DeepParse(raw) {
  const clean = raw.replace(/\r\n/g, "\r").replace(/\n/g, "\r");
  const lines = clean.split("\r").map(l => l.replace(/[\s﻿]+$/, "")).filter(l => l.trim().length);

  // Derive encoding characters from the first MSH segment (fall back to defaults).
  let enc = { field: "|", comp: "^", rep: "~", esc: "\\", sub: "&" };
  const mshLine = lines.find(l => l.startsWith("MSH"));
  if (mshLine && mshLine.length >= 8) {
    enc.field = mshLine[3];
    const encChars = mshLine.slice(4, 8);   // MSH-2, e.g. ^~\&
    enc.comp = encChars[0] || "^";
    enc.rep  = encChars[1] || "~";
    enc.esc  = encChars[2] || "\\";
    enc.sub  = encChars[3] || "&";
  }

  const segments = lines.map((line, index) => {
    const id = line.slice(0, 3);
    const isMSH = id === "MSH";
    const parts = line.split(enc.field);
    const fields = [];

    if (isMSH) {
      // MSH-1 is the field separator itself; MSH-2 the encoding chars.
      fields.push({ raw: enc.field, reps: [[[enc.field]]], atomic: true });      // MSH-1
      fields.push({ raw: parts[1] || "", reps: [[[parts[1] || ""]]], atomic: true }); // MSH-2
      for (let n = 2; n < parts.length; n++) {
        fields.push(_hl7SplitField(parts[n], enc));
      }
    } else {
      for (let n = 1; n < parts.length; n++) {
        fields.push(_hl7SplitField(parts[n], enc));
      }
    }
    return { id, index, fields, raw: line };
  });

  return { enc, segments };
}

// Split one field's raw text into repetitions → components → sub-components.
function _hl7SplitField(rawField, enc) {
  const reps = (rawField === "" ? [""] : rawField.split(enc.rep)).map(rep =>
    (rep === "" ? [""] : rep.split(enc.comp)).map(comp =>
      comp === "" ? [""] : comp.split(enc.sub)
    )
  );
  return { raw: rawField, reps };
}

// ── Look-ups against the loaded reference (model.ref) ────────────────────────
// Reference field rows are [name, datatype, min, max, table]; optionality and
// repeatability are derived from cardinality.
function _hl7FieldDef(model, segId, fieldNum) {
  const seg = model.ref && model.ref.segments[segId];
  const f = seg && seg[fieldNum - 1];
  if (!f) return null;
  const [name, dt, mn, mx, table] = f;
  return {
    name, dt, min: mn, max: mx, table,
    opt: mn >= 1 ? "R" : "O",
    rep: (mx === -1 || mx > 1) ? "Y" : "N",
  };
}

function _hl7CompDef(model, dataType, compNum) {
  const base = dataType && dataType.replace(/_SIMPLE$/, "");
  const dt = model.ref && base && model.ref.datatypes[base];
  const c = dt && dt[compNum - 1];
  return c ? { name: c[0], dt: c[1], table: c[2] || null } : null;
}

function _hl7CompName(model, dataType, compNum) {
  const d = _hl7CompDef(model, dataType, compNum);
  return d ? d.name : null;
}

// Is this a segment the reference knows about?
function _hl7SegKnown(model, segId) {
  return !!(model.ref && model.ref.segments[segId]);
}

function _hl7SegName(model, segId) {
  return _HL7_SEG_NAMES[segId] || segId;
}

// ── Rendering ────────────────────────────────────────────────────────────────
let _hl7DeepModel = null;    // last parsed model, for the detail pane
let _hl7DeepSelected = null; // currently selected node path string

async function hl7DeepInspect() {
  const raw = (document.getElementById("hl7insp-input")?.value || "");
  if (!raw.trim()) { toast(i18n("hl7.no_message"), "warn"); return; }

  const model = _hl7DeepParse(raw);

  // Choose the reference version from MSH-12 and load it (once, cached).
  const msh = model.segments.find(s => s.id === "MSH");
  const mshVer = msh && msh.fields[11]
    ? msh.fields[11].raw.split(model.enc.comp)[0]   // MSH-12.1 (version ID)
    : "";
  const index = await _hl7LoadIndex();
  model.versionRequested = mshVer;
  model.version = _hl7ResolveVersion(mshVer, index);
  model.ref = await _hl7LoadVersion(model.version);
  model.tables = await _hl7LoadTables();

  _hl7DeepModel = model;
  _hl7DeepSelected = null;
  _hl7RenderSummary(_hl7DeepModel);
  _hl7RenderTree(_hl7DeepModel);
  _hl7RenderValidation(_hl7DeepModel);
  document.getElementById("hl7insp-results").style.display = "";
  const detail = document.getElementById("hl7insp-detail-content");
  if (detail) detail.innerHTML =
    `<div style="color:#888;font-size:12px">Click any node in the tree to see its definition and value.</div>`;
}

function _hl7RenderSummary(model) {
  const el = model && document.getElementById("hl7insp-summary");
  if (!el) return;
  const msh = model.segments.find(s => s.id === "MSH");
  const fieldVal = (seg, n) => {
    const f = seg && seg.fields[n - 1];
    return f ? f.raw : "";
  };
  const msgTypeRaw = fieldVal(msh, 9);
  const msgKey = msgTypeRaw.split(model.enc.sub)[0].split(model.enc.comp).slice(0, 2).join("^");
  const codeOnly = msgKey.split("^")[0];
  const desc = _HL7_MSG_TYPES[msgKey] || _HL7_MSG_TYPES[codeOnly] || "";
  const chip = (label, val) => val
    ? `<div style="display:flex;flex-direction:column;gap:1px">
         <span style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.03em">${label}</span>
         <span style="font-size:12px;color:#1e293b;font-weight:600">${escapeHtml(val)}</span>
       </div>`
    : "";
  const segCounts = {};
  model.segments.forEach(s => { segCounts[s.id] = (segCounts[s.id] || 0) + 1; });
  const segList = Object.entries(segCounts)
    .map(([id, n]) => n > 1 ? `${id}×${n}` : id).join(" · ");

  el.innerHTML =
    `<div style="display:flex;flex-wrap:wrap;gap:18px 26px;align-items:flex-start">` +
    chip("Message Type", msgTypeRaw || "—") +
    (desc ? chip("Description", desc) : "") +
    chip("Control ID", fieldVal(msh, 10)) +
    chip("Version", fieldVal(msh, 12)) +
    chip("Processing ID", fieldVal(msh, 11)) +
    chip("Timestamp", fieldVal(msh, 7)) +
    chip("Sending", [fieldVal(msh, 3), fieldVal(msh, 4)].filter(Boolean).join(" / ")) +
    chip("Receiving", [fieldVal(msh, 5), fieldVal(msh, 6)].filter(Boolean).join(" / ")) +
    chip("Segments", `${model.segments.length}`) +
    `</div>` +
    `<div style="margin-top:10px;font-size:11px;color:#64748b;font-family:Consolas,monospace">${escapeHtml(segList)}</div>` +
    `<div style="margin-top:6px;font-size:11px;color:#94a3b8">Definitions: HL7 v${escapeHtml(model.version || "?")}` +
    (model.versionRequested && model.versionRequested !== model.version
      ? ` <span style="color:#b45309">(MSH-12 said “${escapeHtml(model.versionRequested)}”, using nearest bundled version)</span>` : "") +
    `</div>`;
}

function _hl7RenderTree(model) {
  const root = document.getElementById("hl7insp-tree");
  if (!root) return;
  root.innerHTML = "";
  model.segments.forEach(seg => root.appendChild(_hl7SegBlock(seg, model)));
}

// Small DOM helpers ----------------------------------------------------------
function _hl7Caret() {
  const c = document.createElement("span");
  c.className = "hl7insp-caret";
  c.textContent = "▸";
  c.style.cssText = "font-size:9px;color:#94a3b8;width:10px;display:inline-block;transition:transform .1s";
  return c;
}

function _hl7Span(text, css) {
  const s = document.createElement("span");
  s.textContent = text;
  s.style.cssText = css;
  return s;
}

// A collapsible block = a header row + a children container.
// Clicking the header toggles the children; startOpen sets the initial state.
function _hl7Block(headerRow, caret, childrenEl, startOpen) {
  const wrap = document.createElement("div");
  wrap.className = "hl7insp-block";
  childrenEl.className = ((childrenEl.className || "") + " hl7insp-children").trim();
  childrenEl.style.display = startOpen ? "" : "none";
  caret.style.transform = startOpen ? "rotate(90deg)" : "";
  headerRow.addEventListener("click", () => {
    const open = childrenEl.style.display !== "none";
    childrenEl.style.display = open ? "none" : "";
    caret.style.transform = open ? "" : "rotate(90deg)";
  });
  wrap.appendChild(headerRow);
  wrap.appendChild(childrenEl);
  return wrap;
}

// Generic row (leaf or expandable header). Returns { el, caret }.
// `hint` — an optional decoded code meaning shown after the value.
function _hl7Row({ pos, name, dt, value, required, empty, caret, onSelect, muted, hint }) {
  const el = document.createElement("div");
  el.className = "hl7insp-node hl7insp-leaf";
  el.dataset.pos = pos;
  el.dataset.search = (pos + " " + name + " " + (value || "") + " " + (hint || "")).toLowerCase();
  el.style.cssText = "display:flex;align-items:center;gap:6px;padding:3px 6px;cursor:pointer;border-radius:4px;font-size:12px";

  const car = _hl7Caret();
  if (!caret) car.textContent = "";
  el.appendChild(car);

  el.appendChild(_hl7Span(pos,
    "font-family:Consolas,monospace;min-width:82px;font-size:11px;color:" + (muted ? "#94a3b8" : "#0f766e")));

  const nm = _hl7Span(name + (required ? " *" : ""),
    "color:" + (required ? "#b91c1c" : "#475569") + ";white-space:nowrap");
  if (required) nm.title = "Required field";
  el.appendChild(nm);

  if (dt) el.appendChild(_hl7Span(dt,
    "font-size:10px;color:#94a3b8;font-family:Consolas,monospace;border:1px solid #e2e8f0;border-radius:3px;padding:0 4px"));

  const val = _hl7Span(empty ? "∅" : (value || ""),
    "margin-left:auto;font-family:Consolas,monospace;padding:0 5px;border-radius:3px;" +
    "max-width:46%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:" +
    (empty ? "#cbd5e1" : "#111827") + ";background:" + (empty ? "transparent" : "#f8fafc"));
  val.title = value || "";
  el.appendChild(val);

  if (hint) {
    const h = _hl7Span(hint,
      "flex-shrink:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" +
      "font-style:italic;color:#0f766e;font-size:11px");
    h.title = hint;
    el.appendChild(h);
  }

  el.addEventListener("click", ev => {
    ev.stopPropagation();       // don't toggle ancestor blocks
    _hl7HighlightNode(el);
    if (onSelect) onSelect();
  });
  return { el, caret: car };
}

function _hl7SegBlock(seg, model) {
  const known = _hl7SegKnown(model, seg.id);
  const segName = _hl7SegName(model, seg.id);
  const unknown = !known;
  const head = document.createElement("div");
  head.className = "hl7insp-node hl7insp-seg-head";
  head.dataset.search = (seg.id + " " + segName).toLowerCase();
  head.style.cssText =
    "display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-radius:4px;margin-top:2px;" +
    "background:" + (unknown ? "#fff7ed" : "#eff6ff") + ";border:1px solid " + (unknown ? "#fed7aa" : "#dbeafe");
  const caret = _hl7Caret();
  head.appendChild(caret);
  head.appendChild(_hl7Span(seg.id,
    "font-family:Consolas,monospace;font-weight:700;color:" + (unknown ? "#c2410c" : "#1d4ed8")));
  head.appendChild(_hl7Span(unknown ? segName + " (custom / not in reference)" : segName,
    "font-size:12px;color:#475569"));
  head.appendChild(_hl7Span(`${seg.fields.length} fields`, "margin-left:auto;font-size:10px;color:#94a3b8"));
  head.addEventListener("click", () => { _hl7HighlightNode(head); _hl7SelectSegment(seg, model); });

  const kids = document.createElement("div");
  kids.style.cssText = "margin-left:14px;border-left:1px solid #e2e8f0;padding-left:8px";
  seg.fields.forEach((field, idx) => _hl7AppendField(kids, seg, idx + 1, field, model));

  return _hl7Block(head, caret, kids, true);  // fields visible by default
}

function _hl7AppendField(container, seg, fieldNum, field, model) {
  const def = _hl7FieldDef(model, seg.id, fieldNum);
  const dataType = def ? def.dt : null;
  const label = (def && def.name) ? def.name : `Field ${fieldNum}`;
  const pos = `${seg.id}-${fieldNum}`;
  const expandable = !field.atomic && (
    field.reps.length > 1 ||
    field.reps.some(rep => rep.length > 1 || rep.some(c => c.length > 1))
  );

  // Decode a primitive coded field (e.g. ORC-5 → table 0038) inline.
  const meaning = (!expandable && def && def.table)
    ? _hl7DecodeCode(model, def.table, field.raw) : null;

  const row = _hl7Row({
    pos, name: label, dt: dataType, value: field.raw,
    required: !!(def && def.opt === "R"), empty: field.raw === "",
    caret: expandable, hint: meaning,
    onSelect: () => _hl7SelectField(seg, fieldNum, field, def, model),
  });
  if (!expandable) { container.appendChild(row.el); return; }

  const kids = document.createElement("div");
  kids.style.cssText = "margin-left:14px;border-left:1px solid #eef2f6;padding-left:8px";
  _hl7AppendReps(kids, seg, fieldNum, field, dataType, model);
  container.appendChild(_hl7Block(row.el, row.caret, kids, false));
}

function _hl7AppendReps(container, seg, fieldNum, field, dataType, model) {
  const multi = field.reps.length > 1;
  field.reps.forEach((rep, ri) => {
    if (!multi) { _hl7AppendComponents(container, seg, fieldNum, rep, dataType, model, ""); return; }
    const tag = `[${ri + 1}]`;
    const repRaw = rep.map(c => c.join(model.enc.sub)).join(model.enc.comp);
    const row = _hl7Row({
      pos: `${seg.id}-${fieldNum}${tag}`, name: `Repetition ${ri + 1}`, dt: dataType,
      value: repRaw, muted: true,
      caret: rep.length > 1 || rep.some(c => c.length > 1),
      onSelect: () => _hl7SelectValue(`${seg.id}-${fieldNum}${tag}`, dataType, repRaw, model),
    });
    const kids = document.createElement("div");
    kids.style.cssText = "margin-left:14px;border-left:1px solid #eef2f6;padding-left:8px";
    _hl7AppendComponents(kids, seg, fieldNum, rep, dataType, model, tag);
    container.appendChild(_hl7Block(row.el, row.caret, kids, true));
  });
}

function _hl7AppendComponents(container, seg, fieldNum, comps, dataType, model, repTag) {
  if (comps.length === 1 && comps[0].length === 1) return;  // primitive — nothing to break down
  comps.forEach((subs, ci) => {
    const compNum = ci + 1;
    const compDef = _hl7CompDef(model, dataType, compNum);
    const name = (compDef && compDef.name) || `Component ${compNum}`;
    const compDt = compDef ? compDef.dt : null;
    const raw = subs.join(model.enc.sub);
    const pos = `${seg.id}-${fieldNum}${repTag}.${compNum}`;
    const hasSubs = subs.length > 1;
    const compTable = compDef ? compDef.table : null;
    const meaning = (!hasSubs && compTable) ? _hl7DecodeCode(model, compTable, raw) : null;
    const row = _hl7Row({
      pos, name, dt: (hasSubs ? compDt : null), value: raw, empty: raw === "", caret: hasSubs, hint: meaning,
      onSelect: () => _hl7SelectValue(pos, compDt, raw, model, name, compTable),
    });
    if (!hasSubs) { container.appendChild(row.el); return; }
    const kids = document.createElement("div");
    kids.style.cssText = "margin-left:14px;border-left:1px solid #f1f5f9;padding-left:8px";
    subs.forEach((sv, si) => {
      // Sub-components are named from the component's own composite datatype.
      const subDef = _hl7CompDef(model, compDt, si + 1);
      const subName = (subDef && subDef.name) || `Sub-component ${si + 1}`;
      const spos = `${pos}.${si + 1}`;
      kids.appendChild(_hl7Row({
        pos: spos, name: subName, value: sv, empty: sv === "",
        onSelect: () => _hl7SelectValue(spos, null, sv, model, subName),
      }).el);
    });
    container.appendChild(_hl7Block(row.el, row.caret, kids, false));
  });
}

function _hl7HighlightNode(el) {
  document.querySelectorAll("#hl7insp-tree .hl7insp-node.selected").forEach(n => {
    n.classList.remove("selected");
    n.style.outline = "";
  });
  el.classList.add("selected");
  el.style.outline = "2px solid #3b82f6";
}

// ── Detail-pane selection handlers ───────────────────────────────────────────
// Render an HL7 cardinality pair (min, max) — max -1 means unbounded.
function _hl7Card(mn, mx) {
  return `${mn}..${mx === -1 ? "*" : mx}`;
}

function _hl7SelectSegment(seg, model) {
  const el = document.getElementById("hl7insp-detail-content");
  if (!el) return;
  const known = _hl7SegKnown(model, seg.id);
  const name = _hl7SegName(model, seg.id);
  const fields = (model.ref && model.ref.segments[seg.id]) || [];
  let html =
    `<div style="font-weight:700;color:#1d4ed8;font-size:14px;margin-bottom:8px">${escapeHtml(seg.id)} — ${escapeHtml(name)}</div>`;
  if (known && fields.length) {
    html += `<table style="width:100%;border-collapse:collapse;font-size:11px">
      <tr style="background:#f1f5f9"><th style="text-align:left;padding:3px 5px">#</th>
      <th style="text-align:left;padding:3px 5px">Field</th>
      <th style="text-align:left;padding:3px 5px">Type</th>
      <th style="text-align:left;padding:3px 5px">Card.</th></tr>` +
      fields.map((f, i) => {
        const [fname, dt, mn, mx] = f;
        return `<tr style="border-bottom:1px solid #eef2f6">
          <td style="padding:2px 5px;color:#94a3b8">${i + 1}</td>
          <td style="padding:2px 5px">${escapeHtml(fname || "—")}</td>
          <td style="padding:2px 5px;font-family:Consolas;color:#6b7280">${escapeHtml(dt || "")}</td>
          <td style="padding:2px 5px;color:${mn >= 1 ? '#b91c1c' : '#6b7280'};font-family:Consolas">${_hl7Card(mn, mx)}</td>
        </tr>`;
      }).join("") + `</table>`;
  } else {
    html += `<div style="color:#c2410c;font-size:12px">Not in the HL7 v${escapeHtml(model.version || "?")} reference (custom / Z-segment) — parsed positionally.</div>`;
  }
  el.innerHTML = html;
}

function _hl7SelectField(seg, fieldNum, field, def, model) {
  const el = document.getElementById("hl7insp-detail-content");
  if (!el) return;
  const OPT = { R: "Required", O: "Optional" };
  const REP = { Y: "Repeatable", N: "Non-repeatable" };
  const dtFriendly = def && _hl7DtName(def.dt);
  const comps = def && _hl7DtComps(model, def.dt);
  const decoded = _hl7DecodeEscapes(field.raw, model.enc);
  const showDecoded = decoded !== field.raw;

  let html =
    `<div style="font-weight:700;color:#0f766e;font-size:14px;margin-bottom:6px">${escapeHtml(seg.id)}-${fieldNum}` +
    (def && def.name ? ` — ${escapeHtml(def.name)}` : "") + `</div>`;
  if (def) {
    html += `<table style="width:100%;border-collapse:collapse;font-size:11px;margin-bottom:8px">
      <tr><td style="color:#94a3b8;padding:2px 0;width:96px">Data type</td>
          <td style="font-family:Consolas">${escapeHtml(def.dt || "")}${dtFriendly && dtFriendly !== def.dt ? ` — ${escapeHtml(dtFriendly)}` : ""}</td></tr>
      <tr><td style="color:#94a3b8;padding:2px 0">Optionality</td><td>${OPT[def.opt] || def.opt}</td></tr>
      <tr><td style="color:#94a3b8;padding:2px 0">Repeatable</td><td>${REP[def.rep] || def.rep}</td></tr>
      <tr><td style="color:#94a3b8;padding:2px 0">Cardinality</td><td style="font-family:Consolas">${_hl7Card(def.min, def.max)}</td></tr>
      <tr><td style="color:#94a3b8;padding:2px 0">Repetitions</td><td>${field.reps.length}</td></tr>` +
      (def.table ? `<tr><td style="color:#94a3b8;padding:2px 0">Value table</td><td style="font-family:Consolas">${escapeHtml(def.table)}${_hl7Table(model, def.table) ? ` — ${escapeHtml(_hl7Table(model, def.table).desc)}` : ""}</td></tr>` : "") +
    `</table>`;
  } else {
    html += `<div style="color:#c2410c;font-size:12px;margin-bottom:8px">No reference definition for this field (custom segment) — parsed positionally.</div>`;
  }
  html += _hl7ValueBox("Raw value", field.raw);
  if (showDecoded) html += _hl7ValueBox("Decoded", decoded);
  // Coded value: show the meaning and the full value set for a primitive field.
  if (def && def.table && !field.atomic && field.reps.length === 1 &&
      (field.reps[0] || []).length === 1 && (field.reps[0][0] || []).length === 1) {
    html += _hl7TableBox(model, def.table, field.raw);
  }

  // Component breakdown for the first repetition, using the datatype's components.
  if (comps && comps.length && !field.atomic) {
    const rep = field.reps[0] || [];
    html += `<div style="font-size:11px;color:#94a3b8;margin:10px 0 3px">Components${dtFriendly ? ` (${escapeHtml(dtFriendly)})` : ""}</div>`;
    html += `<table style="width:100%;border-collapse:collapse;font-size:11px">`;
    comps.forEach((c, i) => {
      const v = (rep[i] || []).join(model.enc.sub);
      if (!v && i >= rep.length) return;
      html += `<tr style="border-bottom:1px solid #eef2f6">
        <td style="padding:2px 5px;color:#94a3b8;font-family:Consolas">.${i + 1}</td>
        <td style="padding:2px 5px">${escapeHtml(c[0] || "")}</td>
        <td style="padding:2px 5px;font-family:Consolas;color:#111827">${escapeHtml(v) || '<span style="color:#cbd5e1">∅</span>'}</td>
      </tr>`;
    });
    html += `</table>`;
  }
  el.innerHTML = html;
}

function _hl7SelectValue(pos, dataType, value, model, name, tableRef) {
  const el = document.getElementById("hl7insp-detail-content");
  if (!el) return;
  const decoded = _hl7DecodeEscapes(value, model.enc);
  const dtFriendly = dataType && _hl7DtName(dataType);
  let html =
    `<div style="font-weight:700;color:#0f766e;font-size:14px;margin-bottom:6px">${escapeHtml(pos)}` +
    (name ? ` — ${escapeHtml(name)}` : "") + `</div>`;
  if (dataType) html += `<div style="font-size:11px;color:#64748b;margin-bottom:8px">${escapeHtml(dataType)}${dtFriendly && dtFriendly !== dataType ? ` — ${escapeHtml(dtFriendly)}` : ""}</div>`;
  html += _hl7ValueBox("Value", value);
  if (decoded !== value) html += _hl7ValueBox("Decoded", decoded);
  if (tableRef) html += _hl7TableBox(model, tableRef, value);
  if (!value) html += `<div style="color:#94a3b8;font-size:12px;margin-top:6px">This element is empty.</div>`;
  el.innerHTML = html;
}

// The component list for a datatype (strips hl7apy's _SIMPLE suffix).
function _hl7DtComps(model, dataType) {
  const base = dataType && dataType.replace(/_SIMPLE$/, "");
  return (model.ref && base && model.ref.datatypes[base]) || null;
}

function _hl7ValueBox(label, value) {
  return `<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.03em;margin:8px 0 2px">${label}</div>` +
    `<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:4px;padding:5px 7px;font-family:Consolas,monospace;font-size:12px;color:#0c4a6e;word-break:break-all;white-space:pre-wrap">${value ? escapeHtml(value) : '<span style="color:#94a3b8">∅ (empty)</span>'}</div>`;
}

// Render an HL7 value table: the current code's meaning plus the full value set,
// with the current value highlighted. Falls back to a codes-only note if the
// table has no descriptions bundled.
function _hl7TableBox(model, tableRef, value) {
  const t = _hl7Table(model, tableRef);
  const id = _hl7TableId(tableRef);
  if (!t) {
    return `<div style="font-size:11px;color:#94a3b8;margin-top:10px">Value table ${escapeHtml(String(tableRef))} not bundled.</div>`;
  }
  const meaning = value && Object.prototype.hasOwnProperty.call(t.values, value) ? t.values[value] : null;
  let html = `<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.03em;margin:10px 0 2px">Code meaning — table ${escapeHtml(id)} (${escapeHtml(t.desc)})</div>`;
  if (value && meaning) {
    html += `<div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:4px;padding:5px 7px;font-size:12px;color:#065f46">` +
      `<span style="font-family:Consolas,monospace;font-weight:700">${escapeHtml(value)}</span> — ${escapeHtml(meaning)}</div>`;
  } else if (value) {
    html += `<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:4px;padding:5px 7px;font-size:12px;color:#991b1b">` +
      `<span style="font-family:Consolas,monospace;font-weight:700">${escapeHtml(value)}</span> is not a valid code in this table.</div>`;
  }
  // Full value set (scrollable), current code highlighted.
  html += `<div style="max-height:180px;overflow:auto;border:1px solid #e2e8f0;border-radius:4px;margin-top:4px">` +
    `<table style="width:100%;border-collapse:collapse;font-size:11px">`;
  for (const [code, desc] of Object.entries(t.values)) {
    const hit = code === value;
    html += `<tr style="border-bottom:1px solid #eef2f6;background:${hit ? '#ecfdf5' : ''}">` +
      `<td style="padding:2px 6px;font-family:Consolas;color:#0f766e;white-space:nowrap;${hit ? 'font-weight:700' : ''}">${escapeHtml(code)}</td>` +
      `<td style="padding:2px 6px;color:#334155">${escapeHtml(desc)}</td></tr>`;
  }
  html += `</table></div>`;
  return html;
}

// ── Validation / analysis pane ───────────────────────────────────────────────
function _hl7RenderValidation(model) {
  const el = document.getElementById("hl7insp-validation");
  if (!el) return;
  const issues = [];

  if (!model.segments.length) {
    issues.push({ level: "err", text: "No segments found." });
  } else if (model.segments[0].id !== "MSH") {
    issues.push({ level: "err", text: "First segment is not MSH — every HL7 message must begin with MSH." });
  }

  model.segments.forEach(seg => {
    if (!/^[A-Z0-9]{3}$/.test(seg.id)) {
      issues.push({ level: "err", text: `Segment ${seg.index + 1} has an invalid ID "${seg.id}" (must be 3 characters).` });
      return;
    }
    const fieldDefs = model.ref && model.ref.segments[seg.id];
    if (!fieldDefs) {
      issues.push({ level: "info", text: `Segment ${seg.id} is not in the HL7 v${model.version} reference (custom or Z-segment) — shown but not validated.` });
      return;
    }
    fieldDefs.forEach((f, i) => {
      const [fname, , mn] = f;         // [name, datatype, min, max, table]
      if (mn < 1) return;              // only required (min ≥ 1) fields
      const seq = i + 1;
      // MSH-1/MSH-2 always present by construction; skip.
      if (seg.id === "MSH" && (seq === 1 || seq === 2)) return;
      const fld = seg.fields[seq - 1];
      if (!fld || fld.raw === "") {
        issues.push({ level: "warn", text: `${seg.id}-${seq} (${fname || "field"}) is required but empty.` });
      }
    });
  });

  const msh = model.segments.find(s => s.id === "MSH");
  if (msh) {
    const enc2 = msh.fields[1] ? msh.fields[1].raw : "";
    if (enc2 && enc2 !== "^~\\&") {
      issues.push({ level: "info", text: `Non-standard encoding characters in MSH-2: "${enc2}" (standard is ^~\\&).` });
    }
  }

  if (!issues.length) {
    el.innerHTML = `<div style="color:#15803d;font-size:12px">✓ No structural problems detected. ${model.segments.length} segment(s) parsed.</div>`;
    return;
  }
  const colour = { err: "#b91c1c", warn: "#b45309", info: "#0369a1" };
  const icon = { err: "✕", warn: "▲", info: "ℹ" };
  const counts = issues.reduce((a, i) => (a[i.level] = (a[i.level] || 0) + 1, a), {});
  el.innerHTML =
    `<div style="font-size:11px;color:#64748b;margin-bottom:6px">` +
    `${counts.err || 0} error(s) · ${counts.warn || 0} warning(s) · ${counts.info || 0} note(s)</div>` +
    issues.map(i =>
      `<div style="display:flex;gap:7px;font-size:12px;padding:2px 0;color:${colour[i.level]}">
         <span style="width:12px">${icon[i.level]}</span><span style="color:#334155">${escapeHtml(i.text)}</span>
       </div>`).join("");
}

// ── Toolbar actions ──────────────────────────────────────────────────────────
function hl7InspExpandAll() {
  const tree = document.getElementById("hl7insp-tree");
  if (!tree) return;
  tree.querySelectorAll(".hl7insp-children").forEach(c => c.style.display = "");
  tree.querySelectorAll(".hl7insp-caret").forEach(c => { if (c.textContent) c.style.transform = "rotate(90deg)"; });
}

function hl7InspCollapseAll() {
  const tree = document.getElementById("hl7insp-tree");
  if (!tree) return;
  tree.querySelectorAll(".hl7insp-children").forEach(c => c.style.display = "none");
  tree.querySelectorAll(".hl7insp-caret").forEach(c => { if (c.textContent) c.style.transform = ""; });
}

// Default view: each segment's field list open, deeper levels collapsed.
function hl7InspCollapseToDefault() {
  const tree = document.getElementById("hl7insp-tree");
  if (!tree) return;
  tree.querySelectorAll(".hl7insp-block, .hl7insp-node").forEach(n => n.style.display = "");
  tree.querySelectorAll(".hl7insp-leaf").forEach(n => n.style.background = "");
  tree.querySelectorAll(".hl7insp-children").forEach(c => c.style.display = "none");
  tree.querySelectorAll(".hl7insp-caret").forEach(c => { if (c.textContent) c.style.transform = ""; });
  Array.from(tree.children).forEach(segBlock => {
    if (!segBlock.classList.contains("hl7insp-block")) return;
    const box = segBlock.lastElementChild;
    if (box) box.style.display = "";
    const caret = segBlock.firstElementChild && segBlock.firstElementChild.querySelector(".hl7insp-caret");
    if (caret) caret.style.transform = "rotate(90deg)";
  });
}

function hl7InspFilter() {
  const q = (document.getElementById("hl7insp-search")?.value || "").trim().toLowerCase();
  const tree = document.getElementById("hl7insp-tree");
  if (!tree) return;
  tree.querySelectorAll(".hl7insp-leaf").forEach(n => n.style.background = "");
  if (!q) { hl7InspCollapseToDefault(); return; }
  hl7InspExpandAll();
  Array.from(tree.children).forEach(child => _hl7FilterNode(child, q));
}

// Post-order walk: show a subtree only if it or a descendant matches the query.
function _hl7FilterNode(el, q) {
  if (el.classList && el.classList.contains("hl7insp-block")) {
    const header = el.firstElementChild;
    const box    = el.lastElementChild;
    let anyChild = false;
    Array.from(box.children).forEach(c => { if (_hl7FilterNode(c, q)) anyChild = true; });
    const selfHit = (header.dataset.search || "").includes(q);
    // Tint value/field headers on a hit; leave segment headers' own colour intact.
    if (!header.classList.contains("hl7insp-seg-head")) header.style.background = selfHit ? "#fef9c3" : "";
    const show = selfHit || anyChild;
    el.style.display = show ? "" : "none";
    return show;
  }
  if (el.classList && el.classList.contains("hl7insp-node")) {
    const hit = (el.dataset.search || "").includes(q);
    el.style.background = hit ? "#fef9c3" : "";
    el.style.display = hit ? "" : "none";
    return hit;
  }
  return false;
}

function hl7InspLoadFromSend() {
  const src = document.getElementById("hl7-message");
  const dst = document.getElementById("hl7insp-input");
  if (src && dst) {
    dst.value = src.value;
    if (src.value.trim()) hl7DeepInspect();
    else toast("The Send tab message box is empty.", "warn");
  }
}

function hl7InspClear() {
  const inp = document.getElementById("hl7insp-input");
  if (inp) inp.value = "";
  const res = document.getElementById("hl7insp-results");
  if (res) res.style.display = "none";
  _hl7DeepModel = null;
}

// Load a sample message so the feature is discoverable without a live feed.
function hl7InspLoadSample() {
  const inp = document.getElementById("hl7insp-input");
  if (!inp) return;
  inp.value =
    "MSH|^~\\&|RIS|HOSPITAL|PACS|HOSPITAL|20240607123045||ORM^O01|MSG00001|P|2.5.1\r" +
    "PID|1||1234567^^^HOSP^MR~9876543^^^HOSP^PI||DOE^JOHN^A^^MR^^L||19800115|M|||123 MAIN ST^APT 4B^METROPOLIS^NY^10001^USA^H|||||||ACC-0001\r" +
    "PV1|1|O|RADIOLOGY^CT^01||||1234^SMITH^JANE^^^DR|||RAD||||||||VISIT-0001\r" +
    "ORC|NW|PLACER-001|FILLER-001||SC|||||||1234^SMITH^JANE^^^DR\r" +
    "OBR|1|PLACER-001|FILLER-001|CTHEAD^CT HEAD W/O CONTRAST^L||20240607|20240607123000||||||||CT|1234^SMITH^JANE^^^DR\r" +
    "ZDS|1.2.840.113619.2.55.3.604688.1.20240607";
  hl7DeepInspect();
}
