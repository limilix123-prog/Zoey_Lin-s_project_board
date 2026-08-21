"""v0.9.7p1 — :class:`ProjectStorage` schema-migration method split-out.

The v0.9.2 sub-task 7 migration that collapses the "3 baseline + N
custom" two-tier role model into a single tier lives here rather than
in :mod:`project_board.projects.feature_storage` so the latter stays
under the 1000-line cleancode cap. The migration is installed onto
:class:`ProjectStorage` at import time via
:func:`install_migration_methods` below so the public call site
(``storage._install_role_v091_migration(conn)`` from
:meth:`ProjectStorage.init_schema`) is unchanged.

Split members
-------------
* :data:`_BASELINE_ROLE_NAMES` — the 3 baseline role-name literals
  (``project_leader`` / ``team_leader`` / ``user``). Used by the
  step-5 mapping from the legacy ``_v091_role_snapshot.role_in_project``
  string to ``project_custom_roles.id``. Single source of truth.
* :func:`_do_table_exists` / :func:`_do_column_exists` — small
  static-helper methods used only by the migration below. Brought
  along because the migration is the only caller in the storage
  layer.
* :func:`_do_install_role_v091_migration` — the v0.9.2 sub-task 7
  migration. Five steps (drop ``project_role_permissions``;
  snapshot + rebuild ``project_members``; seed baseline roles for
  every existing project; map legacy ``role_in_project`` strings
  to ``custom_role_id`` FK values). Idempotent on a fresh install.

Why a dedicated module
----------------------
v0.9.7p1 (挂账 3) — the 1405-line :mod:`feature_storage` was split
into 3 surface modules (rbac / features / nodes / roles / ddl_v092)
plus this migration module + the bootstrap module. The migration
helpers are the only place in the storage layer that still owns
historical-shape data; isolating them here makes the runtime CRUD
chokepoint (:mod:`feature_storage`) trivially auditable.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# 3 baseline role names from v0.7.1 CHECK constraint. Used by
# _install_role_v091_migration step 5 to map legacy
# ``role_in_project`` strings to project_custom_roles.id. Extend
# this tuple if a future v0.7.x release adds another baseline
# literal.
_BASELINE_ROLE_NAMES: tuple[str, ...] = (
    "project_leader",
    "team_leader",
    "user",
)

def _do_install_role_v091_migration(
    self,
    conn: sqlite3.Connection,
) -> None:
    """Migrate the role model to v0.9.2.

    v0.9.2 sub-task 7 collapses the "3 baseline + N custom" two-tier
    role model into a single tier where every role is a row
    in ``project_custom_roles``. The migration:

    1. drops the now-redundant ``project_role_permissions``
       table (the 3-baseline template);
    2. snapshots the legacy ``role_in_project`` column
       into a temporary table so the column can be dropped
       from ``project_members`` (sqlite < 3.35 cannot
       DROP COLUMN directly);
    3. rebuilds ``project_members`` without the
       ``role_in_project`` column;
    4. inserts the 3 baseline role rows
       (``project_leader`` / ``team_leader`` / ``user``) for
       every existing project, idempotent via
       ``INSERT OR IGNORE``;
    5. migrates each legacy role string into the
       corresponding ``custom_role_id`` for the same
       project.

    Idempotent: re-running on a fresh install (where the
    source tables / columns do not exist) is a no-op. The
    helper is called from :meth:`init_schema` after the
    base + v0.9.2 DDL has been applied.
    """
    # Step 1: drop the now-redundant
    # ``project_role_permissions`` table.
    if _do_table_exists(conn, "project_role_permissions"):
        conn.execute("DROP TABLE project_role_permissions")
        logger.info(
            "v0.9.1 migration: dropped project_role_permissions table"
        )
    # Steps 2 + 3: rebuild ``project_members`` to drop
    # ``role_in_project`` if the column is still present.
    if _do_column_exists(conn, "project_members", "role_in_project"):
        # Step 2a: snapshot the legacy column. The
        # snapshot is kept until the migration step 5
        # finishes so a re-run on a partial migration
        # can resume.
        if not _do_table_exists(conn, "_v091_role_snapshot"):
            conn.execute(
                "CREATE TABLE _v091_role_snapshot ("
                "    project_id      INTEGER NOT NULL,"
                "    user_id         INTEGER NOT NULL,"
                "    role_in_project TEXT    NOT NULL,"
                "    PRIMARY KEY (project_id, user_id)"
                ")"
            )
            conn.execute(
                "INSERT INTO _v091_role_snapshot "
                "(project_id, user_id, role_in_project) "
                "SELECT project_id, user_id, role_in_project "
                "FROM project_members"
            )
            logger.info(
                "v0.9.1 migration: snapshotted role_in_project to "
                "_v091_role_snapshot"
            )
        # Step 2b: rebuild project_members without the
        # role_in_project column.
        conn.execute("ALTER TABLE project_members RENAME TO project_members_old")
        conn.execute(
            "CREATE TABLE project_members ("
            "    project_id     INTEGER NOT NULL,"
            "    user_id        INTEGER NOT NULL,"
            "    added_at       TEXT    NOT NULL,"
            "    custom_role_id INTEGER"
            "        REFERENCES project_custom_roles(id) ON DELETE SET NULL,"
            "    PRIMARY KEY (project_id, user_id),"
            "    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,"
            "    FOREIGN KEY (user_id)    REFERENCES users(id)"
            ")"
        )
        conn.execute(
            "INSERT INTO project_members "
            "(project_id, user_id, added_at) "
            "SELECT project_id, user_id, added_at "
            "FROM project_members_old"
        )
        conn.execute("DROP TABLE project_members_old")
        logger.info(
            "v0.9.1 migration: rebuilt project_members without role_in_project"
        )
    # Step 4: seed 3 baseline role rows + default
    # per-node grants for every existing project
    # (project_leader=manage / team_leader=modify /
    # user=read). INSERT OR IGNORE keeps it
    # idempotent on fresh installs.
    existing_projects = conn.execute(
        "SELECT id FROM projects"
    ).fetchall()
    for row in existing_projects:
        # _seed_baseline_roles_for_project is installed by
        # feature_storage_bootstrap.install_bootstrap_methods
        # (bottom of feature_storage). The self._seed_...
        # call site is preserved unchanged from the
        # pre-split file.
        self._seed_baseline_roles_for_project(
            conn, int(row["id"]),
        )
    # Step 5: map role_in_project (string from snapshot)
    # -> custom_role_id for the same project. A
    # baseline role name resolves to a non-NULL id; a
    # member whose role_in_project is unknown stays
    # NULL (null role).
    if _do_table_exists(conn, "_v091_role_snapshot"):
        for r in _BASELINE_ROLE_NAMES:
            conn.execute(
                "UPDATE project_members "
                "SET custom_role_id = ("
                "  SELECT id FROM project_custom_roles "
                "  WHERE project_custom_roles.project_id = "
                "        project_members.project_id "
                "    AND project_custom_roles.name = ?"
                ") "
                "WHERE custom_role_id IS NULL "
                "AND EXISTS ("
                "  SELECT 1 FROM _v091_role_snapshot s "
                "  WHERE s.project_id = project_members.project_id "
                "    AND s.user_id = project_members.user_id "
                "    AND s.role_in_project = ?"
                ")",
                (r, r),
            )
        conn.execute("DROP TABLE _v091_role_snapshot")
        logger.info(
            "v0.9.1 migration: resolved role_in_project strings to "
            "custom_role_id; dropped snapshot table"
        )

def _do_table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Return ``True`` iff ``name`` is a table in the open ``conn``."""
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cur.fetchone() is not None

