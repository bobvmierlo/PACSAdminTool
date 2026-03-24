# Locales — Adding a New Language

This directory contains the translation files for the PACS Admin Tool.

## Structure

- `en.json` — English (default / fallback)
- `nl.json` — Dutch (Nederlands)
- `__init__.py` — i18n module (`t()`, `set_language()`, etc.)

## Adding a new language

1. Copy `en.json` to `<code>.json` (e.g. `de.json` for German).
2. Update the `_meta` section:
   ```json
   "_meta": {
     "language_name": "Deutsch",
     "code": "de",
     "direction": "ltr"
   }
   ```
3. Translate all string values. Keep the JSON keys and `{placeholder}` tokens unchanged.
4. Drop the file in this directory — it will be discovered automatically by both the desktop and web UIs.

## Key format

Keys use dot-notation sections:

| Section | Description |
|---------|-------------|
| `app.*` | Application title, subtitle, version |
| `tabs.*` | Tab labels |
| `common.*` | Shared labels (Preset, Host, Port, etc.) |
| `cfind.*` | C-FIND / Query-Retrieve tab |
| `cstore.*` | C-STORE tab |
| `dmwl.*` | Worklist (DMWL) tab |
| `commit.*` | Storage Commitment tab |
| `iocm.*` | IOCM tab |
| `hl7.*` | HL7 send/receive tab |
| `scp.*` | DICOM Receiver tab |
| `settings.*` | Settings tab |
| `help.*` | Help tab |
| `about.*` | About tab |
| `dicom_detail.*` | DICOM tag detail dialog |

## Placeholders

Some strings contain `{name}` placeholders that are substituted at runtime:

- `{n}` — a count (e.g. `"{n} files queued"`)
- `{version}` — app version
- `{port}` — port number
- `{ae_title}` — AE title
- `{ts}` — timestamp
- `{pname}`, `{pid}` — patient name / ID

Do not translate or remove these placeholders.

## Web vs Desktop variants

Some keys have a `_web` suffix (e.g. `cfind.results` vs `cfind.results_web`). The `_web` variant is used by the browser UI, while the base key is used by the desktop (Tkinter) UI. Make sure to translate both.
