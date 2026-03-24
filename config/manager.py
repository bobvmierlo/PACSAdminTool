"""
Configuration management for PACS Admin Tool.
Stores and loads AE configurations, presets, and settings.
"""

import json
import os


CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".pacs_admin_tool", "config.json")

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
    "log_level": "INFO",
    "language": "en"
}


def load_config() -> dict:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                loaded = json.load(f)
            # Merge with defaults to handle new keys
            merged = {**DEFAULT_CONFIG, **loaded}
            return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_remote_ae(config: dict, name: str) -> dict | None:
    for ae in config.get("remote_aes", []):
        if ae.get("name") == name:
            return ae
    return None
