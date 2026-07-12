# Changelog

## Unreleased

### Fixed + New

Fix several reliability issues: outgoing DICOM connections now time out instead of hanging indefinitely when a remote peer becomes unresponsive, SCP auto-purge now correctly removes files stored in Study/Series subdirectories (previously only top-level files were cleaned), and DICOM tag comparisons now detect changes inside nested sequences. Harden security: the login screen now blocks repeated failed attempts for 60 seconds after 5 failures within 15 minutes, session cookies gain HttpOnly/SameSite/Secure flags with a 12-hour expiry, and HTTPS support is now available via `--cert`/`--key` flags in the web interface. The Anonymizer gains two new options — remove private tags and regenerate Study/Series/Instance UIDs — and now warns when exported files likely contain burned-in patient information.
