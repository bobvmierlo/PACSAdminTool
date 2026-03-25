"""
DICOM Structured Report (SR) reader.

Parses any SR SOP Class and returns a human-readable hierarchical structure.
Supports all common SR types:
  - Basic Text SR, Enhanced SR, Comprehensive SR, Comprehensive 3D SR
  - X-Ray Radiation Dose SR, Mammography CAD SR, Chest CAD SR, Colon CAD SR
  - Simplified Adult Echo SR, Patient Radiation Dose SR, and others
"""

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _code_meaning(code_seq):
    """Return a readable label from a CodeSequence dataset or list."""
    if not code_seq:
        return ""
    try:
        item = code_seq[0] if hasattr(code_seq, "__len__") else code_seq
        meaning  = str(getattr(item, "CodeMeaning", ""))
        code_val = str(getattr(item, "CodeValue", ""))
        scheme   = str(getattr(item, "CodingSchemeDesignator", ""))
        if meaning and code_val:
            return f"{meaning} ({scheme}:{code_val})"
        return meaning or code_val
    except Exception:
        return str(code_seq)


def _measurement_str(meas_seq):
    """Format a numeric measurement with units from MeasuredValueSequence."""
    if not meas_seq:
        return ""
    try:
        item     = meas_seq[0]
        value    = getattr(item, "NumericValue", None)
        if value is None:
            value = getattr(item, "FloatingPointValue", None)
        value_str = str(value) if value is not None else "?"
        units_seq = getattr(item, "MeasurementUnitsCodeSequence", [])
        if units_seq:
            u = units_seq[0]
            unit_code    = str(getattr(u, "CodeValue", ""))
            unit_meaning = str(getattr(u, "CodeMeaning", unit_code))
            # Map common unit codes to pretty labels
            _UNIT_LABELS = {
                "mm": "mm", "cm": "cm", "m": "m",
                "mm2": "mm²", "cm2": "cm²",
                "mm3": "mm³", "cm3": "cm³",
                "HU": "HU", "mg/mL": "mg/mL",
                "mGy": "mGy", "Gy": "Gy", "mGy.cm2": "mGy·cm²",
                "mSv": "mSv", "uSv": "μSv",
                "%": "%", "dB": "dB",
                "ms": "ms", "s": "s",
                "bpm": "bpm", "/min": "/min",
                "keV": "keV", "kV": "kV", "mA": "mA",
                "{ratio}": "", "1": "",
            }
            label = _UNIT_LABELS.get(unit_code, unit_meaning or unit_code)
            return f"{value_str} {label}".strip()
        return value_str
    except Exception:
        return str(meas_seq)


def _image_ref_str(ref_seq):
    """Format a list of referenced SOP instances."""
    if not ref_seq:
        return ""
    parts = []
    for ref in ref_seq:
        sop_inst  = str(getattr(ref, "ReferencedSOPInstanceUID", ""))
        frame_no  = str(getattr(ref, "ReferencedFrameNumber", ""))
        seg_no    = str(getattr(ref, "ReferencedSegmentNumber", ""))
        entry = sop_inst
        if frame_no:
            entry += f"  frame={frame_no}"
        if seg_no:
            entry += f"  segment={seg_no}"
        parts.append(entry)
    return ";  ".join(parts)


# ---------------------------------------------------------------------------
# Content-item parser
# ---------------------------------------------------------------------------

