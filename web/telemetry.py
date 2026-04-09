"""
Usage telemetry for PACS Admin Tool.

Sends anonymous, privacy-safe usage data to PostHog (EU servers).

What is collected
-----------------
  - A random anonymous installation UUID (not tied to any user or machine)
  - App version, deployment type (docker/exe/source), OS platform
  - Interface language
  - Which features are used (C-FIND, C-MOVE, HL7 send, SCP start, …)

What is NOT collected
---------------------
  - IP addresses  (PostHog may derive country from the request IP and then
    discards it – we never store it ourselves)
  - AE titles, hostnames, or any PACS/HL7 endpoint data
  - Patient data of any kind
  - Usernames or passwords

Opt-out
-------
Users can disable telemetry at any time via Settings → Telemetry.
The preference is stored in config.json under `telemetry.enabled`.

PostHog configuration
---------------------
Set the project API key in the POSTHOG_API_KEY environment variable, or
replace the placeholder constant _POSTHOG_API_KEY below with the key from
your PostHog project settings (Project settings → Project API key).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import uuid

import web.context as ctx

logger = logging.getLogger(__name__)

# ── PostHog project settings ─────────────────────────────────────────────────
# Replace the placeholder with your PostHog EU project API key, or set the
# POSTHOG_API_KEY environment variable (preferred for Docker deployments).
_POSTHOG_API_KEY = os.environ.get(
    "POSTHOG_API_KEY",
    "phc_REPLACE_WITH_YOUR_POSTHOG_PROJECT_API_KEY",
)
_POSTHOG_HOST = "https://eu.i.posthog.com"

# ── Module-level state ───────────────────────────────────────────────────────
_client         = None   # posthog.Posthog instance, set by init()
_anonymous_id: str | None = None
_enabled        = True
_lock           = threading.Lock()


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get_deployment() -> str:
    """Return 'exe', 'docker', or 'source'."""
    if getattr(sys, "frozen", False):
        return "exe"
    if os.path.exists("/.dockerenv") or os.environ.get("PACS_DATA_DIR") == "/data":
        return "docker"
    return "source"


def _get_platform() -> str:
    """Return a simplified OS identifier."""
    p = sys.platform
    if p == "win32":
        return "windows"
    if p == "darwin":
        return "macos"
    return "linux"


# ── Public API ────────────────────────────────────────────────────────────────

def init(config: dict) -> None:
    """
    Initialise (or re-initialise) telemetry from the current config dict.

    Called once at server start and again whenever the user saves settings
    that include a telemetry change.
    """
    global _client, _anonymous_id, _enabled

    with _lock:
        tel      = config.get("telemetry", {})
        _enabled = bool(tel.get("enabled", True))
        anon_id  = tel.get("anonymous_id") or ""

        # Generate a stable anonymous ID on first run and persist it.
        if not anon_id:
            anon_id = str(uuid.uuid4())
            config.setdefault("telemetry", {})["anonymous_id"] = anon_id
            try:
                from config.manager import save_config
                save_config(config)
            except Exception:
                pass  # non-fatal; will be regenerated on next start

        _anonymous_id = anon_id

        placeholder = "phc_REPLACE"
        key_is_placeholder = _POSTHOG_API_KEY.startswith(placeholder)

        try:
            from posthog import Posthog
            # disable_geoip=False lets PostHog derive the country from the
            # server IP, which is the correct location for a self-hosted tool.
            # Pass the API key positionally — the kwarg was renamed from
            # `api_key` to `project_api_key` in posthog SDK v3+.
            _client = Posthog(
                _POSTHOG_API_KEY,
                host=_POSTHOG_HOST,
                disable_geoip=False,
                disabled=not _enabled or key_is_placeholder,
            )
            logger.debug(
                "Telemetry initialised (enabled=%s, key_ok=%s, id=%s…)",
                _enabled, not key_is_placeholder, anon_id[:8],
            )
            if key_is_placeholder:
                logger.debug("Telemetry disabled: API key is still the placeholder.")
            elif not _enabled:
                logger.debug("Telemetry disabled: user opted out.")
        except ImportError:
            logger.debug("posthog package not installed; telemetry disabled.")
            _client = None
        except Exception as exc:
            logger.debug("Telemetry init error: %s", exc)
            _client = None


def capture(event: str, properties: dict | None = None) -> None:
    """
    Capture a named telemetry event.  No-op when telemetry is disabled,
    the posthog package is not installed, or init() has not been called yet.
    """
    if not _enabled or _client is None or not _anonymous_id:
        logger.debug(
            "Telemetry event skipped (%s): enabled=%s, client=%s",
            event, _enabled, _client is not None,
        )
        return
    try:
        # posthog ≥7.x swapped the argument order:
        #   old (≤6.x):  capture(distinct_id, event, properties)
        #   new (≥7.x):  capture(event, distinct_id=..., properties=...)
        _client.capture(event, distinct_id=_anonymous_id, properties=properties or {})
        logger.debug(
            "Telemetry event sent: %s | props: %s",
            event,
            {k: v for k, v in (properties or {}).items() if not k.startswith("$")},
        )
    except Exception as exc:
        logger.debug("Telemetry capture error (%s): %s", event, exc)


def send_startup() -> None:
    """
    Send the `app_startup` event in a background thread.

    Uses `$set` so that PostHog updates the Person properties for this
    anonymous ID every time the app starts, giving you the current version
    and deployment type without duplicating events.
    """
    def _send():
        from __version__ import __version__
        deployment = _get_deployment()
        platform   = _get_platform()
        language   = ctx.config.get("language", "en")
        logger.debug(
            "Telemetry: sending app_startup (version=%s, deployment=%s, platform=%s)",
            __version__, deployment, platform,
        )
        capture("app_startup", {
            "$set": {
                "app_version":     __version__,
                "deployment_type": deployment,
                "os_platform":     platform,
                "language":        language,
            },
            # Also as event properties for funnel / trend queries:
            "app_version":     __version__,
            "deployment_type": deployment,
            "os_platform":     platform,
            "language":        language,
        })

    threading.Thread(target=_send, daemon=True, name="telemetry-startup").start()