def _do_column_exists(
    conn: sqlite3.Connection, table: str, column: str
) -> bool:
    """Return ``True`` iff ``column`` is a column of ``table``."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())

def install_migration_methods() -> None:
    """Attach the migration helpers to :class:`ProjectStorage`.

    Called by :mod:`feature_storage` at the bottom of the module
    (after :class:`ProjectStorage` is fully defined). The
    function is a no-op for any method that is already installed
    (idempotent re-import). Public names mirror the original
    methods so the ``init_schema`` call site is unchanged:

    * ``_install_role_v091_migration`` — the 5-step v0.9.2
      sub-task 7 migration
    * ``_table_exists`` / ``_column_exists`` — static helpers
      used by the migration
    """
    from .feature_storage import ProjectStorage

    _MIGRATION_METHODS = {
        "_install_role_v091_migration": _do_install_role_v091_migration,
        "_table_exists": staticmethod(_do_table_exists),
        "_column_exists": staticmethod(_do_column_exists),
    }
    for _name, _method in _MIGRATION_METHODS.items():
        if _name not in ProjectStorage.__dict__:
            setattr(ProjectStorage, _name, _method)

# Install on import. The bottom of feature_storage.py also calls
# this defensively; running it twice is a no-op.
install_migration_methods()

__all__ = ["install_migration_methods"]