def _parse_content_item(item, depth=0):
    """
    Parse one SR content item (a pydicom Dataset node in the SR tree).

    Returns a dict with keys:
        depth        int   – indentation level
        type         str   – DICOM ValueType (TEXT, CODE, NUM, CONTAINER, …)
        relationship str   – RelationshipType (CONTAINS, HAS OBS CONTEXT, …)
        concept      str   – human-readable concept name
        value        str   – human-readable value
        children     list  – parsed child nodes
    """
    node = {
        "depth":        depth,
        "type":         str(getattr(item, "ValueType", "")),
        "relationship": str(getattr(item, "RelationshipType", "")),
        "concept":      "",
        "value":        "",
        "children":     [],
    }

    concept_seq = getattr(item, "ConceptNameCodeSequence", None)
    if concept_seq:
        node["concept"] = _code_meaning(concept_seq)

    vtype = node["type"]

    try:
        if vtype == "TEXT":
            node["value"] = str(getattr(item, "TextValue", ""))

        elif vtype == "CODE":
            node["value"] = _code_meaning(getattr(item, "ConceptCodeSequence", None))

        elif vtype == "NUM":
            node["value"] = _measurement_str(getattr(item, "MeasuredValueSequence", None))
            if not node["value"]:
                nv = getattr(item, "NumericValue", None)
                if nv is not None:
                    node["value"] = str(nv)

        elif vtype == "UIDREF":
            node["value"] = str(getattr(item, "UID", ""))

        elif vtype == "PNAME":
            pn = getattr(item, "PersonName", None)
            node["value"] = str(pn) if pn is not None else ""

        elif vtype == "DATE":
            node["value"] = str(getattr(item, "Date", ""))

        elif vtype == "TIME":
            node["value"] = str(getattr(item, "Time", ""))

        elif vtype == "DATETIME":
            node["value"] = str(getattr(item, "DateTime", ""))

        elif vtype == "IMAGE":
            node["value"] = _image_ref_str(getattr(item, "ReferencedSOPSequence", None))

        elif vtype in ("COMPOSITE", "WAVEFORM"):
            ref_seq = getattr(item, "ReferencedSOPSequence", None)
            if ref_seq:
                node["value"] = str(getattr(ref_seq[0], "ReferencedSOPInstanceUID", ""))

        elif vtype == "SCOORD":
            gtype = str(getattr(item, "GraphicType", ""))
            gdata = list(getattr(item, "GraphicData", []))
            coord_str = str(gdata) if len(gdata) <= 10 else f"[{len(gdata)} values]"
            node["value"] = f"{gtype}: {coord_str}"

        elif vtype == "SCOORD3D":
            gtype = str(getattr(item, "GraphicType", ""))
            gdata = list(getattr(item, "GraphicData", []))
            if len(gdata) <= 12:
                coord_str = str([round(v, 3) if isinstance(v, float) else v for v in gdata])
            else:
                coord_str = f"[{len(gdata)} values]"
            ref_frame = str(getattr(item, "ReferencedFrameOfReferenceUID", ""))
            node["value"] = f"{gtype}: {coord_str}"
            if ref_frame:
                node["value"] += f"  (frame ref: {ref_frame})"

        elif vtype == "TCOORD":
            node["value"] = str(getattr(item, "TemporalRangeType", ""))

        elif vtype == "CONTAINER":
            continuity = str(getattr(item, "ContinuityOfContent", ""))
            node["value"] = continuity

    except Exception as e:
        node["value"] = f"<parse error: {e}>"

    # Recurse into nested content items
    content_seq = getattr(item, "ContentSequence", None)
    if content_seq:
        for child in content_seq:
            node["children"].append(_parse_content_item(child, depth + 1))

    return node


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# SOP class UID → friendly name
_SOP_NAMES = {
    "1.2.840.10008.5.1.4.1.1.88.11": "Basic Text SR",
    "1.2.840.10008.5.1.4.1.1.88.22": "Enhanced SR",
    "1.2.840.10008.5.1.4.1.1.88.33": "Comprehensive SR",
    "1.2.840.10008.5.1.4.1.1.88.34": "Comprehensive 3D SR",
    "1.2.840.10008.5.1.4.1.1.88.50": "Mammography CAD SR",
    "1.2.840.10008.5.1.4.1.1.88.59": "Key Object Selection",
    "1.2.840.10008.5.1.4.1.1.88.65": "Chest CAD SR",
    "1.2.840.10008.5.1.4.1.1.88.67": "X-Ray Radiation Dose SR",
    "1.2.840.10008.5.1.4.1.1.88.68": "Radiopharmaceutical Radiation Dose SR",
    "1.2.840.10008.5.1.4.1.1.88.69": "Colon CAD SR",
    "1.2.840.10008.5.1.4.1.1.88.70": "Implantation Plan SR",
    "1.2.840.10008.5.1.4.1.1.88.71": "Acquisition Context SR",
    "1.2.840.10008.5.1.4.1.1.88.72": "Simplified Adult Echo SR",
    "1.2.840.10008.5.1.4.1.1.88.73": "Patient Radiation Dose SR",
    "1.2.840.10008.5.1.4.1.1.88.74": "Planned Imaging Agent Administration SR",
    "1.2.840.10008.5.1.4.1.1.88.75": "Performed Imaging Agent Administration SR",
    "1.2.840.10008.5.1.4.1.1.88.76": "Enhanced X-Ray Radiation Dose SR",
}


