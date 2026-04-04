"""
Update checker and auto-updater for PACS Admin Tool.

Queries the GitHub Releases API to detect newer versions.
When running as a frozen PyInstaller executable it can also download the new
binary, stage it, and perform an in-place replacement + restart.

Public API
----------
check_for_update(force=False) -> dict
    Returns cached update info (re-fetched after 1 hour or when force=True).

get_update_state() -> dict
    Returns the current download / staging state.

apply_update_async(download_url, on_ready=None)
    Starts a background thread that downloads the new executable.
    Calls on_ready() when staging is complete.

apply_update_and_restart()
    Replaces the current executable with the staged one and restarts.
    On Windows a detached batch script handles the swap after we exit.
    On Unix/Linux the replacement happens in-place and os.execv() restarts.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_REPO        = "bobvmierlo/PACSAdminTool"
_API_URL           = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

# Filenames attached to GitHub releases by the build workflow
_ASSET_GUI = "PacsAdminTool.exe"
_ASSET_WEB = "PacsAdminToolWeb.exe"

# How long (seconds) to cache the result before hitting GitHub again
_CACHE_TTL = 3600

_cache_lock      = threading.Lock()
_cache_result: dict | None = None
_cache_timestamp: float    = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _current_version() -> str:
    from __version__ import __version__
    return __version__


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _parse_semver(v: str) -> tuple:
    """'v2.7.1' → (2, 7, 1).  Returns (0,0,0) on parse error."""
    v = v.lstrip("v").strip()
    try:
        parts = [int(x) for x in v.split(".")]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _detect_asset_name() -> str | None:
    """Return the GitHub release asset filename that matches this executable."""
    if not _is_frozen():
        return None
    exe = os.path.basename(sys.executable).lower()
    if "web" in exe:
        return _ASSET_WEB
    return _ASSET_GUI


def _fetch_latest_release() -> dict:
    """Hit the GitHub API and return the raw release JSON (or raise)."""
    current = _current_version()
    req = Request(
        _API_URL,
        headers={
            "Accept":               "application/vnd.github+json",
            "User-Agent":           f"PacsAdminTool/{current}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


# ─────────────────────────────────────────────────────────────────────────────
# Public: version check
# ─────────────────────────────────────────────────────────────────────────────

def check_for_update(force: bool = False) -> dict:
    """
    Return a dict describing the latest GitHub release vs. the current version.

    Keys
    ----
    current_version  str   – the version this build carries
    latest_version   str   – latest tag from GitHub (same as current on error)
    has_update       bool  – True when latest > current
    release_url      str   – HTML URL of the release page
    download_url     str|None – direct asset download URL (frozen exe only)
    release_notes    str   – first 500 chars of the release body
    can_auto_update  bool  – True when we can download + swap the exe
    error            str|None – short error token on failure, else None
    """
    global _cache_result, _cache_timestamp

    with _cache_lock:
        now = time.monotonic()
        if not force and _cache_result is not None and (now - _cache_timestamp) < _CACHE_TTL:
            return _cache_result

        result = _build_update_info()
        _cache_result    = result
        _cache_timestamp = now
        return result


def _build_update_info() -> dict:
    current = _current_version()
    base = {
        "current_version": current,
        "latest_version":  current,
        "has_update":      False,
        "release_url":     GITHUB_RELEASE_URL,
        "download_url":    None,
        "release_notes":   "",
        "can_auto_update": False,
        "error":           None,
    }
    try:
        data = _fetch_latest_release()
    except URLError as exc:
        logger.debug("Update check – network error: %s", exc)
        return {**base, "error": "network"}
    except Exception as exc:
        logger.debug("Update check – unexpected error: %s", exc)
        return {**base, "error": str(exc)}

    tag         = data.get("tag_name", "")
    latest      = tag.lstrip("v").strip() or current
    release_url = data.get("html_url", GITHUB_RELEASE_URL)
    notes       = (data.get("body") or "").strip()

    # Try to find the right asset download URL
    asset_name   = _detect_asset_name()
    download_url = None
    if asset_name:
        for asset in data.get("assets", []):
            if asset.get("name", "").lower() == asset_name.lower():
                download_url = asset.get("browser_download_url")
                break

    has_update      = _parse_semver(latest) > _parse_semver(current)
    can_auto_update = has_update and _is_frozen() and download_url is not None

    return {
        "current_version": current,
        "latest_version":  latest,
        "has_update":      has_update,
        "release_url":     release_url,
        "download_url":    download_url,
        "release_notes":   notes[:500],
        "can_auto_update": can_auto_update,
        "error":           None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public: auto-update
# ─────────────────────────────────────────────────────────────────────────────

_update_state: dict = {
    "status":      "idle",   # idle | downloading | ready | error
    "progress":    0,
    "staged_path": None,
    "error":       None,
}
_update_state_lock = threading.Lock()


def get_update_state() -> dict:
    with _update_state_lock:
        return dict(_update_state)


def _set_update_state(**kwargs) -> None:
    with _update_state_lock:
        _update_state.update(kwargs)


def apply_update_async(download_url: str, on_ready=None) -> None:
    """
    Kick off a background download of the new executable.
    ``on_ready`` is called (no arguments) once the file is fully staged.
    Raises RuntimeError when not running as a frozen executable.
    """
    if not _is_frozen():
        raise RuntimeError("Auto-update is only supported for frozen (PyInstaller) executables.")

    state = get_update_state()
    if state["status"] in ("downloading", "ready"):
        logger.info("Update already in progress/staged – skipping duplicate request.")
        return

    _set_update_state(status="downloading", progress=0, staged_path=None, error=None)
    threading.Thread(
        target=_download_worker,
        args=(download_url, on_ready),
        daemon=True,
        name="pacs-update-dl",
    ).start()


def _download_worker(download_url: str, on_ready) -> None:
    current_exe  = sys.executable
    staged_path  = current_exe + ".update"

    try:
        current = _current_version()
        req = Request(
            download_url,
            headers={"User-Agent": f"PacsAdminTool/{current}"},
        )
        with urlopen(req, timeout=120) as resp:
            total      = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(staged_path, "wb") as fout:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fout.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        _set_update_state(progress=int(downloaded * 100 / total))

        _set_update_state(status="ready", progress=100, staged_path=staged_path, error=None)
        logger.info("Update staged at: %s", staged_path)
        if on_ready:
            on_ready()

    except Exception as exc:
        logger.error("Update download failed: %s", exc)
        _try_remove(staged_path)
        _set_update_state(status="error", error=str(exc))


def apply_update_and_restart() -> None:
    """
    Replace the running executable with the staged download, then restart.
    This call does NOT return – the process will exit (or exec).
    Raises RuntimeError if no staged update is available.
    """
    state = get_update_state()
    if state["status"] != "ready":
        raise RuntimeError(f"No staged update available (state={state['status']!r}).")

    staged = state.get("staged_path")
    if not staged or not os.path.isfile(staged):
        raise RuntimeError("Staged update file is missing.")

    current_exe = sys.executable
    logger.info("Applying update: %s → %s", staged, current_exe)

    if sys.platform == "win32":
        _swap_windows(staged, current_exe)
    else:
        _swap_unix(staged, current_exe)


def _swap_windows(staged: str, current_exe: str) -> None:
    """
    On Windows the running .exe is locked, so we write a tiny batch script that:
      1. Waits 2 s for us to exit
      2. Moves (overwrites) the new exe over the old path
      3. Launches the new exe
      4. Deletes itself
    Then we start the script detached and exit.
    """
    script = (
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'move /Y "{staged}" "{current_exe}"\r\n'
        f'start "" "{current_exe}"\r\n'
        'del "%~f0"\r\n'
    )
    batch = os.path.join(tempfile.gettempdir(), "pacs_tool_update.bat")
    with open(batch, "w", encoding="utf-8") as f:
        f.write(script)

    subprocess.Popen(
        ["cmd", "/c", batch],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    time.sleep(0.5)   # let cmd start before we exit
    os._exit(0)


def _swap_unix(staged: str, current_exe: str) -> None:
    """
    On Unix the kernel allows replacing a running binary because open file
    handles refer to the inode, not the path.  We move the new file into place
    and execv() so the OS loads the new image with the same PID chain.
    """
    shutil.move(staged, current_exe)
    os.chmod(current_exe, 0o755)
    logger.info("Restarting with updated executable…")
    os.execv(current_exe, sys.argv)


def _try_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
