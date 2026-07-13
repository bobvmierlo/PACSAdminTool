# Roadmap

Items identified during the July 2026 code review that are **deliberately deferred**.
The bug fixes and security hardening from that review are already merged; the lists
below are the remaining ideas, roughly in order of value.

## Code improvements

1. ~~**Split `web/static/index.html` (~11,000 lines).**~~ ✅ Done — the inline
   script is now 30 per-domain files under `web/static/js/`, loaded in order as
   plain scripts (shared global scope, `init.js` last). `index.html` keeps only
   the markup and CSS.
2. ~~**Per-level C-FIND query datasets.**~~ ✅ Done — `dicom_find()` builds the
   return-key set per query level (PATIENT/STUDY/SERIES/IMAGE, e.g. `Modality`
   instead of `ModalitiesInStudy` at SERIES level), and the query builder has
   an "Extra Return Tags" field accepting keywords or `(gggg,eeee)` tags.
3. ~~**Background job registry.**~~ ✅ Done — `web/jobs.py` in-memory job table
   plus `/api/jobs/<id>`; C-MOVE / C-GET / C-STORE return a `job_id` and the UI
   polls it (persisted in localStorage) so completion state survives a page
   refresh mid-transfer.
4. ~~**Scope SocketIO events to the requesting client.**~~ ✅ Done — each
   browser gets a private Socket.IO room (session cookie); operation logs and
   batch-echo results are emitted to the submitting client's room only.
   Listener-driven events (SCP receiver, HL7 inbound) remain broadcast.
5. ~~**Deduplicate the `save_as` / `except TypeError` fallback.**~~ ✅ Done —
   one `dicom.save_dataset()` helper replaces all repeated fallbacks.

## New features

1. **MPPS testing (N-CREATE / N-SET).** The missing piece of the acquisition
   workflow next to DMWL, Storage Commitment, and IOCM — lets admins simulate a
   modality that starts/completes/discontinues a procedure step.
2. ~~**DICOM TLS for SCU/SCP associations.**~~ ✅ Done — global `dicom_tls`
   config (enabled / cert / key / CA paths, Settings → DICOM TLS card) applied
   to every SCU association and the Storage SCP listener.
3. **Scheduled connectivity monitoring.** Optional background C-ECHO of all AE
   presets every N minutes with a short history, so the Dashboard can show
   uptime/latency trends and flapping links.
4. ~~**CSV export for C-FIND results**~~ ✅ Done — Export CSV button on the
   C-FIND results table (was already implemented; roadmap entry was stale).
5. ~~**Persisted HL7 message history + configurable ACK.**~~ ✅ Done — the last
   200 received messages are persisted to disk (`hl7_history.json`, served via
   `/api/hl7/history`); the listener can return AE/AR for negative-ACK testing
   (ACK Response dropdown); the ACK echoes the incoming message's HL7 version.
6. ~~**Docker `HEALTHCHECK`**~~ ✅ Done — `HEALTHCHECK` hitting `/api/health`
   in the Dockerfile, mirrored in `docker-compose.yml`.
