// hl7-tools.js — HL7 inspector, message history, MLLP listener controls
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// HL7 Inspector — segment/field definitions + parser
// ─────────────────────────────────────────────────────────────────

const _HL7_SEGMENTS = {
  MSH: { name:"Message Header", desc:"Defines the intent, source, destination, and some specifics of the syntax of a message.",
    fields:[
      {seq:1,name:"Field Separator",dt:"ST",opt:"R",rep:"N",desc:"The field separator character. Always '|'."},
      {seq:2,name:"Encoding Characters",dt:"ST",opt:"R",rep:"N",desc:"Encoding characters: component, repetition, escape, sub-component separators. Always '^~\\&'."},
      {seq:3,name:"Sending Application",dt:"HD",opt:"O",rep:"N",desc:"Identifies the sending application among all other applications within the network enterprise."},
      {seq:4,name:"Sending Facility",dt:"HD",opt:"O",rep:"N",desc:"Further identifies the sending application."},
      {seq:5,name:"Receiving Application",dt:"HD",opt:"O",rep:"N",desc:"Identifies the receiving application."},
      {seq:6,name:"Receiving Facility",dt:"HD",opt:"O",rep:"N",desc:"Further identifies the receiving application."},
      {seq:7,name:"Date/Time of Message",dt:"DTM",opt:"R",rep:"N",desc:"Date and time the message was created (YYYYMMDDHHMMSS)."},
      {seq:8,name:"Security",dt:"ST",opt:"O",rep:"N",desc:"In some applications of HL7, this field is used to implement security features."},
      {seq:9,name:"Message Type",dt:"MSG",opt:"R",rep:"N",desc:"Message code and event that define the intent of the message. E.g. ORM^O01, ADT^A04."},
      {seq:10,name:"Message Control ID",dt:"ST",opt:"R",rep:"N",desc:"A number or other identifier that uniquely identifies the message. Used to reference a specific message."},
      {seq:11,name:"Processing ID",dt:"PT",opt:"R",rep:"N",desc:"P=Production, T=Training, D=Debugging."},
      {seq:12,name:"Version ID",dt:"VID",opt:"R",rep:"N",desc:"HL7 version. E.g. 2.4, 2.5, 2.7."},
      {seq:13,name:"Sequence Number",dt:"NM",opt:"O",rep:"N",desc:"Non-null value only if the application sends messages in a continuous stream."},
      {seq:14,name:"Continuation Pointer",dt:"ST",opt:"O",rep:"N",desc:"Used to define continuations in interactive queries."},
      {seq:15,name:"Accept Acknowledgment Type",dt:"ID",opt:"O",rep:"N",desc:"AL=Always, NE=Never, ER=Error/reject, SU=Successful."},
      {seq:16,name:"Application Acknowledgment Type",dt:"ID",opt:"O",rep:"N",desc:"AL=Always, NE=Never, ER=Error/reject, SU=Successful."},
      {seq:17,name:"Country Code",dt:"ID",opt:"O",rep:"N",desc:"Defines the country of origin for the message (ISO 3166)."},
      {seq:18,name:"Character Set",dt:"ID",opt:"O",rep:"Y",desc:"The character set for the entire message. Defaults to ASCII."},
      {seq:19,name:"Principal Language of Message",dt:"CWE",opt:"O",rep:"N",desc:"The primary language used for messaging."},
    ]
  },
  PID: { name:"Patient Identification", desc:"Used to convey basic demographic information about a patient.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"O",rep:"N",desc:"For the first PID segment, the sequence number shall be 1."},
      {seq:2,name:"Patient ID (External)",dt:"CX",opt:"B",rep:"N",desc:"Retained for backward compatibility only."},
      {seq:3,name:"Patient Identifier List",dt:"CX",opt:"R",rep:"Y",desc:"Primary patient identifier(s) used by the facility. MRN, etc."},
      {seq:4,name:"Alternate Patient ID",dt:"CX",opt:"B",rep:"Y",desc:"Retained for backward compatibility."},
      {seq:5,name:"Patient Name",dt:"XPN",opt:"R",rep:"Y",desc:"Legal name of the patient. Format: LastName^FirstName^MiddleName."},
      {seq:6,name:"Mother's Maiden Name",dt:"XPN",opt:"O",rep:"Y",desc:"Mother's maiden name used as means of identifying the patient."},
      {seq:7,name:"Date/Time of Birth",dt:"DTM",opt:"O",rep:"N",desc:"Patient's date and time of birth. Format: YYYYMMDD."},
      {seq:8,name:"Administrative Sex",dt:"IS",opt:"O",rep:"N",desc:"Patient's sex. M=Male, F=Female, U=Unknown, O=Other."},
      {seq:9,name:"Patient Alias",dt:"XPN",opt:"B",rep:"Y",desc:"Retained for backward compatibility."},
      {seq:10,name:"Race",dt:"CWE",opt:"O",rep:"Y",desc:"The patient's race."},
      {seq:11,name:"Patient Address",dt:"XAD",opt:"O",rep:"Y",desc:"Mailing address of the patient."},
      {seq:12,name:"County Code",dt:"IS",opt:"B",rep:"N",desc:"Retained for backward compatibility."},
      {seq:13,name:"Phone Number – Home",dt:"XTN",opt:"O",rep:"Y",desc:"Patient's home phone number."},
      {seq:14,name:"Phone Number – Business",dt:"XTN",opt:"O",rep:"Y",desc:"Patient's business phone number."},
      {seq:15,name:"Primary Language",dt:"CWE",opt:"O",rep:"N",desc:"Patient's primary language."},
      {seq:16,name:"Marital Status",dt:"CWE",opt:"O",rep:"N",desc:"Patient's marital status."},
      {seq:17,name:"Religion",dt:"CWE",opt:"O",rep:"N",desc:"Patient's religion."},
      {seq:18,name:"Patient Account Number",dt:"CX",opt:"O",rep:"N",desc:"Patient account number assigned by accounting."},
      {seq:19,name:"SSN Number – Patient",dt:"ST",opt:"B",rep:"N",desc:"Retained for backward compatibility."},
    ]
  },
  PV1: { name:"Patient Visit", desc:"Used to communicate information on a visit-specific basis.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"O",rep:"N",desc:"Sequence number for the segment."},
      {seq:2,name:"Patient Class",dt:"IS",opt:"R",rep:"N",desc:"I=Inpatient, O=Outpatient, E=Emergency, P=Preadmit, R=Recurring, B=Obstetrics."},
      {seq:3,name:"Assigned Patient Location",dt:"PL",opt:"O",rep:"N",desc:"Location of the patient at the time that the transaction was sent."},
      {seq:4,name:"Admission Type",dt:"IS",opt:"O",rep:"N",desc:"Indicates the circumstances under which the patient was or will be admitted."},
      {seq:5,name:"Preadmit Number",dt:"CX",opt:"O",rep:"N",desc:"Uniquely identifies the patient's pre-admit account."},
      {seq:6,name:"Prior Patient Location",dt:"PL",opt:"O",rep:"N",desc:"Patient's prior patient location if the patient is being transferred."},
      {seq:7,name:"Attending Doctor",dt:"XCN",opt:"O",rep:"Y",desc:"Clinician responsible for the patient's care."},
      {seq:8,name:"Referring Doctor",dt:"XCN",opt:"O",rep:"Y",desc:"Clinician that referred the patient."},
      {seq:9,name:"Consulting Doctor",dt:"XCN",opt:"B",rep:"Y",desc:"Retained for backward compatibility."},
      {seq:10,name:"Hospital Service",dt:"IS",opt:"O",rep:"N",desc:"Service to which the patient belongs."},
      {seq:17,name:"Admitting Doctor",dt:"XCN",opt:"O",rep:"Y",desc:"Attending doctor responsible for admitting the patient."},
      {seq:18,name:"Patient Type",dt:"IS",opt:"O",rep:"N",desc:"Site-defined codes for the patient's type."},
      {seq:19,name:"Visit Number",dt:"CX",opt:"O",rep:"N",desc:"Unique number assigned to each patient visit."},
      {seq:44,name:"Admit Date/Time",dt:"DTM",opt:"O",rep:"N",desc:"Date/time the patient was admitted."},
      {seq:45,name:"Discharge Date/Time",dt:"DTM",opt:"O",rep:"N",desc:"Date/time the patient was discharged."},
    ]
  },
  ORC: { name:"Common Order", desc:"Transmits fields common to all orders (pharmacy, dietary, nursing, radiology, etc.).",
    fields:[
      {seq:1,name:"Order Control",dt:"ID",opt:"R",rep:"N",desc:"Determines the function of the order segment. NW=New order, CA=Cancel, OK=Order accepted, CM=Order completed."},
      {seq:2,name:"Placer Order Number",dt:"EI",opt:"C",rep:"N",desc:"Placer application's order number. Required if not ORC-3."},
      {seq:3,name:"Filler Order Number",dt:"EI",opt:"C",rep:"N",desc:"Filler application's order number. Required if not ORC-2."},
      {seq:4,name:"Placer Group Number",dt:"EI",opt:"O",rep:"N",desc:"Allows an order-placing application to group sets of orders together."},
      {seq:5,name:"Order Status",dt:"ID",opt:"O",rep:"N",desc:"Status of the order. IP=In process, CM=Complete, CA=Cancelled, DC=Discontinued."},
      {seq:9,name:"Date/Time of Transaction",dt:"DTM",opt:"O",rep:"N",desc:"Date and time of the event that initiated the current transaction."},
      {seq:12,name:"Ordering Provider",dt:"XCN",opt:"O",rep:"Y",desc:"Clinician who placed the order."},
      {seq:13,name:"Enterer's Location",dt:"PL",opt:"O",rep:"N",desc:"Point of care, room, bed, facility where the order was entered."},
    ]
  },
  OBR: { name:"Observation Request", desc:"Used to transmit information about an exam, diagnostic study, or assessment.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"O",rep:"N",desc:"Sequence number for the segment."},
      {seq:2,name:"Placer Order Number",dt:"EI",opt:"C",rep:"N",desc:"The order number associated with the filling application."},
      {seq:3,name:"Filler Order Number",dt:"EI",opt:"C",rep:"N",desc:"The order number associated with the filler application."},
      {seq:4,name:"Universal Service Identifier",dt:"CWE",opt:"R",rep:"N",desc:"Identifies the observation requested (procedure code + description)."},
      {seq:7,name:"Observation Date/Time",dt:"DTM",opt:"O",rep:"N",desc:"Date/time that the observation/specimen collection was clinically relevant."},
      {seq:16,name:"Ordering Provider",dt:"XCN",opt:"O",rep:"Y",desc:"Clinician who ordered the observation."},
      {seq:22,name:"Results Rpt/Status Chng Date/Time",dt:"DTM",opt:"C",rep:"N",desc:"Date/time results reported or status changed."},
      {seq:24,name:"Diagnostic Service Section ID",dt:"ID",opt:"O",rep:"N",desc:"Section of the diagnostic service where the observation was performed. RAD, NMR, CT, etc."},
      {seq:25,name:"Result Status",dt:"ID",opt:"C",rep:"N",desc:"Status of results. F=Final, P=Preliminary, C=Corrected, R=Results entered, I=No results available."},
    ]
  },
  OBX: { name:"Observation/Result", desc:"Used to transmit a single observation or observation fragment.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"O",rep:"N",desc:"Sequence number for the segment when repeated."},
      {seq:2,name:"Value Type",dt:"ID",opt:"C",rep:"N",desc:"Data type of OBX-5. NM=Numeric, ST=String, TX=Text, CWE=Coded, DT=Date, TS=Timestamp, ED=Encapsulated data."},
      {seq:3,name:"Observation Identifier",dt:"CWE",opt:"R",rep:"N",desc:"Unique identifier for the observation."},
      {seq:4,name:"Observation Sub-ID",dt:"ST",opt:"O",rep:"N",desc:"Distinguishes between multiple OBX segments with the same observation identifier."},
      {seq:5,name:"Observation Value",dt:"*",opt:"C",rep:"Y",desc:"The actual value of the observation."},
      {seq:6,name:"Units",dt:"CWE",opt:"O",rep:"N",desc:"Units of the observation value."},
      {seq:7,name:"References Range",dt:"ST",opt:"O",rep:"N",desc:"Normal range for the observation."},
      {seq:11,name:"Observation Result Status",dt:"ID",opt:"R",rep:"N",desc:"F=Final, P=Preliminary, C=Corrected, D=Deleted, U=Result status change to final without retransmit."},
      {seq:14,name:"Date/Time of the Observation",dt:"DTM",opt:"O",rep:"N",desc:"Date and time of the observation."},
    ]
  },
  EVN: { name:"Event Type", desc:"Used to communicate necessary trigger event information to receiving applications.",
    fields:[
      {seq:1,name:"Event Type Code",dt:"ID",opt:"B",rep:"N",desc:"Retained for backward compatibility. The trigger event is now the second field of MSH-9."},
      {seq:2,name:"Recorded Date/Time",dt:"DTM",opt:"R",rep:"N",desc:"Date/time the event was recorded."},
      {seq:3,name:"Date/Time Planned Event",dt:"DTM",opt:"O",rep:"N",desc:"Date/time the event is planned to occur."},
      {seq:4,name:"Event Reason Code",dt:"IS",opt:"O",rep:"N",desc:"Indicates the reason for the event. Used for ADT events."},
      {seq:5,name:"Operator ID",dt:"XCN",opt:"O",rep:"Y",desc:"Identifies the individual responsible for triggering the event."},
      {seq:6,name:"Event Occurred",dt:"DTM",opt:"O",rep:"N",desc:"Date/time that the event actually occurred."},
    ]
  },
  NK1: { name:"Next of Kin / Associated Parties", desc:"Contains information about the patient's next of kin or associated parties.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"R",rep:"N",desc:"Sequence number."},
      {seq:2,name:"Name",dt:"XPN",opt:"O",rep:"Y",desc:"Name of the next of kin / associated parties."},
      {seq:3,name:"Relationship",dt:"CWE",opt:"O",rep:"N",desc:"Relationship of the next of kin to the patient. SPO=Spouse, PAR=Parent, CHD=Child, SIB=Sibling."},
      {seq:4,name:"Address",dt:"XAD",opt:"O",rep:"Y",desc:"Address of the associated party."},
      {seq:5,name:"Phone Number",dt:"XTN",opt:"O",rep:"Y",desc:"Phone number of the associated party."},
      {seq:7,name:"Contact Role",dt:"CWE",opt:"O",rep:"N",desc:"Identifies the specific relationship role. EC=Emergency contact, E=Employer, C=State Agency."},
    ]
  },
  SCH: { name:"Scheduling Activity Information", desc:"Contains information about the schedule activity being requested.",
    fields:[
      {seq:1,name:"Placer Appointment ID",dt:"EI",opt:"C",rep:"N",desc:"Placer application's permanent identifier for the requested appointment."},
      {seq:2,name:"Filler Appointment ID",dt:"EI",opt:"C",rep:"N",desc:"Filler application's permanent identifier for the requested appointment."},
      {seq:5,name:"Schedule ID",dt:"CWE",opt:"O",rep:"N",desc:"Contains the ID of the schedule which the appointment request is associated with."},
      {seq:7,name:"Appointment Reason",dt:"CWE",opt:"O",rep:"N",desc:"Describes the reason for the appointment."},
      {seq:8,name:"Appointment Type",dt:"CWE",opt:"O",rep:"N",desc:"Describes the type of appointment."},
      {seq:9,name:"Appointment Duration",dt:"NM",opt:"O",rep:"N",desc:"Contains the amount of time being requested for the appointment."},
      {seq:11,name:"Appointment Timing Quantity",dt:"TQ",opt:"B",rep:"Y",desc:"The start date/time and length of the requested appointment."},
      {seq:16,name:"Filler Contact Person",dt:"XCN",opt:"O",rep:"Y",desc:"Contact person at the filler's site."},
      {seq:25,name:"Filler Status Code",dt:"CWE",opt:"O",rep:"N",desc:"Status of the appointment."},
    ]
  },
  AL1: { name:"Patient Allergy Information", desc:"Transmit patient allergy information.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"R",rep:"N",desc:"Sequence number."},
      {seq:2,name:"Allergy Type",dt:"CWE",opt:"O",rep:"N",desc:"DA=Drug allergy, FA=Food allergy, MA=Miscellaneous allergy, MC=Miscellaneous contraindication."},
      {seq:3,name:"Allergy Code/Mnemonic/Description",dt:"CWE",opt:"R",rep:"N",desc:"Uniquely identifies the allergy."},
      {seq:4,name:"Allergy Severity Code",dt:"CWE",opt:"O",rep:"N",desc:"SV=Severe, MO=Moderate, MI=Mild, U=Unknown."},
      {seq:5,name:"Allergy Reaction Code",dt:"ST",opt:"O",rep:"Y",desc:"Short text name of the reaction to the allergy."},
    ]
  },
  DG1: { name:"Diagnosis", desc:"Transmit patient diagnosis information.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"R",rep:"N",desc:"Sequence number."},
      {seq:2,name:"Diagnosis Coding Method",dt:"ID",opt:"B",rep:"N",desc:"Retained for backward compatibility."},
      {seq:3,name:"Diagnosis Code",dt:"CWE",opt:"O",rep:"N",desc:"Actual code and/or text assigned by the provider to describe the diagnosis."},
      {seq:4,name:"Diagnosis Description",dt:"ST",opt:"B",rep:"N",desc:"Retained for backward compatibility."},
      {seq:5,name:"Diagnosis Date/Time",dt:"DTM",opt:"O",rep:"N",desc:"Date/time the diagnosis was made."},
      {seq:6,name:"Diagnosis Type",dt:"IS",opt:"R",rep:"N",desc:"A=Admitting, W=Working, F=Final."},
    ]
  },
  IN1: { name:"Insurance", desc:"Contains insurance policy coverage information.",
    fields:[
      {seq:1,name:"Set ID",dt:"SI",opt:"R",rep:"N",desc:"Sequence number."},
      {seq:2,name:"Health Plan ID",dt:"CWE",opt:"R",rep:"N",desc:"Unique identifier for the health plan."},
      {seq:3,name:"Insurance Company ID",dt:"CX",opt:"R",rep:"Y",desc:"Uniquely identifies the insurance company."},
      {seq:4,name:"Insurance Company Name",dt:"XON",opt:"O",rep:"Y",desc:"Name of the insurance company."},
      {seq:5,name:"Insurance Company Address",dt:"XAD",opt:"O",rep:"Y",desc:"Address of the insurance company."},
      {seq:15,name:"Plan Type",dt:"IS",opt:"O",rep:"N",desc:"Uniquely identifies the type of health plan. E.g. MA=Medicare, MC=Medicaid, CH=Champus."},
      {seq:16,name:"Name of Insured",dt:"XPN",opt:"O",rep:"Y",desc:"Name of the insured person."},
      {seq:18,name:"Insured's Date of Birth",dt:"DTM",opt:"O",rep:"N",desc:"Date of birth of the insured."},
    ]
  },
  MSA: { name:"Message Acknowledgment", desc:"Contains information sent while acknowledging another message.",
    fields:[
      {seq:1,name:"Acknowledgment Code",dt:"ID",opt:"R",rep:"N",desc:"AA=Application Accept, AE=Application Error, AR=Application Reject, CA=Commit Accept, CE=Commit Error, CR=Commit Reject."},
      {seq:2,name:"Message Control ID",dt:"ST",opt:"R",rep:"N",desc:"The message control ID of the message being acknowledged (MSH-10 of the original message)."},
      {seq:3,name:"Text Message",dt:"ST",opt:"O",rep:"N",desc:"Optional text description of an error condition."},
      {seq:4,name:"Expected Sequence Number",dt:"NM",opt:"O",rep:"N",desc:"The number the sending application expected."},
      {seq:6,name:"Error Condition",dt:"CWE",opt:"B",rep:"N",desc:"Retained for backward compatibility."},
    ]
  },
  ERR: { name:"Error", desc:"Additional error information in an ACK message.",
    fields:[
      {seq:1,name:"Error Code and Location",dt:"ELD",opt:"B",rep:"Y",desc:"Retained for backward compatibility."},
      {seq:3,name:"HL7 Error Code",dt:"CWE",opt:"R",rep:"N",desc:"Identifies the HL7 error code."},
      {seq:4,name:"Severity",dt:"ID",opt:"R",rep:"N",desc:"W=Warning, I=Information, E=Error."},
      {seq:5,name:"Application Error Code",dt:"CWE",opt:"O",rep:"N",desc:"Application-specific error code."},
      {seq:8,name:"User Message",dt:"TX",opt:"O",rep:"N",desc:"Free-text error description for display."},
    ]
  },
  ZDS: { name:"ZDS (Study Instance UID)", desc:"Local extension segment carrying the DICOM Study Instance UID.",
    fields:[
      {seq:1,name:"Study Instance UID",dt:"ST",opt:"O",rep:"N",desc:"DICOM Study Instance UID linked to this order."},
    ]
  },
};

