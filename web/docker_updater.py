"""
One-click Docker update for PACS Admin Tool.

When the app runs as a Docker Compose service and the host's Docker socket
is mounted into the container (/var/run/docker.sock), an admin can trigger
the equivalent of running on the host:

    docker compose pull && docker compose up -d

A container cannot safely recreate itself, so the update is delegated to a
short-lived helper container (image ``docker:cli``) that has the socket and
the compose project directory mounted. The helper keeps running while this
container is stopped, replaced, and restarted by ``docker compose up -d``.

The compose project name, working directory, and config files are discovered
from the labels Docker Compose stamps on every container it creates, so no
extra configuration is needed beyond mounting the socket.

Public API
----------
get_capability(force=False) -> dict
    Whether a one-click update is possible, and why not if it isn't.

trigger_update_async() -> None
    Launch the helper container in a background thread.

get_update_state() -> dict
    Current state of the trigger: idle | preparing | launched | error.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import socket
import threading
import time

logger = logging.getLogger(__name__)

DOCKER_SOCK  = "/var/run/docker.sock"
HELPER_IMAGE = "docker:cli"
UPDATE_CMD   = "docker compose pull && docker compose up -d"

# Compose stamps these labels on every container it manages.
_LBL_PROJECT     = "com.docker.compose.project"
_LBL_WORKING_DIR = "com.docker.compose.project.working_dir"
_LBL_CONFIG      = "com.docker.compose.project.config_files"


# ─────────────────────────────────────────────────────────────────────────────
# Minimal Docker Engine API client over the unix socket (stdlib only)
# ─────────────────────────────────────────────────────────────────────────────

class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection that talks to a unix domain socket instead of TCP."""

    def __init__(self, sock_path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._sock_path = sock_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._sock_path)
        self.sock = sock


