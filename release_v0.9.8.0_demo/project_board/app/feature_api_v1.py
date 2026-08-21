"""v0.9.8 experiment — /api/v1/system/status JSON endpoint (sub-agent worker trial).

Bounded, read-only, 0 side-effect. Returns:
- version: hardcoded "0.9.7.0" (current milestone at time of v0.9.8 trial)
- db_schema: "ok" if storage init_schema idempotent, else "error"
- users_count: SELECT COUNT(*) from users via UserStorage.count_users()
- projects_count: SELECT COUNT(*) from projects via sqlite3 (no
  ProjectStorage.count_all_projects_safe() exists; the count is a single
  parameterless SELECT against the same DB the factory already opened, so
  it is a 5-line shim and not a new chokepoint)
- uptime_seconds: time.monotonic() from process start (per-worker process)
- timestamp: ISO 8601 UTC with nanosecond precision (matching project
  convention; aligned with feature_storage._now_iso()'s microsecond shape)

No @require_auth (read-only public info, no business-lock needed, no
side-effect).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# process start time (for uptime).
# time.monotonic() is the right primitive — it is not affected by wall-clock
# adjustments, and "uptime" is conceptually a duration, not a calendar
# reading. Module-level so the counter survives across requests within the
# same worker process. Multi-worker deploys would each report their own
# uptime; for a single-process Flask dev server this is the right scope.
_process_start_monotonic = time.monotonic()


def _now_iso() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ``.

    Uses ``time.time_ns()`` to get nanosecond precision (matching the
    project convention; cf. user memory 7/22: IDs / timestamps that need
    uniqueness at sub-second resolution use ``time.time_ns()``).
    """
    secs, ns = divmod(time.time_ns(), 1_000_000_000)
    base = datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ns:09d}Z"


def _count_projects() -> int:
    """Return SELECT COUNT(*) FROM projects. 5-line shim.

    ``ProjectStorage`` does not expose a ``count_all_projects_safe()``;
    calling ``list_visible_to(None)`` is not safe (it expects a user
    object). The cleanest minimal read is a direct COUNT(*) against the
    same SQLite file the factory already opened — that file is exposed
    via ``current_app.config["PB_CONFIG"]["DB_PATH"]`` (set in
    :func:`feature_app_factory.create_app`).
    """
    cfg = current_app.config.get("PB_CONFIG") or {}
    db_path = cfg.get("DB_PATH")
    if not db_path:
        return 0
    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None)
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()
        return int(row[0]) if row is not None else 0
    finally:
        conn.close()


@bp.get("/system/status")
def system_status():
    """v0.9.8 experiment — return server status JSON.

    Read-only, no auth required (public info), no chokepoint, no
    business-lock needed. Returns a 200 JSON body with 6 fields:

    - ``version``: hardcoded "0.9.7.0" (the current milestone when this
      trial landed; bumping requires a 1-line edit, not a config pull,
      to keep the trial self-contained)
    - ``db_schema``: "ok" if both ``UserStorage`` and ``ProjectStorage``
      can report a count without raising; "error" otherwise (with the
      exception logged at WARNING)
    - ``users_count`` / ``projects_count``: integer COUNT(*) values
    - ``uptime_seconds``: int seconds since this Python process started
    - ``timestamp``: ISO 8601 UTC with nanosecond precision (Z suffix)

    Bounded scope: 不动现有任何 endpoint, 不动任何 schema, 不写任何数据.
    """
    storage = current_app.config.get("PB_STORAGE")
    db_status = "ok"
    users_count = 0
    projects_count = 0
    try:
        if storage is not None:
            users_count = storage.count_users()
        projects_count = _count_projects()
    except Exception as exc:  # noqa: BLE001 — broad on purpose: read-only
        logger.warning("system status partial: %s", exc)
        db_status = "error"

    uptime = int(time.monotonic() - _process_start_monotonic)
    return jsonify({
        "version": "0.9.7.0",
        "db_schema": db_status,
        "users_count": users_count,
        "projects_count": projects_count,
        "uptime_seconds": uptime,
        "timestamp": _now_iso(),
    })


__all__ = ["bp"]