/** Parse a raw HL7 message string into segments + fields. */
function _hl7Parse(raw) {
  const lines = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n")
    .map(l => l.trim()).filter(l => l.length > 0);
  return lines.map(line => {
    const sep   = line.startsWith("MSH") ? line[3] : (line.indexOf("|") > -1 ? "|" : null);
    if (!sep) return { seg: line, fields: [] };
    const parts  = line.split(sep);
    const segId  = parts[0];
    // For MSH the separator itself is field 1
    const fields = segId === "MSH" ? [sep, ...parts.slice(2)] : parts.slice(1);
    return { seg: segId, fields };
  });
}

/**
 * Show HL7 inspector for a given textarea element ID, or for a raw text string.
 *
 * @param {string|null} textareaId  - ID of the source textarea, or null when rawText is provided.
 * @param {string}      [rawText]   - Raw HL7 message text (used by received-message blocks).
 */
function hl7ParseAndInspect(textareaId, rawText) {
  const isPrimary = textareaId === "hl7-message" && rawText == null;
  const raw = rawText != null ? rawText : (document.getElementById(textareaId)?.value || "");
  if (!raw.trim()) { toast(i18n("hl7.no_message"), "warn"); return; }

  const tbodyId   = isPrimary ? "hl7-parsed-tbody"      : "hl7-recv-parsed-tbody";
  const cardId    = isPrimary ? "hl7-inspector-card"     : "hl7-recv-inspector";
  const infoId    = isPrimary ? "hl7-field-info"         : "hl7-recv-field-info";
  const infoConId = isPrimary ? "hl7-field-info-content" : "hl7-recv-field-info-content";

  const segments  = _hl7Parse(raw);
  const tbody     = document.getElementById(tbodyId);
  tbody.innerHTML = "";

  segments.forEach(({ seg, fields }) => {
    const def     = _HL7_SEGMENTS[seg];
    const segName = def ? def.name : "Unknown segment";
    const tr      = document.createElement("tr");
    tr.style.cssText = "vertical-align:top; border-bottom:1px solid #e2e8f0";

    // Segment cell
    const tdSeg = document.createElement("td");
    tdSeg.style.cssText = "padding:3px 6px; font-weight:700; white-space:nowrap; cursor:pointer; color:#2b6cb0";
    tdSeg.textContent   = seg;
    tdSeg.title         = segName;
    tdSeg.onclick       = () => _hl7ShowSegInfo(seg, infoId, infoConId);
    tr.appendChild(tdSeg);

    // Fields cell — each field is a clickable chip
    const tdFields = document.createElement("td");
    tdFields.style.cssText = "padding:3px 4px; word-break:break-all; line-height:1.8";
    fields.forEach((val, idx) => {
      const fieldNum = seg === "MSH" ? idx + 1 : idx + 1;
      const fdDef    = def?.fields.find(f => f.seq === fieldNum);
      const chip     = document.createElement("span");
      chip.style.cssText =
        "display:inline-block; margin:1px 2px; padding:1px 5px; border-radius:3px; " +
        "border:1px solid #cbd5e0; background:#f7fafc; font-size:11px; cursor:pointer; " +
        "max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:middle";
      chip.title     = fdDef ? `${fdDef.name} (${fdDef.dt})` : `Field ${fieldNum}`;
      chip.textContent = val || (fdDef ? "—" : "");
      if (val) chip.style.background = "#ebf8ff";
      chip.onclick   = () => _hl7ShowFieldInfo(seg, fieldNum, val, infoId, infoConId);
      tdFields.appendChild(chip);
    });
    tr.appendChild(tdFields);
    tbody.appendChild(tr);
  });

  document.getElementById(cardId).style.display = "";
  document.getElementById(infoId).style.display  = "none";
}

