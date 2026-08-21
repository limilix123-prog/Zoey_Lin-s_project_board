"""v0.7.1 data model migration.

Auto-runs on app start (wired by ``feature_app_factory.init_storage``) and
idempotent enough to be called repeatedly without side effects:

1. Add ``users.rank`` column (INTEGER NOT NULL DEFAULT 4) if missing.
   The same DDL is also run by ``UserStorage.init_schema`` so the column
   is created on a fresh install; this step is a no-op once the column
   is present.
2. Backfill ``users.rank`` from the legacy ``users.role`` column for
   every row whose ``rank`` is still the DEFAULT 4 sentinel *and* whose
   legacy role is one of the five v0.7.0 names. Rows that already have
   a real rank (T0-T3) are left alone so a re-run after a partial
   migration is safe.
3. Sync ``users.role`` from ``users.rank`` so the legacy field stays in
   lock-step with the new column. Same "only if stale" guard as step 2.
4. Convert ``project_members.role_in_project = 'member'`` to
   ``'user'`` (T4) — the v0.7.0 "member" literal has no place in the
   v0.7.1 model (where the only per-project roles are
   ``project_leader`` / ``team_leader`` / ``user``); the new model
   treats every pre-existing member as a plain T4 user.

The migration never deletes rows. In particular, T0/T1 rows that
happen to appear in ``project_members`` (because v0.7.0 let admins
and managers be added as ordinary members) are *not* removed here —
the v0.7.0 endpoints that read those rows still need them. v0.7.2's
endpoint rewrite is the place to enforce the "T0/T1 are not in
project_membership" invariant.

Logging
-------
Each step logs a one-line summary at INFO so a tail-grep on the
``project_board.*`` logger can confirm the migration ran and how
many rows it touched. The summary at the end is suitable for paste
into a handoff doc.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

# Legacy role → v0.7.1 T-scale rank. The reverse direction is the
# ``_LEGACY_ROLE_FOR_RANK`` table in :mod:`feature_storage`; the two
# tables are kept in sync by convention (one shared migration pass).
_ROLE_TO_RANK: dict[str, int] = {
    "admin": 0,
    "manager": 1,
    "project_leader": 2,
    "team_leader": 3,
    "user": 4,
}

# v0.7.1 default rank. Rows that have this rank but a non-legacy role
# string (e.g. a fresh insert that defaulted rank=4) are not back-filled
# by step 2 — the role→rank table has nothing meaningful to say about
# them and they are already at the right T-scale value.
_DEFAULT_RANK: int = 4


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(r["name"]) == column for r in rows)


def run_migration(db_path: str) -> dict[str, int]:
    """Execute the v0.7.1 migration against ``db_path``.

    Returns a small dict summarising the per-step row counts so the
    caller (the app factory, a smoke runner, or the in-line validator
    in the v0.7.1 brief) can assert the migration touched the rows it
    was supposed to. The function is total: it never raises on the
    happy path; unexpected SQL errors propagate.
    """
    summary: dict[str, int] = {
        "users_rank_added_column": 0,
        "users_rank_backfilled": 0,
        "users_role_synced": 0,
        "project_members_rewritten": 0,
    }
    conn = _connect(db_path)
    try:
        # Step 1 — ensure users.rank exists. ``UserStorage.init_schema``
        # already runs the same DDL on app start, but the migration is
        # the canonical place to guarantee the column is present so a
        # call from a smoke runner (no app context) still upgrades a
        # legacy DB.
        if not _column_exists(conn, "users", "rank"):
            conn.execute(
                "ALTER TABLE users ADD COLUMN rank INTEGER NOT NULL DEFAULT 4"
            )
            summary["users_rank_added_column"] = 1
            logger.info("v0.7.1 migration: added users.rank column")

        # Step 2 — backfill rank from role for legacy rows.
        # Guard: only touch rows whose rank is the DEFAULT 4 sentinel
        # AND whose role is one of the v0.7.0 names. Anything else is
        # either already at the right rank or a row that did not exist
        # when the role→rank table was authored.
        for role, rank in _ROLE_TO_RANK.items():
            cur = conn.execute(
                "UPDATE users SET rank = ? "
                "WHERE rank = ? AND role = ?",
                (rank, _DEFAULT_RANK, role),
            )
            if cur.rowcount:
                summary["users_rank_backfilled"] += int(cur.rowcount)
                logger.info(
                    "v0.7.1 migration: backfilled %s users role=%s -> rank=%s",
                    cur.rowcount, role, rank,
                )

        # Step 3 — sync role from rank for any row that drifted.
        # Use the same _ROLE_TO_RANK table in reverse; we iterate ranks
        # in deterministic order (T0 first) so the log lines are
        # stable across runs and easy to diff.
        for role, rank in _ROLE_TO_RANK.items():
            cur = conn.execute(
                "UPDATE users SET role = ? "
                "WHERE rank = ? AND role != ?",
                (role, rank, role),
            )
            if cur.rowcount:
                summary["users_role_synced"] += int(cur.rowcount)
                logger.info(
                    "v0.7.1 migration: synced role for %s users rank=%s -> role=%s",
                    cur.rowcount, rank, role,
                )

        # Step 4 — project_members.role_in_project 'member' -> 'user'.
        # v0.7.0 used 'member' as the only per-project role; v0.7.1
        # uses 'project_leader' / 'team_leader' / 'user'. The
        # migration's conservative choice is to map every 'member' to
        # 'user' (T4); v0.7.2 will re-tag T2/T3 rows separately.

        #
        # v0.9.2 sub-task 7 — the ``role_in_project`` column is
        # gone (replaced by ``custom_role_id`` FK into
        # ``project_custom_roles``). The migration step is a no-op
        # when the column is absent — a fresh v0.9.1 install skips

        # it, and a legacy install's column is dropped earlier in
        # the init_schema flow.
        if _column_exists(conn, "project_members", "role_in_project"):
            cur = conn.execute(
                "UPDATE project_members SET role_in_project = ? "
                "WHERE role_in_project = ?",
                ("user", "member"),
            )
            summary["project_members_rewritten"] = int(cur.rowcount)
            if cur.rowcount:
                logger.info(
                    "v0.7.1 migration: rewrote %s project_members "
                    "role_in_project 'member' -> 'user'",
                    cur.rowcount,
                )
        else:
            logger.info(
                "v0.7.1 migration step 4 skipped: "
                "project_members.role_in_project column not present "
                "(v0.9.1 schema)"
            )

    finally:
        conn.close()

    logger.info(
        "v0.7.1 migration done: %s",
        ", ".join(f"{k}={v}" for k, v in summary.items()),
    )
    return summary


def main(db_path: Optional[str] = None) -> dict[str, int]:
    """CLI / standalone entry point. If ``db_path`` is None, the default
    ``project_board/data/project_board.db`` (relative to repo root) is
    used so the script can be run by hand for one-off upgrades.

    Kept separate from :func:`run_migration` so the import side-effect
    is just the function definition; nothing in the storage layer
    starts running until :func:`run_migration` is invoked.
    """
    if db_path is None:
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.normpath(
            os.path.join(here, "..", "data", "project_board.db")
        )
    return run_migration(str(db_path))


if __name__ == "__main__":
    main()
