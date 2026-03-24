"""
HL7 Template Loader
===================
Reads all .hl7 files from the hl7_templates/ folder and returns them
as a list of dicts, sorted by filename so the order is predictable.

Each .hl7 file has a simple format:
  - Lines starting with '#' are metadata/comments.
    # name: <display name>
    # description: <help text>
  - All other lines are the message body (one segment per line).
    Segments are joined with \\r (carriage return) as required by MLLP.

This module is imported by:
  - gui/app.py  (desktop GUI)
  - web/server.py  (web backend — exposes templates via REST API)
"""
from __future__ import annotations

import os
import sys
import glob


def _templates_dir() -> str:
    """Return the hl7_templates directory, handling PyInstaller one-file bundles."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "hl7_templates")
    return os.path.dirname(os.path.abspath(__file__))


# The folder that contains all .hl7 template files.
TEMPLATES_DIR = _templates_dir()


def load_templates() -> list[dict]:
    """
    Scan the hl7_templates/ folder for *.hl7 files and return them
    as a sorted list of dicts:

      [
        {
          "name":        "ORM^O01 - Radiology Order",
          "description": "Sent by RIS/HIS to PACS ...",
          "body":        "MSH|^~\\&|...\\rPID|...\\r...",
          "filename":    "ORM_O01_RadiologyOrder.hl7",
        },
        ...
      ]

    Files are sorted alphabetically by filename so the order in the
    dropdown is consistent and predictable.
    """
    templates = []
    pattern = os.path.join(TEMPLATES_DIR, "*.hl7")

    for filepath in sorted(glob.glob(pattern)):
        filename = os.path.basename(filepath)
        try:
            template = _parse_template_file(filepath, filename)
            templates.append(template)
        except Exception as e:
            # Don't crash if one file is malformed — just skip it and warn
            import logging
            logging.getLogger(__name__).warning(
                f"Could not load HL7 template '{filename}': {e}")

    return templates


def _parse_template_file(filepath: str, filename: str) -> dict:
    """
    Parse a single .hl7 file into a template dict.

    Metadata lines (starting with #) are stripped from the body.
    The remaining lines are joined with \\r to form the HL7 message.
    """
    name        = filename.replace(".hl7", "").replace("_", " ")
    description = ""
    body_lines  = []

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")

            if line.startswith("# name:"):
                # Extract the display name after "# name:"
                name = line[len("# name:"):].strip()

            elif line.startswith("# description:"):
                # Extract the description after "# description:"
                description = line[len("# description:"):].strip()

            elif line.startswith("#"):
                # Other comment lines — ignore
                pass

            else:
                # Non-comment line = part of the HL7 message body
                body_lines.append(line)

    # Join segments with \r (MLLP/HL7 segment separator)
    # Strip any trailing empty lines to keep the message clean
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    body = "\r".join(body_lines)

    return {
        "name":        name,
        "description": description,
        "body":        body,
        "filename":    filename,
    }


def get_template_by_name(name: str) -> dict | None:
    """Find a template by its display name. Returns None if not found."""
    for tmpl in load_templates():
        if tmpl["name"] == name:
            return tmpl
    return None