function _hl7ShowSegInfo(seg, infoId, infoConId) {
  const def = _HL7_SEGMENTS[seg];
  const el  = document.getElementById(infoConId);
  if (!def) {
    el.innerHTML = `<b>${escapeHtml(seg)}</b><br><span style="color:#888">No definition available.</span>`;
  } else {
    el.innerHTML =
      `<div style="font-weight:700; color:#2b6cb0; margin-bottom:4px">${escapeHtml(seg)} — ${escapeHtml(def.name)}</div>` +
      `<div style="color:#555; margin-bottom:8px; font-size:11px">${escapeHtml(def.desc)}</div>` +
      `<table style="width:100%; border-collapse:collapse; font-size:11px">` +
      `<tr style="background:#f0f4f8"><th style="padding:2px 4px;text-align:left">#</th>` +
      `<th style="padding:2px 4px;text-align:left">Field</th>` +
      `<th style="padding:2px 4px;text-align:left">Type</th>` +
      `<th style="padding:2px 4px;text-align:left">Opt</th></tr>` +
      (def.fields || []).map(f =>
        `<tr style="border-bottom:1px solid #e2e8f0">` +
        `<td style="padding:2px 4px;color:#888">${f.seq}</td>` +
        `<td style="padding:2px 4px">${escapeHtml(f.name)}</td>` +
        `<td style="padding:2px 4px;font-family:Consolas;color:#6b7280">${f.dt}</td>` +
        `<td style="padding:2px 4px;color:${f.opt==='R'?'#dc2626':'#6b7280'}">${f.opt}</td>` +
        `</tr>`
      ).join("") + `</table>`;
  }
  document.getElementById(infoId).style.display = "";
}

