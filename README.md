# PACS Admin Tool

A portable, self-contained DICOM/HL7 workstation for PACS administrators.  
**No installation required** — just run `PacsAdminTool.exe`.

---

## Features

| Tab | Functionality |
|-----|--------------|
| **C-FIND / Q-R** | Patient/Study/Series/Image level C-FIND, C-ECHO, C-MOVE with query builder |
| **C-STORE** | Send single files or entire folder trees to any Storage SCP |
| **DMWL** | Full Modality Worklist query with export to CSV |
| **Storage Commit** | Send N-ACTION storage commitment requests; receive N-EVENT-REPORT responses |
| **IOCM** | Send Instance Availability Notifications (delete/change notifications) |
| **HL7** | Send/receive HL7 v2 messages over MLLP; built-in templates for ORM, ORU, ADT, SIU, QBP |
| **SCP Listener** | Embedded DICOM SCP — receive C-STORE and C-ECHO; auto-saves received DICOM files |
| **Settings** | Manage local AE title/port, remote AE presets, HL7 defaults |

---

## Quick Start (Desktop GUI)

```bash
# 1. Install dependencies
pip install pydicom pynetdicom hl7

# 2. Run
python main.py
```

---

## Quick Start (Web Version)

```bash
# 1. Install dependencies (includes the desktop ones plus web extras)
pip install pydicom pynetdicom hl7 flask flask-socketio simple-websocket

# 2. Run the web server
python webmain.py

# 3. Open in your browser
#    http://localhost:5000
```

To allow other PCs on your network to connect:
```bash
python webmain.py --host 0.0.0.0
# Others can reach it at http://<your-ip>:5000
```

To use a different port:
```bash
python webmain.py --port 8080
```

---

## Build a Portable .exe (Windows)

```bat
# One command:
build.bat
```

This produces `dist\PacsAdminTool.exe` — a single executable with no external dependencies.

### Manual build steps:
```bash
pip install pydicom pynetdicom hl7 pyinstaller
pyinstaller pacs_tool.spec --clean --noconfirm
```

---

## Build on Linux / macOS

```bash
chmod +x build.sh
./build.sh
# Output: dist/PacsAdminTool
```

---

## Configuration

Settings are saved to `~/.pacs_admin_tool/config.json` automatically.

### Remote AE Presets
Add your PACS, RIS, and modality AE entries in the **Settings** tab.  
They become available as a dropdown in every other tab.

---

## DICOM Operations Reference

### C-FIND
- Supports Patient Root and Study Root query models
- Query levels: PATIENT, STUDY, SERIES, IMAGE
- Wildcard matching supported (e.g. `SMITH*` for patient name)

### C-MOVE
- Select a result row from C-FIND, specify destination AE title
- Destination must have your local AE registered as a known source

### C-STORE
- Sends files using all common Storage SOP classes
- Recursive folder scanning supported

### DMWL
- Queries ModalityWorklistInformationFind SOP
- Filters: patient, date, modality, AE title, accession
- CSV export of results

### Storage Commitment
- Sends N-ACTION with a list of SOP Class/Instance UID pairs
- Displays N-EVENT-REPORT response (committed / failed)
- Load references directly from DICOM files

### IOCM
- Sends Instance Availability Notification (N-CREATE)
- Marks instances as UNAVAILABLE for delete notifications
- Per PS3.4 Annex KK

### SCP Listener
- Runs a DICOM SCP in the background
- Accepts C-STORE (all common modalities) and C-ECHO
- Saves received files to a configurable directory

---

## HL7 Message Templates

| Template | Description |
|----------|-------------|
| ORM^O01 | Radiology order |
| ORU^R01 | Observation/report result |
| ADT^A04 | Patient registration |
| SIU^S12 | Schedule notification |
| QBP^Q22 | Patient demographics query (PDQ) |

All templates are editable before sending. Raw HL7 text can also be pasted directly.

---

## Requirements

**Desktop version:**
- Python 3.10+
- pynetdicom >= 2.0
- pydicom >= 2.4
- hl7 >= 0.4.5
- PyInstaller >= 6.0 (build only)

**Web version (additional):**
- flask >= 3.0
- flask-socketio >= 5.3
- simple-websocket >= 1.0

The compiled `.exe` has **no runtime requirements**.

---

## Network Ports

| Service | Default Port |
|---------|-------------|
| Local DICOM SCP | 11112 |
| HL7 MLLP Listener | 2575 |

Configure in **Settings** tab or `~/.pacs_admin_tool/config.json`.

---

## License

MIT — free for personal and commercial use.
