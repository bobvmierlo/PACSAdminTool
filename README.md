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
| **DICOM Receiver** | Embedded DICOM SCP — receive C-STORE and C-ECHO; auto-saves received DICOM files |
| **SR Viewer** | Parse and display any DICOM Structured Report in a human-readable format |
| **KOS Creator** | Build a DICOM Key Object Selection document (XDS-I manifest) from existing DICOM files |
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

### DICOM Receiver (SCP Listener)
- Runs a DICOM SCP in the background
- Accepts C-STORE (all common modalities) and C-ECHO
- Saves received files to a configurable directory

### SR Viewer
Reads and displays any DICOM Structured Report in a readable, indented format.

**Supported SR SOP classes:**
- Basic Text SR, Enhanced SR, Comprehensive SR, Comprehensive 3D SR
- X-Ray Radiation Dose SR, Patient Radiation Dose SR, Enhanced X-Ray Radiation Dose SR
- Mammography CAD SR, Chest CAD SR, Colon CAD SR
- Simplified Adult Echo SR
- Acquisition Context SR, Implantation Plan SR
- Key Object Selection (KOS)
- And any other SR SOP class (generic fallback)

**Supported content item types:** `CONTAINER`, `NUM` (with units), `TEXT`, `CODE`, `IMAGE`, `UIDREF`, `PNAME`, `DATE`, `TIME`, `DATETIME`, `SCOORD`, `SCOORD3D`, `TCOORD`, `COMPOSITE`, `WAVEFORM`

The formatted report shows measurements with their units (mm, HU, mGy, mSv, %, bpm, …), nested containers with indented hierarchy, and referenced image UIDs. A "View Raw DICOM Tags" button opens the full tag list for deeper inspection.

### KOS Creator
Builds a DICOM **Key Object Selection** document (SOP `1.2.840.10008.5.1.4.1.1.88.59`) that can be used as an **XDS-I manifest** when publishing a study to an IHE XDS domain.

**Workflow:**
1. Load one or more DICOM files — the tool extracts patient, study, series, and instance metadata automatically.
2. Review and edit the study/patient fields and the referenced instance list if needed.
3. Choose a document title (Of Interest, For Referring Provider, XDS-I Manifest, etc.).
4. Create & Save the KOS as a `.dcm` file, or Create & Send it directly via C-STORE.

**Instance list format** (one line per instance, `#` lines are comments):
```
# SeriesUID | SOPClassUID | SOPInstanceUID
1.2.3.4.5|1.2.840.10008.5.1.4.1.1.2|1.2.3.4.5.6.7
```

The generated KOS includes:
- `ContentSequence` with IMAGE items and observer context
- `CurrentRequestedProcedureEvidenceSequence` (required by DICOM PS3.3 C.17.6)
- Proper file meta with Explicit VR Little Endian transfer syntax
- All nine CID 7010 document titles, including `XDS-I Manifest (DCM:113500)`

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
| Web UI | 5000 |

Configure in **Settings** tab or `~/.pacs_admin_tool/config.json`.

---

## License

MIT — free for personal and commercial use.
