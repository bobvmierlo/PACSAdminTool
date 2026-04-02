# PACS Admin Tool - Test Suite

This project uses [pytest](https://docs.pytest.org/) for automated testing. The tests live in the `tests/` directory and cover core logic that does **not** require a running DICOM or HL7 server.

## Prerequisites

```bash
pip install pytest
```

All other dependencies are listed in `requirements.txt`.

## Running the Tests

**Run the full suite:**

```bash
pytest tests/
```

**Run with verbose output:**

```bash
pytest tests/ -v
```

**Run a single test file:**

```bash
pytest tests/test_config.py
pytest tests/test_mllp.py
pytest tests/test_validation.py
pytest tests/test_web_api.py
```

**Run a specific test class or method:**

```bash
pytest tests/test_config.py::TestDeepMerge
pytest tests/test_config.py::TestDeepMerge::test_nested_merge
```

## Test Files

### `test_config.py` - Configuration Management

Tests for the config system in `config/manager.py`.

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestDeepMerge` | 8 | The `_deep_merge()` function that recursively merges saved config with defaults. Ensures new default keys are preserved, nested dicts merge correctly, non-dict values override properly, and the base dict is never mutated. |
| `TestSaveConfig` | 3 | Atomic config writes via `save_config()`. Verifies that the saved file contains valid JSON, no temp files are left behind after a write, and overwrites work correctly. Uses `monkeypatch` to redirect `CONFIG_PATH` to a temp directory. |

### `test_mllp.py` - HL7 MLLP Framing

Tests for the MLLP (Minimal Lower Layer Protocol) framing functions in `hl7_module/messaging.py`.

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestWrapMllp` | 3 | `wrap_mllp()` correctly wraps an HL7 message string with the MLLP start byte (`0x0B`) and end bytes (`0x1C 0x0D`). Also tests empty messages. |
| `TestUnwrapMllp` | 5 | `unwrap_mllp()` correctly strips MLLP framing. Tests round-trip fidelity (`unwrap(wrap(msg)) == msg`), partial framing (only start or only end), and no framing at all. |
| `TestFormatRawBytes` | 5 | `format_raw_bytes()` renders byte buffers for debug display. Printable ASCII is shown as-is, control bytes are shown as `<0x..>`, carriage returns as `<CR>`, the optional label prefix is formatted correctly, and output without a label contains only the rendered bytes. |

### `test_validation.py` - Web API Input Validation

Tests for the web server's input validation, exercised through Flask's test client. These tests do **not** make real DICOM or HL7 connections.

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestWebValidationHelpers` | 4 | **Health endpoint**: `GET /api/health` returns 200 with `status`, `scp_running`, and `hl7_listener_running` fields. **Missing fields**: `POST /api/dicom/find` and `POST /api/hl7/send` with empty JSON bodies return HTTP 400. **Invalid port**: `POST /api/dicom/find` with `port: "abc"` returns HTTP 400. |

### `test_web_api.py` - Web API Integration

Full integration tests for the Flask web server using an isolated temporary data directory. Each test gets a fresh user store and config — no state leaks between tests.

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestPublicEndpoints` | 3 | `/api/health` is always public. `/api/version` requires authentication once users exist and returns version/app_dir info when authenticated. |
| `TestSetup` | 4 | `GET /setup` redirects to `/` when users already exist. `POST /setup` creates the first admin and returns 200. Short passwords are rejected with 400. A second setup attempt returns 403. |
| `TestAuth` | 4 | Successful login returns 200 and sets a session. Wrong password returns 401. Logout clears the session (subsequent requests return 401). `GET /api/me` returns the current user's username and role. |
| `TestAuthGuard` | 3 | `/api/config` and `/api/locale/languages` return 401 for unauthenticated clients. `/api/health` remains public regardless of auth state. |
| `TestConfig` | 5 | `GET /api/config` returns the current config dict. `POST /api/config` accepts valid keys (`log_level: DEBUG`). Rejects unknown keys (400), invalid log level values (400), and out-of-range port numbers (400). |
| `TestLocale` | 3 | `/api/locale/languages` returns a list that includes `en`. `/api/locale/current` returns the active language. `/api/translations` returns a dict of translation strings. |
| `TestUserManagement` | 6 | List users, create and delete a user, reject duplicate usernames (409), prevent self-deletion (400), block non-admin users from listing users (403), and allow changing own password. |
| `TestSCPFiles` | 1 | `GET /api/scp/files` returns 200 with an empty `files` list when the SCP receive directory is empty. |

## Test Count Summary

| File | Tests |
|------|-------|
| `test_config.py` | 11 |
| `test_mllp.py` | 13 |
| `test_validation.py` | 4 |
| `test_web_api.py` | 29 |
| **Total** | **57** |

## Adding New Tests

When adding tests, follow these conventions:

1. **File naming**: `tests/test_<module>.py`
2. **Class naming**: `Test<Feature>` (e.g., `TestDeepMerge`)
3. **Method naming**: `test_<what_it_checks>` (e.g., `test_nested_merge`)
4. **Imports**: Each test file adds the project root to `sys.path` so modules can be imported directly
5. **No network**: Tests should not depend on external DICOM/HL7 servers. Use Flask's test client for HTTP endpoints and mock/monkeypatch for filesystem operations.
6. **Isolated data dir**: Tests that touch the web server must set `PACS_DATA_DIR` to a `tmp_path` and reload `config.manager`, `web.auth`, and `web.server` in that order so module-level path constants are re-evaluated against the temp directory.

## CI Integration

To run tests in a CI pipeline, add this step:

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/ -v --tb=short
```

The exit code is `0` when all tests pass and non-zero on any failure.
