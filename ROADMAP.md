# Roadmap

Items identified during the July 2026 code review that are **deliberately deferred**.
The bug fixes and security hardening from that review are already merged; the lists
below are the remaining ideas, roughly in order of value.

## Code improvements

1. **Split `web/static/index.html` (~11,000 lines).** Biggest maintainability
   liability. Split the JS per tab into `web/static/js/*.js` files loaded with
   plain `<script>` tags — no build system needed.
2. **Per-level C-FIND query datasets.** `dicom_find()` always sets study-level
   return keys (`ModalitiesInStudy`, `StudyDescription`, …) even for SERIES/IMAGE
   level queries; at SERIES level the correct key is `Modality`, and strict SCPs
   reject unexpected keys. Build the return-key set per query level, and let the
   user add arbitrary extra return tags in the query builder.
3. **Background job registry.** C-MOVE / C-GET / C-STORE run in fire-and-forget
   threads with results only visible in the SocketIO log stream. Add a small
   in-memory job table (id, state, message, timestamps) plus `/api/jobs/<id>` so
   the UI can show real completion state and survive a page refresh mid-transfer.
4. **Scope SocketIO events to the requesting client.** `_log()` and batch-echo
   results are emitted globally, so concurrent users see each other's operation
   logs. Emit to the submitting client's room instead.
5. **Deduplicate the repeated `save_as(..., enforce_file_format=True)` /
   `except TypeError` fallback** into one helper (appears ~6 times across routes).

## New features

1. **MPPS testing (N-CREATE / N-SET).** The missing piece of the acquisition
   workflow next to DMWL, Storage Commitment, and IOCM — lets admins simulate a
   modality that starts/completes/discontinues a procedure step.
2. **DICOM TLS for SCU/SCP associations.** pynetdicom supports TLS directly;
   increasingly required on hospital networks. (Web-UI HTTPS already exists via
   `webmain.py --cert/--key`.)
3. **Scheduled connectivity monitoring.** Optional background C-ECHO of all AE
   presets every N minutes with a short history, so the Dashboard can show
   uptime/latency trends and flapping links.
4. **CSV export for C-FIND results** (DMWL already has it).
5. **Persisted HL7 message history + configurable ACK.** Persist the last N
   received messages to disk; let the listener return AE/AR for negative-ACK
   testing; echo the incoming message's HL7 version in the ACK instead of the
   hardcoded `2.3`.
6. **Docker `HEALTHCHECK`** hitting `/api/health` in the Dockerfile / compose file.
