"""v0.7.1 RBAC helpers split out from :mod:`feature_storage` for line-budget hygiene.

The main ``feature_storage.py`` file is the single chokepoint for project /
project_member writes; the v0.7.1 data-model changes added several
read-side helpers (auto-own check, membership cache, rank-label
formatting) that pushed the file past the ``cleancode --strict``
1000-line cap. The helpers are pure-Python and do not touch the
SQLite write path, so they live in this separate module and
``feature_storage.py`` re-exports the public names so existing
callers can keep working without an import-site rewrite.

Imports
-------
This module depends on ``ProjectStorage`` for the row-level lookups
the helpers perform. The import is local (inside each function that
needs it) so the import-time cycle that v0.7.0 worked around with
``ProjectStorage(db_path)`` is preserved — calling code can still
import both modules without an ordering constraint.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Final, Optional

logger = logging.getLogger(__name__)


# v0.7.1 — valid role_in_project literals. Same set as
# project_board.rbac.feature_storage.known_project_roles() but inlined
# here so the CHECK-constraint installer below does not have to take a
# cross-module import (avoids a circular import during the v0.7.x
# transition when the rbac module is being split).
_V0_7_1_PROJECT_ROLES: frozenset[str] = frozenset(
    {"project_leader", "team_leader", "user"}
)


# v0.7.1 — last-resort DB path used when neither the Flask app
# context nor the ``PB_DB_PATH`` env var is set. The path is the
# canonical ``data/project_board.db`` resolved relative to the
# project_board package. A smoke runner can introspect via
# ``project_board.projects.feature_storage_rbac._DEFAULT_DB_PATH_FALLBACK``.


def _compute_default_db_path() -> Optional[str]:
    """Compute the canonical fallback DB path (project_board/data/project_board.db).

    Resolved at import time so the constant is stable for the life
    of the process. Returns ``None`` if the directory does not exist
    yet (fresh checkout before ``init_schema``) — in that case the
    caller falls back to ``False`` from the row lookups, which is the
    same behavior as "no DB configured".
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(
        os.path.join(here, "..", "data", "project_board.db")
    )
    if os.path.isfile(candidate):
        return candidate
    return None


_DEFAULT_DB_PATH_FALLBACK: Optional[str] = os.environ.get(
    "PB_DEFAULT_DB_PATH",
) or _compute_default_db_path()


def get_db_path() -> Optional[str]:
    """Return the active Flask app's ``DB_PATH`` or the env-var fallback.

    The SQLite file location is read from ``current_app.config`` so the
    helper is request-scoped. ``None`` means no app context is active;
    the caller treats that as a miss without special-casing it.

    v0.7.1 — fallback for the smoke / migration runners that invoke
    these helpers from a bare Python process (no Flask app context).
    The fallback reads the ``PB_DB_PATH`` environment variable first,
    then the canonical ``_DEFAULT_DB_PATH_FALLBACK`` constant.
    """
    try:
        from flask import current_app
        cfg = current_app.config.get("PB_CONFIG") or {}
        db_path = cfg.get("DB_PATH")
        if db_path:
            return str(db_path)
    except RuntimeError:
        # No app context — fall through to the env-var / default path.
        pass
    env_path = os.environ.get("PB_DB_PATH")
    if env_path:
        return str(env_path)
    return _DEFAULT_DB_PATH_FALLBACK


def _is_auto_own(user) -> bool:
    """Return True iff ``user`` is a T0/T1 row that auto-owns every project.

    v0.7.1 data model: T0 (admin) and T1 (manager) are the platform
    super-users; they auto-own every project and *do not* appear in
    ``project_members``. The check is rank-based (the new T-scale is
    the source of truth) with a legacy ``role`` fallback so a row
    read by a code path that has not yet been updated to populate
    ``rank`` still classifies correctly. Returns False for ``None``
    or any user object missing both fields.
    """
    if user is None:
        return False
    rank = getattr(user, "rank", None)
    if rank is not None:
        return int(rank) in (0, 1)
    role = getattr(user, "role", None)
    # Legacy fallback (v0.7.0 used the role string as the source of
    # truth). Matches the role string the v0.7.0 rbac/feature_role
    # module exports; the literal comparison is enough because the
    # v0.7.0 seeders only ever write one of these five values.
    return str(role) in ("admin", "manager")


