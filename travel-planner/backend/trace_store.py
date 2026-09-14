"""In-memory storage for run_id -> {recommendation, trace}.

MVP scope: no database, no persistence across restarts - matches PRD section 10
(no user accounts/history required for the MVP).
"""

import uuid
from threading import Lock

_store: dict[str, dict] = {}
_lock = Lock()


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def save_run(run_id: str, recommendation: dict, trace: list[dict]) -> None:
    with _lock:
        _store[run_id] = {"recommendation": recommendation, "trace": trace}


def get_run(run_id: str) -> dict | None:
    with _lock:
        return _store.get(run_id)