def _api(method: str, path: str, body: dict | None = None,
         timeout: float = 10.0) -> tuple[int, bytes]:
    """One request to the Docker Engine API. Returns (status, raw body)."""
    conn = _UnixHTTPConnection(DOCKER_SOCK, timeout=timeout)
    try:
        headers = {"Host": "docker"}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _api_json(method: str, path: str, body: dict | None = None,
              timeout: float = 10.0) -> tuple[int, dict]:
    status, raw = _api(method, path, body=body, timeout=timeout)
    try:
        return status, json.loads(raw.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return status, {}


# ─────────────────────────────────────────────────────────────────────────────
# Self-identification
# ─────────────────────────────────────────────────────────────────────────────

def _own_container_id() -> str:
    """Best-effort discovery of the ID of the container we are running in."""
    # Docker bind-mounts /etc/{resolv.conf,hostname,hosts} from
    # /var/lib/docker/containers/<id>/…, which shows up in mountinfo even on
    # cgroup v2 hosts where /proc/self/cgroup is unhelpful.
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"/containers/([0-9a-f]{64})/", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    # cgroup v1: paths like /docker/<id> or docker-<id>.scope
    try:
        with open("/proc/self/cgroup", "r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"(?:/docker/|docker-)([0-9a-f]{64})", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    # Fallback: the default container hostname is the short container ID,
    # which the Docker API accepts as an ID prefix.
    return socket.gethostname()


# ─────────────────────────────────────────────────────────────────────────────
# Capability detection (cached — labels cannot change while we're running)
# ─────────────────────────────────────────────────────────────────────────────

_cap_lock  = threading.Lock()
_cap_cache: dict | None = None


def get_capability(force: bool = False) -> dict:
    """
    Return whether a one-click compose update can be triggered.

    Keys
    ----
    available    bool  – True when everything needed is in place
    reason       str   – "socket_not_mounted" | "inspect_failed" | "not_compose"
                         (only when available is False)
    project      str   – compose project name         (when available)
    working_dir  str   – host path of the compose dir (when available)
    config_files str   – comma-separated compose file host paths (may be "")
    """
    global _cap_cache
    with _cap_lock:
        if _cap_cache is not None and not force:
            return _cap_cache
        _cap_cache = _detect_capability()
        return _cap_cache


def _detect_capability() -> dict:
    if not os.path.exists(DOCKER_SOCK):
        return {"available": False, "reason": "socket_not_mounted"}

    container_id = _own_container_id()
    try:
        status, data = _api_json("GET", f"/containers/{container_id}/json")
    except OSError as exc:
        logger.debug("Docker socket not usable: %s", exc)
        return {"available": False, "reason": "inspect_failed"}
    if status != 200:
        logger.debug("Self-inspect returned HTTP %s", status)
        return {"available": False, "reason": "inspect_failed"}

    labels      = (data.get("Config") or {}).get("Labels") or {}
    project     = labels.get(_LBL_PROJECT, "")
    working_dir = labels.get(_LBL_WORKING_DIR, "")
    if not project or not working_dir:
        # Started with plain `docker run` — compose can't manage it.
        return {"available": False, "reason": "not_compose"}

    return {
        "available":    True,
        "project":      project,
        "working_dir":  working_dir,
        "config_files": labels.get(_LBL_CONFIG, ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Update trigger
# ─────────────────────────────────────────────────────────────────────────────

_state_lock = threading.Lock()
_state: dict = {
    "status": "idle",    # idle | preparing | launched | error
    "error":  None,
}


def get_update_state() -> dict:
    with _state_lock:
        return dict(_state)


def _set_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


def trigger_update_async() -> None:
    """
    Launch the compose-update helper container in a background thread.
    Raises RuntimeError when the capability check fails or a trigger is
    already in flight.
    """
    cap = get_capability()
    if not cap.get("available"):
        raise RuntimeError(f"Docker update not available ({cap.get('reason')}).")

    with _state_lock:
        if _state["status"] in ("preparing", "launched"):
            raise RuntimeError("A Docker update is already in progress.")
        _state.update(status="preparing", error=None)

    threading.Thread(
        target=_trigger_worker,
        args=(cap,),
        daemon=True,
        name="pacs-docker-update",
    ).start()


def _trigger_worker(cap: dict) -> None:
    try:
        _ensure_helper_image()
        helper_id = _launch_helper(cap)
        logger.info("Docker update helper launched: %s", helper_id[:12])
        _set_state(status="launched", error=None)
    except Exception as exc:
        logger.error("Docker update trigger failed: %s", exc)
        _set_state(status="error", error=str(exc))


def _ensure_helper_image() -> None:
    """Pull the docker:cli helper image unless it is already present."""
    status, _ = _api_json("GET", f"/images/{HELPER_IMAGE}/json")
    if status == 200:
        return
    # Streamed pull — the request completes only when the pull is done.
    image, tag = HELPER_IMAGE.split(":", 1)
    status, raw = _api(
        "POST", f"/images/create?fromImage={image}&tag={tag}", timeout=600,
    )
    if status != 200:
        raise RuntimeError(f"Could not pull helper image {HELPER_IMAGE} (HTTP {status}).")
    # The pull stream reports errors in-band with HTTP 200.
    tail = raw[-2048:].decode(errors="replace")
    if '"error"' in tail:
        raise RuntimeError(f"Helper image pull failed: {tail.strip().splitlines()[-1]}")


def _launch_helper(cap: dict) -> str:
    """Create and start the one-shot helper container. Returns its ID."""
    working_dir  = cap["working_dir"]
    config_files = [p for p in cap.get("config_files", "").split(",") if p]

    binds = [
        f"{DOCKER_SOCK}:{DOCKER_SOCK}",
        f"{working_dir}:{working_dir}",
    ]
    # Compose files may live outside the project directory (e.g. -f overrides);
    # mount their parent dirs at identical paths so the helper can read them.
    for cf in config_files:
        parent = os.path.dirname(cf)
        if parent and parent != working_dir and not parent.startswith(working_dir + os.sep):
            bind = f"{parent}:{parent}"
            if bind not in binds:
                binds.append(bind)

    env = [f"COMPOSE_PROJECT_NAME={cap['project']}"]
    if config_files:
        env.append("COMPOSE_FILE=" + os.pathsep.join(config_files))

    body = {
        "Image":      HELPER_IMAGE,
        "Cmd":        ["sh", "-c", UPDATE_CMD],
        "WorkingDir": working_dir,
        "Env":        env,
        "Labels":     {"pacsadmintool.helper": "compose-update"},
        "HostConfig": {
            "Binds":      binds,
            "AutoRemove": True,
        },
    }
    name = f"pacsadmintool-updater-{int(time.time())}"
    status, data = _api_json("POST", f"/containers/create?name={name}",
                             body=body, timeout=30)
    if status != 201:
        raise RuntimeError(
            f"Could not create update helper (HTTP {status}): {data.get('message', '')}"
        )
    helper_id = data["Id"]

    status, data = _api_json("POST", f"/containers/{helper_id}/start", timeout=30)
    if status != 204:
        raise RuntimeError(
            f"Could not start update helper (HTTP {status}): {data.get('message', '')}"
        )
    return helper_id