function _hl7ShowFieldInfo(seg, fieldNum, value, infoId, infoConId) {
  const def   = _HL7_SEGMENTS[seg];
  const fdDef = def?.fields.find(f => f.seq === fieldNum);
  const el    = document.getElementById(infoConId);
  const OPT   = { R:"Required", O:"Optional", C:"Conditional", B:"Backward compat." };
  const REP   = { Y:"Repeatable", N:"Non-repeatable" };
  el.innerHTML =
    `<div style="font-weight:700; color:#2b6cb0; margin-bottom:4px">${escapeHtml(seg)}-${fieldNum}` +
    (fdDef ? ` — ${escapeHtml(fdDef.name)}` : "") + `</div>` +
    (fdDef ? `<table style="width:100%; border-collapse:collapse; font-size:11px; margin-bottom:8px">` +
      `<tr><td style="color:#888;padding:2px 0;width:80px">Data type</td><td style="font-family:Consolas">${fdDef.dt}</td></tr>` +
      `<tr><td style="color:#888;padding:2px 0">Optionality</td><td>${OPT[fdDef.opt]||fdDef.opt}</td></tr>` +
      `<tr><td style="color:#888;padding:2px 0">Repeatable</td><td>${REP[fdDef.rep]||fdDef.rep}</td></tr>` +
      `</table>` +
      `<div style="color:#555; margin-bottom:8px; font-size:11px">${escapeHtml(fdDef.desc)}</div>` : "") +
    (value ? `<div style="background:#ebf8ff; border:1px solid #bee3f8; border-radius:3px; padding:4px 6px; font-family:Consolas; font-size:11px; word-break:break-all">${escapeHtml(value)}</div>` : "");
  document.getElementById(infoId).style.display = "";
}

