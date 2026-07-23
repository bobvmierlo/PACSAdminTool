# Changelog

## v3.3.2 — 2026-07-23

### Improved — [#154](https://github.com/bobvmierlo/PACSAdminTool/pull/154)

- **Docker update hints** — when one-click updates aren't available, the update card now explains why (for example, the Docker socket isn't mounted or the app isn't running under Docker Compose) instead of silently showing only the manual instructions.

### Improved — [#155](https://github.com/bobvmierlo/PACSAdminTool/pull/155)

- The running version number now appears in the startup log messages for both the web server and desktop client, making it easier to confirm which version is running.

## v3.3.1 — 2026-07-23

Internal change — no release note (dependency updates only).

## v3.3.0 — 2026-07-17

### New — [#151](https://github.com/bobvmierlo/PACSAdminTool/pull/151)

- **One-click Docker update** — when running as a Docker Compose service with the host's Docker socket mounted, administrators get an "Update & Restart" button in the update banner and About tab that pulls the new image and restarts the app automatically, with the page reloading once the restart completes. Manual instructions remain available as a fallback.

## v3.2.1 — 2026-07-16

### New — [#150](https://github.com/bobvmierlo/PACSAdminTool/pull/150)

- **Requested Procedure ID in DICOMize** — you can now set a Requested Procedure ID when converting files, entered manually or auto-filled from Modality Worklist, C-FIND, and worklist selections, helping PACS systems match imported objects to the right study or order.

## v3.2.0 — 2026-07-16

### New — [#149](https://github.com/bobvmierlo/PACSAdminTool/pull/149)

- **C-FIND source in DICOMize** — a new C-FIND tab lets you query a PACS directly for studies (by patient name, ID, accession, or study date) and click a result to auto-fill the study details, useful for studies no longer on the worklist.
- **Change your own password** — a Change Password card in My Preferences lets you update your password after confirming your current one.
- **Admin password reset** — administrators can reset another user's password from the Users table without needing that user's current password.

## v3.1.0 — 2026-07-13

### New — [#146](https://github.com/bobvmierlo/PACSAdminTool/pull/146)

- **Job tracking for transfers** — retrieve and send operations (C-MOVE, C-GET, C-STORE) now run as tracked jobs whose progress survives page refreshes and dropped connections.
- **DICOM TLS support** — outgoing connections (echo, query, retrieve, send) and the Storage receiver can now use optional TLS encryption, with configurable client certificates and CA bundles.
- **Extra Return Tags for C-FIND** — a new field lets you request additional return tags in a query using DICOM keywords or `(gggg,eeee)` notation.
- **Configurable HL7 acknowledgements** — the HL7 listener can now be set to reply with AA, AE, or AR acknowledgement codes.

### Improved — [#146](https://github.com/bobvmierlo/PACSAdminTool/pull/146)

- **Per-level C-FIND queries** — queries now send only the return keys valid for the chosen level (Patient, Study, Series, or Image), following the DICOM standard.
- **Persistent HL7 message history** — received HL7 messages are now stored on the server, so history is kept across page refreshes and can be cleared on demand.

### Fixed — [#146](https://github.com/bobvmierlo/PACSAdminTool/pull/146)

- Operation logs and echo-test results are now private to each user, so concurrent users no longer see each other's activity.

## v3.0.0 (pre-release) — 2026-07-12

Implements the first code improvement from ROADMAP.md: the single ~7,500-line inline <script> block in web/static/index.html is split into 30 per-domain files under web/static/js/.

What changed
- One file per feature domain:
  core.js (i18n, toasts, dialogs, shared helpers), socket.js, tabs.js, settings.js, ae-selector.js, and one file per tab (cfind.js, cstore.js, dmwl.js, commit-iocm.js, hl7-templates.js, hl7-tools.js, scp-receiver.js, dicomweb.js, dicomize.js, anonymizer.js, inspector.js, sr-viewer.js, kos.js, uid-remap.js, dicomdir.js, validator.js, dashboard.js, logs.js, help.js, tag-modal.js, scp-stats.js, echo.js), plus updater.js and init.js.
