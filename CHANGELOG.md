# Changelog

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