async function doHL7Send() {
  const host    = document.getElementById("hl7-host").value.trim();
  const portStr = document.getElementById("hl7-port").value.trim();
  const port    = parsePort(portStr);
  if (port === null) { toast(i18n("common.invalid_port", {port: portStr}), "err"); return; }
  const msg  = document.getElementById("hl7-message").value.trim();
  if (!msg) { toast(i18n("hl7.no_message"), "warn"); return; }
  appendLog("log-hl7-send", now(), `Sending to ${host}:${port}`);

  const res  = await fetch("/api/hl7/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      host,
      port: parseInt(port),
      message: msg,
      debug: document.getElementById("hl7-send-debug").checked,
    }),
  });
  const data = await res.json();
  appendLog("log-hl7-send", now(),
    data.ok ? `ACK: ${data.response.substring(0,200)}` : `FAILED: ${data.response}`,
    data.ok ? "ok" : "err");

  // Persist to outbound history
  _hl7OutHistorySave({
    ts:       new Date().toISOString(),
    host,
    port,
    message:  msg,
    ok:       data.ok,
    response: data.response || "",
  });
}

// ─────────────────────────────────────────────────────────────────
// HL7 Message History (localStorage)
// ─────────────────────────────────────────────────────────────────

const HL7_HIST_OUT_KEY = "pacsadmin_hl7_hist_out";
const HL7_HIST_IN_KEY  = "pacsadmin_hl7_hist_in";
const HL7_HIST_MAX     = 10;

