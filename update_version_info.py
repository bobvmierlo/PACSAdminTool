"""
Sync version_info_web.py and version_info_gui.py with __version__.py.

Run this script (or let the build scripts call it) whenever __version__.py changes.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# Read version from __version__.py
version_text = (ROOT / "__version__.py").read_text()
match = re.search(r'__version__\s*=\s*"([^"]+)"', version_text)
if not match:
    print("ERROR: Could not parse __version__ from __version__.py")
    sys.exit(1)

version_str = match.group(1)  # e.g. "2.3.0"
parts = version_str.split(".")
if len(parts) < 3:
    print(f"ERROR: Expected at least 3 version components, got: {version_str}")
    sys.exit(1)

major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
build = int(parts[3]) if len(parts) > 3 else 0

tuple_str = f"({major}, {minor}, {patch}, {build})"   # e.g. (2, 3, 0, 0)
dotted_str = f"{major}.{minor}.{patch}.{build}"        # e.g. 2.3.0.0

FILES = ["version_info_web.py", "version_info_gui.py"]

for filename in FILES:
    path = ROOT / filename
    content = path.read_text(encoding="utf-8")

    # Tuple fields: filevers=(...) and prodvers=(...)
    content = re.sub(r"(filevers\s*=\s*)\([^)]+\)", rf"\g<1>{tuple_str}", content)
    content = re.sub(r"(prodvers\s*=\s*)\([^)]+\)", rf"\g<1>{tuple_str}", content)

    # String fields: FileVersion and ProductVersion
    content = re.sub(
        r'(StringStruct\("FileVersion",\s*")[^"]+(")',
        rf"\g<1>{dotted_str}\g<2>",
        content,
    )
    content = re.sub(
        r'(StringStruct\("ProductVersion",\s*")[^"]+(")',
        rf"\g<1>{dotted_str}\g<2>",
        content,
    )

    path.write_text(content, encoding="utf-8")
    print(f"Updated {filename} -> {dotted_str}")

print(f"Version sync complete: {version_str}")
