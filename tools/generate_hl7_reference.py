#!/usr/bin/env python3
"""Generate the HL7 v2 reference data bundled with the web inspector.

The web "Inspect Message" tool needs to label every segment, field, and
composite-datatype component of an HL7 v2 message with its standard name,
data type, and cardinality. Rather than hand-maintaining those dictionaries,
this script extracts them from *hl7apy* (MIT-licensed), whose definitions are
generated from the official HL7 databases, and writes one compact JSON file
per HL7 version into ``web/static/hl7ref/``.

hl7apy is a BUILD-TIME dependency only: the generated JSON is committed to the
repo and shipped as a static asset, so the running application never calls out
to hl7apy or any third-party service. The inspector stays fully offline.

Run from the repo root:

    pip install hl7apy
    python tools/generate_hl7_reference.py

Then commit the regenerated files under web/static/hl7ref/.
"""

import importlib
import json
import os
import re
from datetime import date

# hl7apy version modules, oldest → newest. "2_7_1" is intentionally absent
# (hl7apy does not ship it). The dotted form is what MSH-12 carries.
VERSION_MODULES = [
    "2_1", "2_2", "2_3", "2_3_1", "2_4",
    "2_5", "2_5_1", "2_6", "2_7", "2_8", "2_8_1",
]

# Field/component values fall back to this version's definitions when a
# message's MSH-12 version is missing or unknown.
DEFAULT_VERSION = "2.5.1"

_COMP_KEY = re.compile(r"^(.*)_(\d+)$")

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "web", "static", "hl7ref")


def _title(name):
    """HL7apy long-names are SHOUTY_SNAKE_CASE; make them human-readable."""
    if not name:
        return ""
    return name.replace("_", " ").title()


def _rec(cdef):
    """Pull (long-name, data-type, table) out of a hl7apy element record.

    Records look like ['leaf', None, 'ST', 'PATIENT_NAME', 'HL70200', -1] or a
    ('sequence', (...children...), 'XPN', 'PATIENT_NAME', table, -1) tuple. Both
    put the data type at index 2, the long-name at index 3, and (when present)
    the table id at index 4.
    """
    if not isinstance(cdef, (list, tuple)) or len(cdef) < 4:
        return None, None, None
    dt = cdef[2] if len(cdef) > 2 else None
    name = cdef[3] if len(cdef) > 3 else None
    table = cdef[4] if len(cdef) > 4 else None
    if not isinstance(dt, str):
        dt = None
    if not isinstance(table, str):
        table = None
    return _title(name), dt, table


def _segments(mod):
    """{ 'MSH': [ [name, datatype, min, max, table], ... ], ... }."""
    out = {}
    for sid, sdef in mod.SEGMENTS.items():
        try:
            children = sdef[1]
        except (IndexError, TypeError):
            continue
        fields = []
        for child in children:
            # child = (element_id, element_def, (min, max), role)
            if not (isinstance(child, (list, tuple)) and len(child) >= 3):
                continue
            cdef, card = child[1], child[2]
            if not (isinstance(card, (list, tuple)) and len(card) == 2):
                continue
            name, dt, table = _rec(cdef)
            fields.append([name, dt, card[0], card[1], table])
        if fields:
            out[sid] = fields
    return out


def _datatypes(mod):
    """{ 'XPN': [ [component_name, datatype], ... ], ... }.

    hl7apy keys composite components as XPN_1, XPN_2, … — group them back by
    base name in positional order.
    """
    grouped = {}
    for key, rec in mod.DATATYPES.items():
        m = _COMP_KEY.match(key)
        if not m:
            continue
        base, idx = m.group(1), int(m.group(2))
        name, dt, _table = _rec(rec)
        grouped.setdefault(base, []).append((idx, name, dt))
    out = {}
    for base, items in grouped.items():
        items.sort(key=lambda t: t[0])
        out[base] = [[name, dt] for _idx, name, dt in items]
    return out


def build_version(vsuf):
    mod = importlib.import_module("hl7apy.v" + vsuf)
    return {"segments": _segments(mod), "datatypes": _datatypes(mod)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    for vsuf in VERSION_MODULES:
        dotted = vsuf.replace("_", ".")
        ref = build_version(vsuf)
        path = os.path.join(OUT_DIR, dotted + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ref, fh, separators=(",", ":"), ensure_ascii=False)
        size = os.path.getsize(path)
        written.append((dotted, len(ref["segments"]), len(ref["datatypes"]), size))
        print(f"  v{dotted:6}  segments={len(ref['segments']):3}  "
              f"datatypes={len(ref['datatypes']):3}  {size:>7} bytes")

    index = {
        "generated": date.today().isoformat(),
        "generator": "hl7apy (build-time only; MIT)",
        "default": DEFAULT_VERSION,
        "versions": [v for v, *_ in written],
    }
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {len(written)} version files + index.json to {OUT_DIR}")


if __name__ == "__main__":
    main()