function _hl7HistLoad(key) {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); }
  catch { return []; }
}

function _hl7HistSave(key, entry) {
  const arr = _hl7HistLoad(key);
  arr.unshift(entry);
  try { localStorage.setItem(key, JSON.stringify(arr.slice(0, HL7_HIST_MAX))); }
  catch { /* storage full */ }
}

function _hl7OutHistorySave(entry) {
  _hl7HistSave(HL7_HIST_OUT_KEY, entry);
  renderHL7OutHistory();
}

// Inbound history is persisted server-side (survives restarts); the server
// appends each message before emitting the socket event, so a refresh from
// /api/hl7/history is all that's needed here.
function _hl7InHistorySave(_entry) {
  renderHL7InHistory();
}

function _hl7HistItemEl(item, dir) {
  const el  = document.createElement("div");
  el.style.cssText = "border:1px solid #e5e7eb; border-radius:6px; overflow:hidden; background:#fff";
  const ts  = item.ts ? new Date(item.ts).toLocaleString() : "";
  const who = dir === "out"
    ? `To ${item.host}:${item.port}`
    : `From ${item.from || "?"}`;
  const ok  = dir === "out" ? item.ok : true;
  const preview = (item.message || "").substring(0, 120).replace(/\r/g, " ");
  const detailId = "hl7h-" + Math.random().toString(36).slice(2);

  el.innerHTML =
    `<div style="display:flex;justify-content:space-between;align-items:center;
                 padding:6px 10px; background:${ok ? '#f0fdf4' : '#fef2f2'};
                 border-bottom:1px solid #e5e7eb; cursor:pointer"
         onclick="document.getElementById('${detailId}').style.display =
                  document.getElementById('${detailId}').style.display==='none'?'':'none'">
       <div style="font-size:11px;color:#6b7280">${ts} · <strong>${who}</strong>
         <span style="margin-left:6px;color:${ok?'#16a34a':'#dc2626'}">${ok?'OK':'FAILED'}</span>
       </div>
       <span style="font-size:10px;color:#9ca3af">▼</span>
     </div>
     <div style="font-size:11px;color:#555;padding:4px 10px;
                 white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
          title="${escapeHtml(preview)}">${escapeHtml(preview)}</div>
     <div id="${detailId}" style="display:none;padding:8px 10px">
       <pre style="font-size:11px;white-space:pre-wrap;color:#374151;max-height:200px;overflow-y:auto;margin:0">${escapeHtml(item.message || "")}</pre>
       ${dir === 'out' && item.response
         ? `<div style="font-size:11px;color:#6b7280;margin-top:6px">ACK: ${escapeHtml(item.response.substring(0,300))}</div>`
         : ""}
     </div>`;
  return el;
}

