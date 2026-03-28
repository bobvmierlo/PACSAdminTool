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
| `TestFormatRawBytes` | 4 | `format_raw_bytes()` renders byte buffers for debug display. Printable ASCII is shown as-is, control bytes are shown as `<0x..>`, carriage returns as `<CR>`, and the optional label prefix is formatted correctly. |

### `test_validation.py` - Web API Input Validation

Tests for the web server's input validation, exercised through Flask's test client. These tests do **not** make real DICOM or HL7 connections.

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestWebValidationHelpers` | 4 | **Health endpoint**: `GET /api/health` returns 200 with `status`, `scp_running`, and `hl7_listener_running` fields. **Missing fields**: `POST /api/dicom/find` and `POST /api/hl7/send` with empty JSON bodies return HTTP 400. **Invalid port**: `POST /api/dicom/find` with `port: "abc"` returns HTTP 400. |

## Test Count Summary

| File | Tests |
|------|-------|
| `test_config.py` | 11 |
| `test_mllp.py` | 12 |
| `test_validation.py` | 4 |
| **Total** | **27** |

## Adding New Tests

When adding tests, follow these conventions:

1. **File naming**: `tests/test_<module>.py`
2. **Class naming**: `Test<Feature>` (e.g., `TestDeepMerge`)
3. **Method naming**: `test_<what_it_checks>` (e.g., `test_nested_merge`)
4. **Imports**: Each test file adds the project root to `sys.path` so modules can be imported directly
5. **No network**: Tests should not depend on external DICOM/HL7 servers. Use Flask's test client for HTTP endpoints and mock/monkeypatch for filesystem operations.

## CI Integration

To run tests in a CI pipeline, add this step:

```bash
pip install -r requirements.txt
pip install pytest
pytest tests/ -v --tb=short
```

The exit code is `0` when all tests pass and non-zero on any failure.
