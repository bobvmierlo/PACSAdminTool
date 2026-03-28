"""
Configuration management for PACS Admin Tool.
Stores and loads AE configurations, presets, and settings.
"""

import json
import logging
import os
import stat
import tempfile

logger = logging.getLogger(__name__)


APP_DIR = os.path.join(os.path.expanduser("~"), ".pacs_admin_tool")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_DIR = os.path.join(APP_DIR, "logs")

DEFAULT_CONFIG = {
    "local_ae": {
        "ae_title": "PACSADMIN",
        "port": 11112
    },
    "remote_aes": [],
    "hl7": {
        "listen_port": 2575,
        "default_host": "127.0.0.1",
        "default_port": 2575
    },
    "query_defaults": {
        "query_level": "STUDY",
        "date_range": ""
    },
    "web": {
        "host": "127.0.0.1",
        "port": 5000
    },
    "log_level": "INFO",
    "language": "en"
}


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge *override* into a copy of *base*.
    - Dict values are merged recursively so nested keys added to DEFAULT_CONFIG
      in later versions are picked up even when the saved config pre-dates them.
    - Non-dict values in *override* replace those in *base*.
    - Keys present only in *base* (new defaults) are preserved.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                loaded = json.load(f)
            # Deep-merge: new default keys are picked up even for nested dicts.
            return _deep_merge(DEFAULT_CONFIG, loaded)
        except Exception:
            logger.warning(
                "Could not load config from %s (corrupt or unreadable); "
                "falling back to defaults.",
                CONFIG_PATH,
                exc_info=True,
            )
    return _deep_merge(DEFAULT_CONFIG, {})


def save_config(config: dict):
    config_dir = os.path.dirname(CONFIG_PATH)
    os.makedirs(config_dir, exist_ok=True)
    # Write to a temp file in the same directory, then atomically replace.
    # This prevents a half-written config if the process crashes mid-write.
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        # Restrict permissions to owner-only (rw-------) so that credentials
        # stored in the config (e.g. future TLS keys, passwords) are not readable
        # by other users on the same system.  No-op on Windows.
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(tmp_path, CONFIG_PATH)
    except BaseException:
        # Clean up the temp file if anything goes wrong
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_remote_ae(config: dict, name: str) -> dict | None:
    for ae in config.get("remote_aes", []):
        if ae.get("name") == name:
            return ae
    return None