function renderHL7OutHistory() {
  const arr  = _hl7HistLoad(HL7_HIST_OUT_KEY);
  const card = document.getElementById("hl7-out-history-card");
  const list = document.getElementById("hl7-out-history-list");
  if (!arr.length) { card.style.display = "none"; return; }
  card.style.display = "";
  list.innerHTML = "";
  arr.forEach(item => list.appendChild(_hl7HistItemEl(item, "out")));
}

async function renderHL7InHistory() {
  const card = document.getElementById("hl7-in-history-card");
  const list = document.getElementById("hl7-in-history-list");
  let arr = [];
  try {
    const res  = await fetch("/api/hl7/history");
    const data = await res.json();
    arr = (data.messages || []).map(m => ({
      ts: m.ts, from: m.from,
      message: (m.message || "").replace(/\r/g, "\n"),
    }));
  } catch { /* server unreachable — leave list empty */ }
  if (!arr.length) { card.style.display = "none"; return; }
  card.style.display = "";
  list.innerHTML = "";
  arr.forEach(item => list.appendChild(_hl7HistItemEl(item, "in")));
}

function clearHL7OutHistory() {
  localStorage.removeItem(HL7_HIST_OUT_KEY);
  renderHL7OutHistory();
}

async function clearHL7InHistory() {
  localStorage.removeItem(HL7_HIST_IN_KEY);  // clean up pre-server-history data
  await fetch("/api/hl7/history/clear", { method: "POST" }).catch(() => {});
  renderHL7InHistory();
}