- Plain <script> tags, loaded in the original source order — no build system, no ES modules, shared global scope is unchanged.
- The only reordering: init.js (the page-bootstrap IIFE, which defines nothing) now loads last, so every function exists before it runs.
- index.html: 11,204 → 3,746 lines (markup + CSS + 30 script tags).
- No backend, packaging, or behavior changes. The PyInstaller spec already bundles web/static/* recursively, so built executables pick up the new directory unchanged.

## v2.19.0 — 2026-07-12

### Fixed — [#142](https://github.com/bobvmierlo/PACSAdminTool/pull/142)

- Outgoing DICOM connections now time out instead of hanging indefinitely when a remote peer becomes unresponsive.
- SCP auto-purge now correctly removes files in Study/Series subdirectories — previously only top-level files were cleaned up.
- DICOM tag comparisons now detect changes inside nested sequences (e.g. ReferencedSeriesSequence).
- HL7 listener message history is now capped, preventing unbounded memory growth on long-running instances.

### New — [#142](https://github.com/bobvmierlo/PACSAdminTool/pull/142)

- **HTTPS support** — the web interface can now be served over TLS using the `--cert` and `--key` flags.
- **Login rate-limiting** — after 5 failed attempts within 15 minutes, further attempts are blocked for 60 seconds.
- **Hardened session cookies** — cookies now carry HttpOnly, SameSite=Lax, and Secure (when TLS is on) flags; sessions expire after 12 hours.
- **Anonymizer: remove private tags** — new option to strip all vendor-private DICOM tags from exported files.
- **Anonymizer: regenerate UIDs** — new option to generate fresh Study/Series/Instance UIDs, with consistent remapping across a batch.
- **Anonymizer: burned-in PHI warning** — files that likely contain burned-in patient data are flagged, with a warning summary included in the export ZIP.

## v2.18.1 — 2026-06-24

### Improved — [#139](https://github.com/bobvmierlo/PACSAdminTool/pull/139)

- **Docker image refresh** — the Docker image is now built on Python 3.13.

## v2.18 — 2026-06-24

Internal change — no release note (dependency updates and build tooling only).

## v2.17.6 — 2026-05-18

### New — [#133](https://github.com/bobvmierlo/PACSAdminTool/pull/133)

- **Calling AE Title for worklist queries** — the Worklist (DMWL) tab now has a dedicated Calling AE Title field, so worklist queries can identify themselves with a different AE title than the local receiver.

## v2.17.5 — 2026-05-07

### Fixed — [#131](https://github.com/bobvmierlo/PACSAdminTool/pull/131)

- Audit logs are now included in the automatic 7-day log cleanup, so they no longer accumulate indefinitely.

## v2.17.4 — 2026-05-06

Internal change — no release note (dependency updates only).

## v2.17.3 — 2026-05-01

### Improved — [#129](https://github.com/bobvmierlo/PACSAdminTool/pull/129)

- **ORM mapping help** — new "Default mapping" and "Available fields" buttons show exactly which HL7 fields map to which DICOM values, and which field names you can use in custom mappings.
- **Inspect HL7 in DICOMize** — new Inspect buttons let you open received ORM messages and outgoing ORU messages in a built-in HL7 inspector.

## v2.17.2 — 2026-05-01

### Fixed — [#128](https://github.com/bobvmierlo/PACSAdminTool/pull/128)

- The tag editor no longer crashes when opened in certain situations.
- Custom ORM field mappings with three-part specifications (e.g. PID.5.1) were silently ignored — they now work as documented.
- Study description and accession number are now taken from the correct ORM fields.

### Improved — [#128](https://github.com/bobvmierlo/PACSAdminTool/pull/128)

- When you start a retrieve while the local DICOM receiver is stopped, the app now offers to start it for you instead of failing silently.

## v2.17.1 — 2026-05-01

### Fixed — [#127](https://github.com/bobvmierlo/PACSAdminTool/pull/127)

- The DICOMize activity log no longer appears on unrelated tabs.
- Long filenames no longer overflow the inspector metadata panel.
- The worklist query inside the DICOMize source panel now returns results correctly.

### New — [#127](https://github.com/bobvmierlo/PACSAdminTool/pull/127)

- **Jump to Receiver after retrieve** — after a successful C-MOVE, the app automatically switches to the DICOM Receiver tab and refreshes the study tree.
- **Anonymize received series** — each received series now has an "Anonymize…" button that loads its files straight into the Anonymizer.
- **Retrieve study from PACS in Anonymizer** — search a PACS, pick a study, and pull it directly into the Anonymizer in one flow.

## v2.17.0 — 2026-04-29

### Improved — [#126](https://github.com/bobvmierlo/PACSAdminTool/pull/126)

- **DICOMize overhaul** — drag & drop uploads, folder upload, mixed file types in one batch, per-file progress, video frame-rate control, grouping multiple files into one series, a patient-data source switcher, ORM field mapping, metadata preview before conversion, duplicate detection, an ORU/IAN notification workflow, and fixed handling of special characters.

## v2.16.0 — 2026-04-14

### New — [#123](https://github.com/bobvmierlo/PACSAdminTool/pull/123)

- **C-FIND query presets** — save frequently used query parameter sets and reload them from a dropdown.
- **Configuration backup** — export the system configuration to a file and import it back, from the Settings tab.

## v2.15.6 — 2026-04-14

### Fixed — [#120](https://github.com/bobvmierlo/PACSAdminTool/pull/120)

- Regular users can once again save their own language and logging preferences — admin-only enforcement now applies per setting instead of blocking the whole Settings form.

## v2.15.5 — 2026-04-13

### Improved — [#119](https://github.com/bobvmierlo/PACSAdminTool/pull/119)

- **Admin-only system settings** — system-wide settings can now only be changed by administrators; regular users see them as read-only with a clear notice.

## v2.15.4 — 2026-04-13

### Fixed — [#118](https://github.com/bobvmierlo/PACSAdminTool/pull/118)

- Clicking "Edit tags…" in the DICOM Receiver no longer crashes the page.

### Improved — [#118](https://github.com/bobvmierlo/PACSAdminTool/pull/118)

- The Help section now explains the difference between admin and regular user roles.

## v2.15.3 — 2026-04-13

### Fixed — [#117](https://github.com/bobvmierlo/PACSAdminTool/pull/117)

- Deleting a study from the DICOM Receiver no longer fails due to a script error.

## v2.15.2 — 2026-04-13

### Improved — [#115](https://github.com/bobvmierlo/PACSAdminTool/pull/115)

- **Branded dialogs** — all native browser popups (alerts, confirmations, prompts) are replaced with custom in-app dialogs that match the application's look and dark mode.

## v2.15.1 — 2026-04-12

### New — [#114](https://github.com/bobvmierlo/PACSAdminTool/pull/114)

- **Inspect received HL7 messages** — received HL7 messages now have an Inspect button that opens them in the segment/field inspector.

## v2.15.0 — 2026-04-12

### New — [#112](https://github.com/bobvmierlo/PACSAdminTool/pull/112)

- **System DICOMweb presets** — administrators can manage shared DICOMweb server presets for all users.
- **HL7 inspector** — click any segment or field in an HL7 message to see its name, data type, and description.
- **Validator checklist** — the DICOM Validator now shows the full list of checks performed, including the ones that passed.
- **Dark mode toggle in header** — switch between light and dark mode directly from the page header.
- **DICOMweb health check** — the dashboard now tests DICOMweb server connectivity alongside DICOM echo tests.

## v2.14.0 — 2026-04-12

### New — [#111](https://github.com/bobvmierlo/PACSAdminTool/pull/111)

- **Advanced tabs toggle** — less-used tabs (Storage Commit, IOCM, KOS Creator, UID Remapper, DICOMweb) are hidden by default behind an "Advanced" button; each user chooses their own setting.
- **Personal presets** — DICOM and DICOMweb presets can now be saved either system-wide or as personal "My Presets", managed from a new "My Preferences" card in Settings.

### Fixed — [#111](https://github.com/bobvmierlo/PACSAdminTool/pull/111)

- DICOM and DICOMweb presets no longer show up in each other's dropdowns.

## v2.13.0 — 2026-04-11

### New — [#110](https://github.com/bobvmierlo/PACSAdminTool/pull/110)

- **DICOMweb tab** — query, upload, and download via QIDO-RS, STOW-RS, and WADO-RS.
- **DICOM Validator** — check files for missing or invalid required tags.
- **UID Remapper** — regenerate UIDs across a set of files with consistent remapping.
- **DICOM Diff** — compare two DICOM files side by side.
- **Edit tags on received files** — the DICOM Receiver gains an Edit Tags button; the Inspector tab is now called "Inspector & Editor".

## v2.12.1 — 2026-04-10

### Fixed — [#109](https://github.com/bobvmierlo/PACSAdminTool/pull/109)

- AE health indicator dots now update when the dashboard runs its batch echo test.

## v2.12.0 — 2026-04-10

### New — [#108](https://github.com/bobvmierlo/PACSAdminTool/pull/108)

- **Dark mode** — switchable in Settings.
- **Toast notifications** — pop-up alerts are replaced by unobtrusive toast messages.
- **Date and time pickers** — all date/time fields use proper calendar and clock pickers, with a From/To date range for C-FIND and "Today" quick-set buttons.
- **Keyboard shortcuts** — Enter submits the current tab's main action, Escape closes dialogs.
- **AE health dots** — connection health indicators next to preset selectors, updated by echo tests.
- **Copy buttons** — one-click copy on all UID fields.

### Improved — [#108](https://github.com/bobvmierlo/PACSAdminTool/pull/108)

- Search form fields are remembered between visits.
- Dates in query results are shown in a readable DD-MM-YYYY format.

### Fixed — [#108](https://github.com/bobvmierlo/PACSAdminTool/pull/108)

- The connection status indicator no longer resets when switching languages.

## v2.11.5 — 2026-04-09

Internal change — no release note (telemetry library compatibility fix).

## v2.11.4 — 2026-04-09

Internal change — no release note (telemetry library compatibility fix).

## v2.11.3 — 2026-04-09

### Improved — [#104](https://github.com/bobvmierlo/PACSAdminTool/pull/104)

- **Help tab refresh** — sections reordered to match the tab order, new Logs and About sections, and corrected content throughout.

## v2.11.2 — 2026-04-09

### Fixed — [#103](https://github.com/bobvmierlo/PACSAdminTool/pull/103)

- DICOMize presets now load correctly.
- Multi-frame videos created with DICOMize can now be sent to a PACS.
- Removed spurious warnings when converting files.

## v2.11.1 — 2026-04-09

Internal change — no release note (release workflow consolidation).

## v2.11.0 — 2026-04-09

### New — [#101](https://github.com/bobvmierlo/PACSAdminTool/pull/101)

- **DICOMize worklist integration** — fill patient and study details directly from a worklist entry when converting files.
- **Multi-frame video DICOM** — videos are converted into true multi-frame DICOM objects.

### Improved — [#101](https://github.com/bobvmierlo/PACSAdminTool/pull/101)

- The Structured Report viewer gains an About card, an SR type reference table, and a more prominent document title.

## v2.10.1 — 2026-04-09

Internal change — no release note (version bump only).

## v2.10 — 2026-04-09

### New — [#100](https://github.com/bobvmierlo/PACSAdminTool/pull/100)

- **DICOMize** — convert PDFs, images, and videos into DICOM files, ready to send to a PACS.
- **Structured Report viewer** — view DICOM Structured Reports as a readable tree.

### Improved — [#100](https://github.com/bobvmierlo/PACSAdminTool/pull/100)

- Tabs are arranged in a more logical order, and the Help tab covers the new features.

## v2.9.5 — 2026-04-08

Internal change — no release note (statistics workflows and dependency updates).

## v2.9.4 — 2026-04-06

Internal change — no release note (telemetry logging).

## v2.9.3 — 2026-04-06

Internal change — no release note (telemetry fix).

## v2.9.2 — 2026-04-06

Internal change — no release note (telemetry fix).

## v2.9.1 — 2026-04-06

Internal change — no release note (version bump only).

## v2.9.0 — 2026-04-06

### New — [#92](https://github.com/bobvmierlo/PACSAdminTool/pull/92)

- **Anonymous usage statistics** — the app now collects anonymous usage telemetry (hosted in the EU) to help guide development; it can be turned off in Settings.

## v2.8.0 — 2026-04-05

### Improved — [#91](https://github.com/bobvmierlo/PACSAdminTool/pull/91)

- **Complete translations** — added missing Dutch translations for the offline overlay, update dialogs, Logs tab, and tag editor.

## v2.7.7 — 2026-04-05

### Improved — [#90](https://github.com/bobvmierlo/PACSAdminTool/pull/90)

- Tabs are reordered into a more logical workflow sequence.

## v2.7.6 — 2026-04-04

### Fixed — [#89](https://github.com/bobvmierlo/PACSAdminTool/pull/89)

- The update-install overlay no longer reloads the page before the update has actually finished.

## v2.7.5.1 — 2026-04-04

Internal change — no release note (build workflow tweak).

## v2.7.5 — 2026-04-04

### Improved — [#88](https://github.com/bobvmierlo/PACSAdminTool/pull/88)

- **Smarter update notifications** — update messages now match how you run the app (Windows exe, Docker, or from source), with the right instructions for each.

## v2.7.4 — 2026-04-04

Internal change — no release note (version bump only).

## v2.7.3 — 2026-04-04

### Fixed — [#87](https://github.com/bobvmierlo/PACSAdminTool/pull/87)

- After installing an update, the page now reloads automatically once the app has restarted.

## v2.7.2.1 — 2026-04-04

Internal change — no release note (version bump only).

## v2.7.2 — 2026-04-04

### Fixed — [#86](https://github.com/bobvmierlo/PACSAdminTool/pull/86)

- Auto-update now works on Windows — the updater no longer trips over the running program file.

## v2.7.1 — 2026-04-04

### New — [#85](https://github.com/bobvmierlo/PACSAdminTool/pull/85)

- **Check for updates button** — manually check for a new version from the About tab.

### Fixed — [#85](https://github.com/bobvmierlo/PACSAdminTool/pull/85)

- The update checker now understands four-part version numbers.

## v2.7.0.1 — 2026-04-04

Internal change — no release note (version bump only).

## v2.7.0 — 2026-04-04

### New — [#84](https://github.com/bobvmierlo/PACSAdminTool/pull/84)

- **Update checker** — the app now checks for new releases and shows an in-app notification with one-click auto-update.

## v2.6.0 — 2026-04-04

### New — [#73](https://github.com/bobvmierlo/PACSAdminTool/pull/73)

- **Built-in DICOM image viewer** — view received series as a scrollable image stack directly in the browser.

### Fixed — [#73](https://github.com/bobvmierlo/PACSAdminTool/pull/73)

- Images in a series are now ordered by instance number instead of file date.

### Fixed — [#74](https://github.com/bobvmierlo/PACSAdminTool/pull/74)

- The received-studies list no longer intermittently fails to load.
- MRI images are no longer rejected by the DICOM receiver due to their transfer syntax.

### Fixed — [#75](https://github.com/bobvmierlo/PACSAdminTool/pull/75)

- Compressed DICOM images (e.g. JPEG-compressed) now display correctly in the viewer.

### New — [#76](https://github.com/bobvmierlo/PACSAdminTool/pull/76)

- **Log level filter** — filter the Logs tab by severity.

### Fixed — [#77](https://github.com/bobvmierlo/PACSAdminTool/pull/77)

- A single unreadable file no longer breaks the received-studies list; errors are now shown clearly.

### Fixed — [#78](https://github.com/bobvmierlo/PACSAdminTool/pull/78)

- Fixed a server error that could occur when loading DICOM data.

### New — [#81](https://github.com/bobvmierlo/PACSAdminTool/pull/81)

- **Measure tool and window/level presets** — measure distances and apply common window/level presets in the image viewer.

### New — [#83](https://github.com/bobvmierlo/PACSAdminTool/pull/83)

- **Remembered tab** — the app reopens on the tab you last used.

## v2.5.2 — 2026-04-04

### New — [#71](https://github.com/bobvmierlo/PACSAdminTool/pull/71)

- **Mobile-friendly layout** — the interface now adapts to phones and tablets, with a hamburger navigation menu.

### Fixed — [#72](https://github.com/bobvmierlo/PACSAdminTool/pull/72)

- Image viewer scaling and anonymizer profile layout issues on smaller screens.

## v2.5.1 — 2026-04-03

Internal change — no release note (version bump only).

## v2.5.0 — 2026-04-03

### New — [#67](https://github.com/bobvmierlo/PACSAdminTool/pull/67)

- **DICOM tag editor** — edit tags in the Inspector, then download the modified file or send it straight to a PACS.
- **Image preview for received files** — preview received DICOM images without leaving the receiver tab.
- **Custom anonymization profiles** — create and manage your own tag profiles alongside the built-in Basic and Full profiles.
- **Anonymize & Send** — anonymize files and send them to a remote system in one step.

### Improved — [#68](https://github.com/bobvmierlo/PACSAdminTool/pull/68)

- The image preview dialog is larger, shows patient/modality/date details, and gains brightness and contrast sliders.
- The anonymizer profile editor was overhauled — copy tags from an existing profile in one click.

### New — [#69](https://github.com/bobvmierlo/PACSAdminTool/pull/69)

- **Multi-frame stack viewer** — browse received studies as a study/series tree and scroll through multi-frame images.

## v2.4.1 — 2026-04-03

### New — [#66](https://github.com/bobvmierlo/PACSAdminTool/pull/66)

- **Connection-lost overlay** — the app clearly shows when the connection to the server is lost and recovers automatically.

### Fixed — [#66](https://github.com/bobvmierlo/PACSAdminTool/pull/66)

- The interactive API documentation page loads correctly again.

## v2.4.0 — 2026-04-02

### New — [#60](https://github.com/bobvmierlo/PACSAdminTool/pull/60)

- **Interactive API documentation** — the web API is now documented with a browsable OpenAPI (Swagger) page.

## v2.3.1 — 2026-04-02

### Improved — [#58](https://github.com/bobvmierlo/PACSAdminTool/pull/58)

- **Docker Hub availability** — Docker images are now published to Docker Hub in addition to GitHub Container Registry.

## v2.3.0 — 2026-04-01

### New — [#54](https://github.com/bobvmierlo/PACSAdminTool/pull/54)

- **Automatic cleanup of received files** — received DICOM files older than 24 hours are deleted automatically for privacy/GDPR hygiene.
- **Inspect and Delete for received files** — inspect or remove individual files directly from the DICOM Receiver files table.

## v2.2.0 — 2026-04-01

### New — [#47](https://github.com/bobvmierlo/PACSAdminTool/pull/47)

- **Dashboard** — an at-a-glance overview of configured systems and activity.
- **C-GET retrieval** — retrieve studies using C-GET in addition to C-MOVE.
- **Bulk C-FIND** — run queries for many patients or studies in one go.
- **DICOM inspector** — browse the full tag contents of any DICOM file.
- **Anonymizer** — strip patient-identifying data from DICOM files.
- **Receiver statistics** — see counts and volumes for received studies.

### New — [#51](https://github.com/bobvmierlo/PACSAdminTool/pull/51)

- **DICOMDIR generator** — upload files or a folder and download a ZIP with a generated DICOMDIR.

### Fixed — [#48](https://github.com/bobvmierlo/PACSAdminTool/pull/48)

- Storage commitment confirmations from remote systems are no longer rejected by the receiver.

### Improved — [#49](https://github.com/bobvmierlo/PACSAdminTool/pull/49)

- Storage commitment results now appear in the commitment activity log.

### Fixed — [#50](https://github.com/bobvmierlo/PACSAdminTool/pull/50)

- Storage commitment responses are now read reliably regardless of how the remote system formats them.

## v2.1.0 — 2026-03-31

### New — [#46](https://github.com/bobvmierlo/PACSAdminTool/pull/46)

- **Log viewer** — view application logs live from a new tab in the web UI.

## v2.0.1 — 2026-03-31

### Improved — [#37](https://github.com/bobvmierlo/PACSAdminTool/pull/37)

- Nested sequence tags in the tag detail popup are now collapsible, making large files easier to read.

## v2.0 — 2026-03-31

### New — [#36](https://github.com/bobvmierlo/PACSAdminTool/pull/36)

- **User accounts and login** — the web interface is now protected by a login, with user management for administrators.
- **Audit log** — user actions are recorded for accountability.
- **AE connection test** — test connectivity to a configured system with one button.
- **C-FIND CSV export and query history** — export query results to CSV and revisit recent queries.
- **Received files list** — see the files stored by the DICOM receiver.

### Improved — [#36](https://github.com/bobvmierlo/PACSAdminTool/pull/36)

- Security hardening of the web interface with stricter browser security headers.
