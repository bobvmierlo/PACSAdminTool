# PACS Admin Tool

A portable, self-contained DICOM/HL7 workstation for PACS administrators.

**No installation required** — just run `PacsAdminTool.exe` or `PacsAdminToolWeb.exe`.
Can also be run locally with Python and pip, or deployed as a Docker container.

**Note:** This tool was built for my own professional use. The repository is not actively maintained and issues may not be addressed.

---

## Features

### Web UI Tabs

| Tab | Functionality |
|-----|--------------|
| **Dashboard** | AE connectivity health check (batch C-ECHO all presets at once), service status, recent audit activity |
| **C-FIND / Q-R** | Patient/Study/Series/Image level C-FIND with query builder; multi-select results with checkboxes; bulk C-MOVE or C-GET retrieve |
| **C-STORE** | Send single files or entire folder trees to any Storage SCP |
| **DMWL** | Full Modality Worklist query with export to CSV |
| **Storage Commit** | Send N-ACTION storage commitment requests; receive async N-EVENT-REPORT responses with committed/failed breakdown |
| **IOCM** | Send Instance Availability Notifications (delete/change notifications) |
| **HL7** | Send/receive HL7 v2 messages over MLLP; built-in templates for ORM, ORU, ADT, SIU, OML, QBP |
| **DICOM Receiver** | Embedded DICOM SCP — receive C-STORE and C-ECHO; auto-saves files; inspect tags or delete files per-row; auto-purges files older than 24 h |
| **DICOM Inspector** | Upload any `.dcm` file and browse all DICOM tags in a searchable, collapsible tree |
| **Anonymizer** | Strip PHI from one or more DICOM files using a Basic or Full profile; download result as a ZIP |
| **DICOMDIR** | Read a DICOMDIR file and browse the Patient → Study → Series → Instance hierarchy; or generate a standards-compliant DICOMDIR from uploaded files/folder and download as ZIP |
| **SR Viewer** | Parse and display any DICOM Structured Report in a human-readable format |
| **KOS Creator** | Build a DICOM Key Object Selection document (XDS-I manifest) from existing DICOM files |
| **Settings** | Manage local AE title/port, remote AE presets, HL7 defaults, language, log level |
| **Logs** | Live view of application logs from `~/.pacs_admin_tool/logs/` |

---

## Automatic Update Notifications

Both the desktop GUI and the web UI check GitHub Releases on startup and show a **styled notification banner** when a newer version is available.

**Web UI** — a blue slide-in banner appears below the header bar:
- Shows the new version number and a link to the release page
- On `.exe` builds: a **"Download Update"** button downloads the new binary in the background; once ready it becomes **"Install & Restart"** — the swap and restart happen automatically

**Desktop GUI** — a matching blue banner appears between the header and tabs:
- Same Download / Install & Restart / View Release buttons
- Fires 3 seconds after startup in a background thread; the UI is never blocked

**Auto-update details:**
- Works for frozen PyInstaller executables (`PacsAdminTool.exe`, `PacsAdminToolWeb.exe`)
- Windows: a detached batch script performs the swap after the process exits, then relaunches
- Linux/macOS: the binary is replaced in-place and `os.execv()` restarts the process
- Docker and source-code installs: only the "View Release ↗" link is shown (no auto-update)
- Uses only Python standard-library modules (`urllib`, `json`, `threading`) — **no extra packages required**
- Results are cached for 1 hour; GitHub is never contacted more than once per hour

---

## System Tray Icon

Both the desktop GUI and the web server can show a **system tray icon** (notification area, bottom-right on Windows) when `pystray` and `Pillow` are installed. The app works without them, but system tray functionality will be disabled.

**Desktop GUI:**
- Closing the window (X button) minimises the app to the tray instead of quitting
- Double-click the tray icon or use the right-click menu to restore the window
- Right-click menu: *Show Window*, *Open Data Folder*, *Exit*

**Web Server:**
- The tray icon is the only visual indicator that the server is running (no console window)
- Right-click menu: *Open in Browser*, *Open Data Folder*, *Exit*
- No need to use Task Manager to stop the server — just click *Exit* in the tray menu

---

## Quick Start (Desktop GUI)

```bash
# 1. Install dependencies
pip install pydicom pynetdicom hl7

# 2. (Optional) Install system tray support
pip install pystray Pillow

# 3. Run
python main.py
```