def parse_sr(dataset) -> dict:
    """
    Parse a DICOM SR (or KOS) dataset into a structured dict.

    Returns::

        {
            'meta':   { PatientID, PatientName, StudyDate, … },
            'title':  str  (document title),
            'content': list[node]  (tree),
            'flat':    list[node]  (flattened, depth-annotated, for table display),
            'errors':  list[str],
        }
    """
    result = {"meta": {}, "title": "", "content": [], "flat": [], "errors": []}

    try:
        m = result["meta"]
        for attr in (
            "SOPClassUID", "SOPInstanceUID",
            "StudyInstanceUID", "SeriesInstanceUID",
            "PatientID", "PatientName",
            "StudyDate", "ContentDate", "ContentTime",
            "Modality", "Manufacturer", "InstitutionName",
            "AccessionNumber", "StudyDescription", "SeriesDescription",
            "InstanceNumber", "CompletionFlag", "VerificationFlag",
        ):
            m[attr] = str(getattr(dataset, attr, ""))

        # Friendly SOP class label
        m["SOPClassName"] = _SOP_NAMES.get(m["SOPClassUID"], m["SOPClassUID"])

        # Document title
        title_seq = getattr(dataset, "ConceptNameCodeSequence", None)
        if title_seq:
            result["title"] = _code_meaning(title_seq)

        # Parse content tree
        content_seq = getattr(dataset, "ContentSequence", None)
        if content_seq:
            for item in content_seq:
                result["content"].append(_parse_content_item(item, depth=0))

        result["flat"] = _flatten(result["content"])

    except Exception as e:
        result["errors"].append(str(e))
        logger.exception("SR parse error")

    return result


def _flatten(nodes, out=None):
    """Flatten a nested content tree into a plain list (preserving depth)."""
    if out is None:
        out = []
    for n in nodes:
        out.append({k: n[k] for k in ("depth", "type", "relationship", "concept", "value")})
        _flatten(n["children"], out)
    return out


def sr_to_text(parsed: dict) -> str:
    """Render a parsed SR dict as a human-readable plain-text report."""
    lines = []
    m     = parsed.get("meta", {})
    title = parsed.get("title", "")

    lines.append("=" * 72)
    lines.append("DICOM Structured Report")
    if title:
        lines.append(f"Document Title: {title}")
    sop_label = m.get("SOPClassName", m.get("SOPClassUID", ""))
    if sop_label:
        lines.append(f"SOP Class:      {sop_label}")
    lines.append("=" * 72)

    def _row(label, val):
        if val and val.strip():
            lines.append(f"{label:<16} {val}")

    _row("Patient:",      f"{m.get('PatientName','')}  [{m.get('PatientID','')}]")
    _row("Accession:",    m.get("AccessionNumber", ""))
    _row("Study Date:",   m.get("StudyDate", ""))
    _row("Content:",      f"{m.get('ContentDate','')} {m.get('ContentTime','')}".strip())
    _row("Study Desc:",   m.get("StudyDescription", ""))
    _row("Series Desc:",  m.get("SeriesDescription", ""))
    _row("Institution:",  m.get("InstitutionName", ""))
    _row("Manufacturer:", m.get("Manufacturer", ""))
    _row("Completion:",   m.get("CompletionFlag", ""))
    _row("Verification:", m.get("VerificationFlag", ""))

    for err in parsed.get("errors", []):
        lines.append(f"PARSE ERROR: {err}")

    flat = parsed.get("flat", [])
    if not flat:
        lines.append("")
        lines.append("(No content items found)")
        return "\n".join(lines)

    lines.append("")
    lines.append("─" * 72)
    lines.append("Content:")
    lines.append("")

    for item in flat:
        indent  = "  " * item["depth"]
        vtype   = item["type"]
        concept = item["concept"]
        value   = item["value"]

        if vtype == "CONTAINER":
            header = f"{indent}┌─ {concept}" if concept else f"{indent}┌─ [Container]"
            if value:
                header += f"  ({value})"
            lines.append(header)

        elif vtype == "TEXT":
            text_lines = value.splitlines()
            if len(text_lines) <= 1:
                lines.append(f"{indent}  {concept}: {value}")
            else:
                lines.append(f"{indent}  {concept}:")
                for tl in text_lines:
                    lines.append(f"{indent}    {tl}")

        elif vtype == "NUM":
            lines.append(f"{indent}  {concept}: {value}")

        elif vtype == "CODE":
            lines.append(f"{indent}  {concept}: {value}")

        elif vtype == "IMAGE":
            lines.append(f"{indent}  {concept or 'Image ref'}: {value}")

        elif vtype == "UIDREF":
            lines.append(f"{indent}  {concept or 'UID'}: {value}")

        elif vtype == "PNAME":
            lines.append(f"{indent}  {concept or 'Person'}: {value}")

        elif vtype in ("DATE", "TIME", "DATETIME"):
            lines.append(f"{indent}  {concept}: {value}")

        elif vtype in ("SCOORD", "SCOORD3D", "TCOORD"):
            lines.append(f"{indent}  {concept or vtype}: {value}")

        elif vtype in ("COMPOSITE", "WAVEFORM"):
            lines.append(f"{indent}  {concept or vtype}: {value}")

        else:
            if concept or value:
                lines.append(f"{indent}  {concept}: {value}" if concept else f"{indent}  {value}")

    return "\n".join(lines)
