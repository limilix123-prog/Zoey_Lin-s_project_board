"""v0.9.2 data model migration — add ``project_nodes`` and role tables.

Auto-runs on app start (wired by
:mod:`project_board.app.feature_app_factory.create_app`) and
idempotent enough to be called repeatedly without side effects.

Schema additions (v0.9.2; v0.9.3 — user-level perm table dropped)
----------------------------------------------------------------
1. ``project_nodes(id, project_id, parent_id, level, name, description,
   status, position, created_at, updated_at)`` — N-level tree (1..6),
   4 statuses (``backlog``/``in_progress``/``done``/``archived``).
   ``parent_id`` is ``NULL`` for top-level nodes; the depth is
   server-enforced by the helper in
   :mod:`project_board.projects.feature_storage_nodes` so the
   storage layer is the single chokepoint. ``ON DELETE CASCADE``
   from ``projects`` (deleting a project removes its tree) and
   from ``parent_id`` (deleting a node removes its subtree).
2. (v0.9.3) — the user-level ``project_node_permissions`` table
   is **no longer** installed. The role-grant path
   (``user → project_members.custom_role_id → project_custom_role_permissions``)
   is the only path; v0.9.2 had added an empty user-level table
   that v0.9.3 dropped (user 8/13 19:34 拍板). On a pre-v0.9.3
   DB the table is left in place with its existing 0 rows
   (idempotent — no DDL issued against it).

The migration never deletes rows. The legacy ``project_features``
table is **kept** (read-only) per the 7/22 业务级 lock + 历史回溯
rule — a hand-crafted query (or a re-run of a v0.9.0 smoke) must
still see the historical rows.

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


def _connect(db_path: str) -> sqlite3.Connection:
    """Open ``db_path`` with the same pragmas the storage layer uses.

    Local helper (not imported from :mod:`feature_storage`) so the
    migration script has no top-of-module dependency on the storage
    class — a future contributor can run the migration against a
    throwaway DB from a bare Python process without dragging the
    whole ``ProjectStorage`` machinery in.
    """
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return True iff ``table`` is a row in ``sqlite_master``.

    Used to skip the install step when the table is already present
    (e.g. a re-run of the migration on a DB that already has v0.9.2
    schema).
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def run_migration(db_path: str) -> dict[str, int]:
    """Execute the v0.9.2 migration against ``db_path``.

    Returns a small dict summarising the per-step row counts so the
    caller (the app factory, a smoke runner, or the in-line validator
    in the v0.9.2 brief) can assert the migration touched the rows
    it was supposed to. The function is total: it never raises on
    the happy path; unexpected SQL errors propagate.

    Idempotency
    -----------
    The DDL uses ``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF
    NOT EXISTS`` so the install step is a no-op on a fresh install
    or a re-run. The summary dict always reports zero for the
    counter when the table is already present.

    v0.9.3
    -------
    The user-level ``project_node_permissions`` table is no longer
    installed. The role-grant path
    (``user → project_members.custom_role_id → project_custom_role_permissions``)
    is the only path; the v0.9.2 install step that created the
    user-level table is gone. On a pre-v0.9.3 DB the table is left
    untouched (0 rows in practice; the migration never deletes
    rows per the 7/22 业务级 lock + 历史回溯 rule).
    """
    summary: dict[str, int] = {
        "nodes_table_installed": 0,
    }
    conn = _connect(db_path)
    try:
        # --- Step 1: install project_nodes (+ role tables via
        # the same fragment) (DDL is idempotent) ---
        if not _table_exists(conn, "project_nodes"):
            from .feature_storage_ddl_v092 import _V092_DDL
            conn.executescript(_V092_DDL)
            summary["nodes_table_installed"] = 1
            logger.info(
                "v0.9.2 migration: installed project_nodes (+ role) tables"
            )
        else:
            logger.info(
                "v0.9.2 migration: project_nodes already present, skipping"
            )

        # --- v0.9.3 — Step 2 (project_node_permissions install) is
        # removed. The user-level grant table is gone. Existing
        # pre-v0.9.3 DBs that still have the table are not touched
        # (the table is left empty + unused; 7/22 RBAC 业务 lock
        # forbids silent DELETE). ---

    finally:
        conn.close()

    logger.info(
        "v0.9.2 migration done: %s",
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