---

## Quick Start (Web Version)

```bash
# 1. Install dependencies
pip install pydicom pynetdicom hl7 flask flask-socketio simple-websocket

# 2. (Optional) Install system tray support
pip install pystray Pillow

# 3. Run the web server
python webmain.py

# 4. Open in your browser
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

To enable debug mode with auto-reload:
```bash
python webmain.py --debug
```

---

## Quick Start (Docker)

The web server is available as a pre-built Docker image on the GitHub Container Registry.
No Python installation required — Docker is all you need.

### Using docker-compose (recommended)

Copy the `docker-compose.yml` from this repository and run:

```bash
docker compose up -d
```

Then open **http://localhost:5000** in your browser.

Config and logs are stored in a named Docker volume (`pacs_data`) so they survive container restarts and upgrades.

To upgrade to a newer version:

```bash
docker compose pull
docker compose up -d
```

---

### docker-compose.yml options explained

```yaml
services:
  pacsadmintool:
    image: ghcr.io/bobvmierlo/pacsadmintool:latest
    container_name: pacsadmintool
    restart: unless-stopped

    ports:
      - "5000:5000"       # Web UI — change the left number to use a different host port
                          # e.g. "8080:5000" to reach the UI at http://your-server:8080

      # Uncomment these if you want the built-in listeners to accept traffic
      # from outside the container. The left (host) port must match what you
      # configure in the Settings tab inside the app.
      #- "11112:11112"    # DICOM Storage SCP (C-STORE / C-ECHO receiver)
      #- "2575:2575"      # HL7 MLLP listener

    volumes:
      - pacs_data:/data   # Named volume — stores config.json and log files.
                          # Replace with a bind-mount if you prefer a specific path
                          # on the host, e.g.: - /opt/pacsadmin:/data

    environment:
      # PACS_DATA_DIR is already set to /data inside the image.
      # Only override this if you change the volume mount point above.
      # - PACS_DATA_DIR=/data

volumes:
  pacs_data:
```

**Key settings at a glance:**

| Option | What it does |
|--------|-------------|
| `"5000:5000"` | Maps host port → container port. Change the left number to expose the UI on a different host port. |
| `"11112:11112"` | Required if you want to receive DICOM via C-STORE from external systems. Must match the SCP port in Settings. |
| `"2575:2575"` | Required if you want to receive HL7 messages from external systems. Must match the HL7 listener port in Settings. |
| `pacs_data:/data` | Named volume for persistent storage. Swap for a bind-mount (e.g. `/opt/pacsadmin:/data`) if you need direct host-filesystem access to your config or logs. |
| `restart: unless-stopped` | The container restarts automatically after a reboot or crash. Use `no` to disable, or `always` to restart even after a manual `docker stop`. |

---

### Running without docker-compose

```bash
docker run -d \
  --name pacsadmintool \
  --restart unless-stopped \
  -p 5000:5000 \
  -v pacs_data:/data \
  ghcr.io/bobvmierlo/pacsadmintool:latest
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
pip install -r requirements.txt
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
Logs are written to `~/.pacs_admin_tool/logs/` with automatic 7-day rotation.

When running in Docker the data directory is `/data` inside the container
(controlled by the `PACS_DATA_DIR` environment variable). Mount a volume there
to keep your config and logs across restarts — see the Docker section above.

### Remote AE Presets
Add your PACS, RIS, and modality AE entries in the **Settings** tab.
They become available as a dropdown in every other tab.

### Language
The UI supports English and Dutch. Switch languages in the **Settings** tab.

---

## DICOM Operations Reference

### C-FIND
- Supports Patient Root and Study Root query models
- Query levels: PATIENT, STUDY, SERIES, IMAGE
- Wildcard matching supported (e.g. `SMITH*` for patient name)
- Results shown in a table with checkboxes for bulk selection

### C-MOVE
- Retrieve one or more C-FIND results to a destination AE
- Destination must have your local AE registered as a known source
- Bulk mode: select multiple rows and retrieve sequentially

### C-GET
- Alternative to C-MOVE — pulls files directly into the application without requiring an inbound port on the destination
- Not supported by all PACS systems (optional per DICOM standard)
- See the **Help** tab for a full C-MOVE vs C-GET comparison

