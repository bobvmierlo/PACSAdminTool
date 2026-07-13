"""In-memory background-job registry for C-MOVE / C-GET / C-STORE.

These operations run in fire-and-forget threads with progress previously
visible only through the SocketIO log stream. This registry lets the UI poll
``/api/jobs/<id>`` for the real completion state, so it survives a page
refresh mid-transfer or a dropped WebSocket connection.

Jobs are process-local and not persisted to disk — a server restart clears
them, which is fine since the underlying transfer thread would be gone too.
"""

import threading
import time
import uuid
from datetime import datetime, timezone

_lock = threading.Lock()
_jobs: dict[str, dict] = {}

_MAX_AGE_SECONDS = 3600  # prune finished jobs older than this


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(kind: str) -> str:
    """Register a new job in the "running" state and return its id."""
    job_id = uuid.uuid4().hex
    with _lock:
        _prune_locked()
        _jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "state": "running",
            "message": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
    return job_id


def update_job(job_id: str, **fields) -> None:
    """Merge *fields* (e.g. message=, state=) into an existing job."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(fields)
        job["updated_at"] = _now()


def get_job(job_id: str) -> dict | None:
    """Return a copy of the job dict, or None if unknown."""
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _prune_locked() -> None:
    """Drop finished jobs older than _MAX_AGE_SECONDS. Caller holds _lock."""
    cutoff = time.time() - _MAX_AGE_SECONDS
    stale = [
        jid for jid, job in _jobs.items()
        if job["state"] != "running"
        and datetime.fromisoformat(job["updated_at"]).timestamp() < cutoff
    ]
    for jid in stale:
        del _jobs[jid]
