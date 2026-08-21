"""/team/_internal/report storage primitives.

The ``agent_team_status`` table SQL lives in
:mod:`project_board.projects.feature_storage` (single source of DDL,
so :meth:`ProjectStorage.init_schema` auto-creates the table on
first launch). This module hosts the per-entry validation helper
and the UPSERT helper used by the ``POST /team/_internal/report``
route. Lives in the team module so the storage layer file stays
under the 1000-line cleanliness threshold.

The UPSERT helper accepts a :class:`ProjectStorage` so the team
module can reuse the same lock-guarded connection pattern the
rest of the storage layer uses (no duplicate SQLite plumbing).

v0.9.7 — ``GET /team`` retired (302 → /projects). The human-view
read helpers (``list_team_status_rows`` + ``AgentTeamStatusRow``
dataclass + ``TEAM_STATUS_DEFAULT`` default) were removed in the
same patch because the only caller was the retired handler.
The write side (UPSERT + per-entry validation) stays.
"""

from __future__ import annotations

import datetime as _dt
import logging
import time
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

TEAM_STATUSES: frozenset[str] = frozenset({"idle", "busy", "blocked", "offline"})


def _now_iso() -> str:
    """ISO 8601 UTC with nanosecond suffix (same pattern as feature_storage)."""
    secs, ns = divmod(time.time_ns(), 1_000_000_000)
    base = _dt.datetime.fromtimestamp(secs, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ns:09d}Z"


def validate_team_entry(entry: Any) -> tuple[str, str, str, int]:
    """Validate one report entry; return ``(name, desc, status, count)``.

    Raises ``ValueError`` on any malformed field so the caller can
    abort the whole batch without partial writes.
    """
    if not isinstance(entry, Mapping):
        raise ValueError("each entry must be a mapping")
    name = str(entry.get("agent_name", "") or "").strip()
    if not name:
        raise ValueError("agent_name is required")
    description = str(entry.get("description", "") or "")
    raw_status = str(entry.get("status", "") or "").strip().lower()
    if raw_status not in TEAM_STATUSES:
        raise ValueError(f"invalid status: {raw_status!r}")
    raw_count = entry.get("task_count", 0)
    try:
        task_count = int(raw_count)
    except (TypeError, ValueError):
        raise ValueError(f"task_count must be int, got {raw_count!r}")
    if task_count < 0:
        raise ValueError(f"task_count must be >= 0, got {task_count}")
    return name, description, raw_status, task_count


def apply_team_report(
    storage,
    report,
    reported_by: str,
    now_iso: Optional[str] = None,
) -> int:
    """UPSERT a batch of agent rows into ``agent_team_status``.

    Server-side chokepoint for the internal /team/report endpoint —
    the route layer authenticates via shared secret and then
    delegates the write here. Each entry is validated by
    :func:`validate_team_entry`; any failure raises ``ValueError``
    and the entire batch is rejected (no partial writes). ``now_iso``
    defaults to the helper's current-time string so tests can pin a
    deterministic timestamp.
    """
    if not isinstance(report, list):
        raise ValueError("report must be a list")
    now = str(now_iso) if now_iso else _now_iso()
    with storage._lock:
        conn = storage._connect()
        try:
            for entry in report:
                name, desc, status, count = validate_team_entry(entry)
                conn.execute(
                    "INSERT INTO agent_team_status "
                    "(agent_name, description, status, task_count, "
                    "reported_at, reported_by) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(agent_name) DO UPDATE SET "
                    "description=excluded.description, "
                    "status=excluded.status, "
                    "task_count=excluded.task_count, "
                    "reported_at=excluded.reported_at, "
                    "reported_by=excluded.reported_by",
                    (name, desc, status, count, now, str(reported_by)),
                )
        finally:
            conn.close()
    written = len(report)
    logger.info("team report applied entries=%d reported_by=%s", written, reported_by)
    return written


__all__ = [
    "TEAM_STATUSES",
    "validate_team_entry",
    "apply_team_report",
]