### C-STORE
- Sends files using all common Storage SOP classes
- Recursive folder scanning supported

### DMWL
- Queries ModalityWorklistInformationFind SOP
- Filters: patient, date, modality, AE title, accession
- CSV export of results

### Storage Commitment
- Sends N-ACTION with a list of SOP Class/Instance UID pairs
- Async N-EVENT-REPORT arrives on a separate inbound association (requires the DICOM Receiver to be running)
- Displays committed/failed counts and per-UID failure reason codes

### IOCM
- Sends Instance Availability Notification (N-CREATE)
- Marks instances as UNAVAILABLE for delete notifications
- Per PS3.4 Annex KK

### DICOM Receiver (SCP Listener)
- Runs a DICOM SCP in the background
- Accepts C-STORE (all common modalities), C-ECHO, and Storage Commitment N-EVENT-REPORT callbacks
- Saves received files to a configurable directory
- Per-file Inspect (full tag browser) and Delete actions in the Files on Disk table
- **Auto-purge**: files older than 24 hours are deleted on startup and nightly at 01:00 to prevent patient data from lingering

### DICOM Inspector
- Upload any `.dcm` file and browse all tags in a searchable, collapsible tree
- Sequence (SQ) elements expand inline; binary data shown as byte-length summary

### Anonymizer
- Upload one or more DICOM files
- **Basic profile**: removes patient identifiers and institution details
- **Full profile**: additionally removes study/series descriptions and other potentially identifying fields
- Replacement patient name and ID can be specified
- Output downloaded as a ZIP archive

### DICOMDIR
- **Reader**: upload a DICOMDIR file to browse the Patient → Study → Series → Instance hierarchy
- **Generator**: upload individual DICOM files or an entire folder; a standards-compliant DICOM File Set (DICOMDIR + organised instance files) is generated using `pydicom.FileSet` and returned as a downloadable ZIP

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
| OML^O21 | Lab order |
| ORU^R01 | Observation/report result |
| ADT^A04 | Patient registration |
| ADT^A08 | Patient update |
| ADT^A23 | Delete visit |
| SIU^S12 | Schedule appointment |
| SIU^S15 | Cancel appointment |
| QBP^Q22 | Patient demographics query (PDQ) |

All templates are editable before sending. Raw HL7 text can also be pasted directly.

---

## Requirements

**Desktop version:**
- Python 3.10+
- pynetdicom
- pydicom
- hl7

**Optional:**
- pystray (system tray icon)
- Pillow (icon rendering for tray)
- PyInstaller (build only)

**Web version (additional):**
- flask
- flask-socketio
- simple-websocket

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

## Open-source credits

The web UI bundles the following JavaScript libraries (all served locally, no CDN):

| Library | Version | Author / Project | License | Link |
|---------|---------|-----------------|---------|------|
| **dwv** (DICOM Web Viewer) | 0.33 | Yves Martelli | GPL-3.0 | [github.com/ivmartel/dwv](https://github.com/ivmartel/dwv) |
| **Konva** | 8.4.2 | Anton Lavrenov | MIT | [github.com/konvajs/konva](https://github.com/konvajs/konva) |
| **JSZip** | 3.10.1 | Stuart Knightley | MIT / GPL-3.0 | [github.com/Stuk/jszip](https://github.com/Stuk/jszip) |
| **magic-wand-tool** | 1.1.7 | Ryasnoy Paul | MIT | [github.com/Tamersoul/magic-wand-js](https://github.com/Tamersoul/magic-wand-js) |
| **Socket.IO** (client) | 4.7.2 | Guillermo Rauch | MIT | [github.com/socketio/socket.io](https://github.com/socketio/socket.io) |

The DICOM decoder Web Worker scripts bundled under `web/static/decoders/` originate from the **dwv** project and its upstream sources:

- `decoders/pdfjs/` — JPEG 2000 / JPEG Baseline decoders adapted from [Mozilla PDF.js](https://github.com/mozilla/pdf.js) (Apache-2.0)
- `decoders/rii-mango/` — JPEG Lossless decoder from [rii-mango/jpeg-lossless-decoder-js](https://github.com/rii-mango/JPEG-Lossless-decoder-JS) (MIT)
- `decoders/dwv/` — RLE decoder from the dwv project (GPL-3.0)