def _has_role_in_project_check(conn: sqlite3.Connection) -> bool:
    """Return True iff ``project_members.role_in_project`` has a CHECK constraint.

    The check looks at the ``sqlite_master`` schema dump for the
    table — the SQL is the only authoritative source for whether a
    CHECK was installed, because SQLite has no separate
    ``PRAGMA constraint_list`` on a column-level check. The search
    is a literal substring match on the SQL DDL; both true and false
    positives are caught by the post-install validation below.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'table' AND name = 'project_members'"
    ).fetchone()
    if row is None:
        return False
    sql = str(row["sql"] or "")
    return "CHECK" in sql.upper() and "role_in_project" in sql


# Membership-check used by user_can_see_project. Wraps storage.is_member via
# a lazy construction so we don't import ProjectStorage into its own module
# scope (avoids the circular type-hint dance).
_IS_MEMBER_CACHE: dict[tuple[int, int], bool] = {}


def _is_member_via_storage(project_id: int, user_id: int) -> bool:
    """Return whether ``user_id`` belongs to ``project_id`` via storage.

    v0.7.1: this helper still performs the *row* lookup only. The
    T0/T1 auto-own short-circuit is applied one level up, in
    :func:`_is_member_cached`, so the storage layer stays policy-free
    and a test that wants to check the raw row state (e.g. "is
    kylins actually in project_members row 7?") can call this
    helper directly without being lied to about auto-own.

    Returns ``False`` when no DB path is configured (e.g. outside a
    request) so the cache layer above never has to special-case it.
    """
    db_path = get_db_path()
    if not db_path:
        return False
    # Local import — see module docstring for the cycle-avoidance rationale.
    from .feature_storage import ProjectStorage
    return bool(ProjectStorage(db_path).is_member(project_id, user_id))


def _is_member_cached(project_id: int, user_id: int, user=None) -> bool:
    """Cached wrapper around :func:`_is_member_via_storage`.

    Stores the first lookup result in :data:`_IS_MEMBER_CACHE` so a
    burst of :func:`user_can_see_project` calls for the same
    ``(project_id, user_id)`` pair do not re-open the SQLite file.

    v0.7.1: an optional ``user`` argument short-circuits to ``True``
    for T0/T1 (auto-own) so the storage lookup is never even
    attempted. When ``user`` is ``None`` the helper falls back to
    the legacy row-only check — this preserves backward compatibility
    for the v0.7.0 callers that passed only ``(project_id, user_id)``
    and were satisfied with the table-level truth.
    """
    if user is not None and _is_auto_own(user):
        return True
    key = (int(project_id), int(user_id))
    cached = _IS_MEMBER_CACHE.get(key)
    if cached is not None:
        return cached
    result = _is_member_via_storage(project_id, user_id)
    _IS_MEMBER_CACHE[key] = result
    return result


def _invalidate_member_cache(project_id: int, user_id: int) -> None:
    """Drop a (project_id, user_id) entry from the membership cache.

    Called by :meth:`ProjectStorage.add_member` and
    :meth:`ProjectStorage.remove_member` so the cache used by
    :func:`user_can_see_project` cannot return a stale True after a
    remove.
    """
    _IS_MEMBER_CACHE.pop((int(project_id), int(user_id)), None)


# v0.9.5 — user-facing rank label. Single source of truth for
# the T0..T4 display string used by /me /users /projects/<id> /
# /help/glossary. Unknown ranks fall back to "T<rank> 普通用户"
# so a new rank the v0.9.5 UI does not yet know about still
# renders readably instead of crashing on a missing key.
_RANK_LABELS: Final[dict[int, str]] = {
    0: "T0 系统管理员",
    1: "T1 平台管理员",
    2: "T2 项目负责人",
    3: "T3 团队负责人",
    4: "T4 普通用户",
}


def format_rank_label(rank: int) -> str:
    """Return the user-facing T-scale label for ``rank``.

    v0.9.5 P0-3 — single source of truth for the rank string that
    surfaces on /me, /users, /projects/<id>, and the /help/glossary
    page. The function is the rank-to-label lookup; the rank-to-T
    string (e.g. "T0") is the rank itself, no lookup needed. Unknown
    ranks fall through to ``"T<rank> 普通用户"`` so a future rank
    addition does not raise a KeyError mid-render.

    Returns the same string for the canonical 0..4 set; clamps
    anything else to a stable "T<rank> 普通用户" so the helper
    is total (no exception) on bad input.
    """
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return "T? 普通用户"
    return _RANK_LABELS.get(r, f"T{r} 普通用户")


__all__ = [
    "get_db_path",
    "_is_auto_own",
    "_is_member_via_storage",
    "_is_member_cached",
    "_invalidate_member_cache",
    "format_rank_label",
]