// ─────────────────────────────────────────────────────────────────
// 12. HL7 Listener
// ─────────────────────────────────────────────────────────────────

let hl7ListenerRunning = false;

async function toggleHL7Listener() {
  if (hl7ListenerRunning) {
    await fetch("/api/hl7/listener/stop", { method: "POST" });
    hl7ListenerRunning = false;
  } else {
    const portStr = document.getElementById("hl7-listen-port").value;
    const port = parsePort(portStr);
    if (port === null) { toast(i18n("common.invalid_port", {port: portStr}), "err"); return; }
    const res  = await fetch("/api/hl7/listener/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        port: port,
        debug: document.getElementById("hl7-recv-debug").checked,
        ack_code: document.getElementById("hl7-ack-mode").value,
      }),
    });
    const data = await res.json();
    hl7ListenerRunning = data.ok;
    appendLog("log-hl7-recv", now(), data.message, data.ok ? "ok" : "err");
  }
  updateHL7Button(hl7ListenerRunning);
}

function updateHL7Button(running) {
  hl7ListenerRunning = running;
  const btn   = document.getElementById("hl7-listen-btn");
  const badge = document.getElementById("hl7-listen-badge");
  if (running) {
    btn.textContent = i18n("hl7.stop_hl7_web");
    btn.className   = "btn danger";
    badge.textContent = i18n("common.running");
    badge.className   = "badge running";
  } else {
    btn.textContent = i18n("hl7.start_hl7_web");
    btn.className   = "btn primary";
    badge.textContent = i18n("common.stopped");
    badge.className   = "badge stopped";
  }
}

function clearHL7Received() {
  document.getElementById("hl7-recv-messages").innerHTML = "";
  document.getElementById("hl7-recv-count").textContent = "0 messages";
}

