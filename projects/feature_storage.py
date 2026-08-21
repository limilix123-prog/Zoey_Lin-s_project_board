"""SQLite storage layer for projects and project members.

Independent of :class:`project_board.accounts.feature_storage.UserStorage`
(7/22 modularity principle): the two classes share the same SQLite file
but neither wraps nor inherits from the other, so each module is the
single chokepoint for its own writes.

Schema
------
``projects(id, name UNIQUE, description, owner_id FK→users.id, project_type,
created_at, updated_at)``. ``project_type`` has two literals —
``"common"`` for every user-creatable project and ``"system"`` reserved
for the platform self-status project seeded at boot. The
:meth:`ProjectStorage.init_schema` step rewrites any incoming
``"user"`` value to ``"common"`` so the migration is invisible to the
rest of the app.
``project_members(project_id, user_id, role_in_project, added_at)`` with a
composite PK and ``ON DELETE CASCADE`` from projects.

All SQL strings are parameterised — no string concatenation of user input.
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from ..rbac.feature_role import ADMIN, MANAGER
from .feature_storage_rbac import (
    _invalidate_member_cache as _invalidate_member_cache,
    _is_auto_own as _is_auto_own,
    _is_member_cached as _is_member_cached,
)

# Feature Board status whitelist. Four literals only. The set is the
# single source of truth for both the storage layer's INSERT / UPDATE
# validation and the route handler's move-status check. Adding a new
# column is a one-line change here + the template column list.
_FEATURE_STATUSES: frozenset[str] = frozenset(
    {"backlog", "in_progress", "done", "archived"}
)

logger = logging.getLogger(__name__)

# project-type discriminator. Two literals only — ``"common"`` for
# every user-creatable project and ``"system"`` for the platform
# self-status project seeded at boot. Schema's ``DEFAULT`` is
# ``"common"`` and the rewrite happens in init_schema so it is
# idempotent.

# ``"system"`` is reserved for the bootstrap path
# (create_system_project_if_missing); the create endpoint rejects
# a hand-crafted ``project_type=system`` POST with 400.
_PROJECT_TYPE_COMMON: str = "common"
_PROJECT_TYPE_SYSTEM: str = "system"

# Reused by ``create_system_project_if_missing`` to keep the bootstrap
# log line self-describing without inventing a new constant downstream.
_SYSTEM_DESCRIPTION: str = "项目管理系统种子项目 (auto-seeded)."

@dataclass(frozen=True)
class ProjectRow:
    """Immutable project record.

    Fields mirror the ``projects`` table columns. ``frozen=True`` so callers
    cannot mutate a row in place; updates go through the storage layer.
    """

    id: int
    name: str
    description: str
    owner_id: int
    project_type: str
    created_at: str
    updated_at: str

    @property
    def is_system(self) -> bool:
        """True iff this row is a platform-owned system project.

        Convenience accessor so route handlers can branch on
        ``row.is_system`` without comparing the string literal every time.
        The underlying column is ``project_type``; the property hides the
        raw value from template / endpoint code.
        """
        return str(self.project_type) == _PROJECT_TYPE_SYSTEM

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ProjectRow":
        return cls(
            id=int(row["id"]),
            name=str(row["name"]),
            description=str(row["description"] or ""),
            owner_id=int(row["owner_id"]),
            project_type=str(row["project_type"] or _PROJECT_TYPE_COMMON),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

@dataclass(frozen=True)
class FeatureRow:
    """Immutable feature record.

    Fields mirror the ``project_features`` table columns. ``frozen=True``
    so callers cannot mutate a row in place; updates go through the
    storage layer. ``status`` is always one of the four literals in
    :data:`_FEATURE_STATUSES`; the storage layer's ``move_feature``
    validates the value before writing so a hand-crafted POST cannot
    plant an unknown status.
    """

    id: int
    project_id: int
    name: str
    description: str
    status: str
    position: int
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "FeatureRow":
        return cls(
            id=int(row["id"]),
            project_id=int(row["project_id"]),
            name=str(row["name"]),
            description=str(row["description"] or ""),
            status=str(row["status"] or "backlog"),
            position=int(row["position"] or 0),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

# agent_team_status table is owned by the team module
# (project_board.team.feature_team_storage) so this file stays under
# the 1000-line cap. DDL stays here as the single source.
# POST /team/_internal/report is the active write; GET /team was
# retired in v0.9.7 (302 → /projects).

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    description  TEXT,
    owner_id     INTEGER NOT NULL,
    project_type TEXT    NOT NULL DEFAULT 'common',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS project_members (
    project_id     INTEGER NOT NULL,
    user_id        INTEGER NOT NULL,
    added_at       TEXT    NOT NULL,
    custom_role_id INTEGER
        REFERENCES project_custom_roles(id) ON DELETE SET NULL,
    PRIMARY KEY (project_id, user_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)    REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS project_features (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    description TEXT,
    status      TEXT    NOT NULL DEFAULT 'backlog',
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS agent_team_status (
    agent_name   TEXT    PRIMARY KEY,
    description  TEXT,
    status       TEXT    NOT NULL DEFAULT 'idle',
    task_count   INTEGER NOT NULL DEFAULT 0,
    reported_at  TEXT    NOT NULL,
    reported_by  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_owner          ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_members_user            ON project_members(user_id);
CREATE INDEX IF NOT EXISTS idx_features_project_status ON project_features(project_id, status, position);
-- v0.9.2 sub-task 8 (perf 9 ops) -- users ORDER BY id ASC is already covered by
-- the implicit PK btree, but a (created_at, id) composite gives the
-- /users page a covering index for the ``SELECT id, username, rank,
-- created_at`` projection. Cheap; idempotent.
CREATE INDEX IF NOT EXISTS idx_users_created_at        ON users(created_at, id);
"""

# v0.9.2 DDL fragment: 2 new tables + 2 new indexes. Concatenated
# to the base schema at init_schema time so a single
# ``executescript`` call installs the whole schema in one
# transaction. Imported lazily (function-body) so the cycle with
# feature_storage_ddl_v092 stays at "soft" status.
def _v092_ddl_fragment() -> str:
    from .feature_storage_ddl_v092 import _V092_DDL
    return _V092_DDL

# Column list for the read-side queries. Centralised so every SELECT
# stays in sync.
_PROJECT_COLS: str = (
    "id, name, description, owner_id, project_type, created_at, updated_at"
)
# Same column list but each column qualified with the ``p.`` alias used
# in the JOIN-backed queries below. Keeping a separate constant avoids
# the awkward ``replace(',', ', p.')`` trick which leaves dangling
# commas on the first column.
_PROJECT_COLS_P: str = ", ".join(
    f"p.{c.strip()}" for c in _PROJECT_COLS.split(",")
)

_ADMIN_LIST_SQL = f"""
SELECT {_PROJECT_COLS}
FROM projects
ORDER BY id ASC
"""

_USER_LIST_SQL = f"""
WITH owned AS (
    SELECT id, name, description, owner_id, project_type, created_at, updated_at
    FROM projects WHERE owner_id = ?
), membered AS (
    SELECT {_PROJECT_COLS_P}
    FROM projects p
    JOIN project_members pm ON pm.project_id = p.id
    WHERE pm.user_id = ?
)
SELECT * FROM owned
UNION
SELECT * FROM membered
ORDER BY id ASC
"""

_OWNED_LIST_SQL = f"""
SELECT {_PROJECT_COLS}
FROM projects
WHERE owner_id = ?
ORDER BY id ASC
"""

_MEMBER_OF_SQL = f"""
SELECT {_PROJECT_COLS_P}
FROM projects p
JOIN project_members pm ON pm.project_id = p.id
WHERE pm.user_id = ?
  AND p.owner_id != ?
ORDER BY p.id ASC
"""

_SYSTEM_SEED_DESCRIPTION: str = _SYSTEM_DESCRIPTION

class ProjectStorage:
    """Thread-safe SQLite wrapper for projects + project_members.

    Each public method opens a short-lived connection guarded by a lock so
    concurrent Flask request workers do not collide on the underlying file.
    Shares the same DB file as :class:`UserStorage` but owns its own tables
    and connection pool.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        parent = Path(db_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    # ---------- low-level helpers ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def init_schema(self) -> None:
        """Create tables and indexes if they do not exist.

        Migrates pre-existing DBs in three steps:

        1. ``ALTER TABLE ... ADD COLUMN project_type`` guarded by an
           ``OperationalError`` check so the column-add is idempotent.
        2. ``UPDATE projects SET project_type = 'common'
           WHERE project_type = 'user'`` rewrites any ``"user"`` row
           to ``"common"`` — a no-op on a fresh DB or a second run.
        3. v0.7.1 — install the CHECK constraint on
           ``project_members.role_in_project`` so the only valid
           literals are ``'project_leader'``, ``'team_leader'``,
           ``'user'``. The install is a table-recreate (SQLite has no
           ``ALTER TABLE ADD CONSTRAINT``); the migration is wrapped
           in a savepoint so a pre-existing CHECK is a no-op rather
           than a hard error.
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA_SQL)
                # v0.9.2 (v0.9.3 — user-level perm table dropped) — append
                # the v0.9.2 tables (project_nodes + 2 role / role-permission
                # tables) + 2 new indexes for tree-walk + role-permission
                # lookups. Fragment is CREATE TABLE IF NOT EXISTS so a
                # fresh install or a re-run is safe.
                conn.executescript(_v092_ddl_fragment())
                try:
                    conn.execute(
                        "ALTER TABLE projects ADD COLUMN "
                        "project_type TEXT NOT NULL DEFAULT 'common'"
                    )
                    logger.info(
                        "projects schema migrated: added project_type column"
                    )
                except sqlite3.OperationalError as exc:
                    # The column already exists — that is the fresh-install
                    # / post-migration steady state. The error string is
                    # stable across CPython versions: "duplicate column
                    # name: project_type". Match on the prefix to be safe.
                    if "duplicate column" not in str(exc).lower():
                        raise
                cur = conn.execute(
                    "UPDATE projects SET project_type = ? WHERE project_type = ?",
                    (_PROJECT_TYPE_COMMON, "user"),
                )
                if cur.rowcount > 0:
                    logger.info(
                        "projects schema migrated: rewrote %s 'user' rows "
                        "to 'common'",
                        cur.rowcount,
                    )
                # v0.9.2 sub-task 7 — add ``custom_role_id`` column
                # to ``project_members``. The column is nullable; a
                # member with no custom role is the default. The FK
                # is ``ON DELETE SET NULL`` so deleting a custom
                # role clears the member's assignment automatically.

                # ``ALTER TABLE ADD COLUMN`` is wrapped in try/except
                # because sqlite's ``IF NOT EXISTS`` is not supported
                # for ADD COLUMN — the "duplicate column" error is
                # the steady state (column already exists).
                try:
                    conn.execute(
                        "ALTER TABLE project_members ADD COLUMN "
                        "custom_role_id INTEGER REFERENCES "
                        "project_custom_roles(id) ON DELETE SET NULL"
                    )
                    logger.info(
                        "project_members schema migrated: added "
                        "custom_role_id column"
                    )
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise
                # v0.9.2 sub-task 7 -- index the
                # ``custom_role_id`` column AFTER it exists. The
                # CREATE INDEX lives here, not in the DDL fragment,
                # because the fragment runs before the ALTER TABLE
                # (sqlite's ``executescript`` is one transaction and

                # CREATE INDEX referencing a not-yet-existing column
                # would fail with "no such column"). The
                # ``IF NOT EXISTS`` guard makes the second / third
                # call a no-op.
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_members_custom_role "
                    "ON project_members(project_id, custom_role_id)"
                )
                # v0.9.2 sub-task 7 — covering index for
                # ``list_members`` (hot path for /projects/<id>/members).
                # ``(project_id, added_at)`` lets the engine return rows
                # in ``added_at ASC`` order without a temp btree for the
                # sort. Idempotent.
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_members_project_added_at "
                    "ON project_members(project_id, added_at)"
                )
                # v0.9.3 — dropped idx_node_perms_node_user with the
                # project_node_permissions table (8/13 拍板). v0.9.2
                # sub-task 7 also drops the redundant
                # project_role_permissions (3-baseline role template) and
                # migrates role_in_project to custom_role_id FK values.
                self._install_role_v091_migration(conn)
                logger.info("projects schema initialised at %s", self._db_path)
            finally:
                conn.close()

    # ---------- projects ----------

    def create(
        self,
        name: str,
        description: str,
        owner_id: int,
        project_type: str = _PROJECT_TYPE_COMMON,
    ) -> int:
        """Insert a project. Returns the new id. Raises ``sqlite3.IntegrityError``
        on a duplicate name so callers can surface a 409.

        ``project_type`` defaults to ``"common"``; ``_normalise_project_type``
        maps a ``"user"`` literal to ``"common"`` so the create handler
        never produces a row that bypasses the schema.

        v0.9.2 sub-task 7 -- after the project is
        inserted, the 3 baseline roles
        (project_leader / team_leader / user) are
        seeded into ``project_custom_roles`` for the
        new project (with the default per-node grants
        auto-applied). The seed is idempotent so a
        re-run on a pre-existing project is a no-op.
        """
        project_type_norm = _normalise_project_type(project_type)
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO projects "
                    "(name, description, owner_id, project_type, "
                    "created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        description,
                        int(owner_id),
                        project_type_norm,
                        now,
                        now,
                    ),
                )
                new_id = int(cur.lastrowid)
                # Seed baseline roles for the newly created
                # project. Done in the same connection /
                # transaction window so a failed insert
                # cannot leave the project without its
                # baseline roles.
                self._seed_baseline_roles_for_project(conn, int(new_id))
                logger.info(
                    "project created id=%s name=%s owner_id=%s type=%s",
                    new_id,
                    name,
                    int(owner_id),
                    project_type_norm,
                )
                return new_id
            finally:
                conn.close()

    def find_by_id(self, project_id: int) -> Optional[ProjectRow]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT {_PROJECT_COLS} FROM projects WHERE id = ?",
                    (int(project_id),),
                ).fetchone()
                return ProjectRow.from_row(row) if row is not None else None
            finally:
                conn.close()

    def list_visible_to(self, user, is_admin: bool) -> list[ProjectRow]:
        """Return the projects ``user`` may see.

        * admin → every project
        * user  → projects the user owns OR is a member of
        """
        with self._lock:
            conn = self._connect()
            try:
                if is_admin:
                    rows = conn.execute(_ADMIN_LIST_SQL).fetchall()
                else:
                    rows = conn.execute(
                        _USER_LIST_SQL,
                        (int(user.id), int(user.id)),
                    ).fetchall()
                return [ProjectRow.from_row(r) for r in rows]
            finally:
                conn.close()

    def list_members(
        self, project_id: int
    ) -> list[tuple[int, str, str, int | None]]:
        """Return ``(user_id, username, added_at, custom_role_id)`` rows.

        Username is joined from the shared ``users`` table — that table is
        owned by :class:`UserStorage` but a SELECT against the same SQLite
        file is the cheapest, normalised way to surface the field. Writes
        to ``users`` still go through ``UserStorage`` exclusively; this
        method only reads.

        v0.9.2 sub-task 7 — the per-project role model is a
        single-tier FK into ``project_custom_roles``. The 4th
        tuple element is ``custom_role_id`` (nullable); ``None``
        is the "null role" case (member has no project role).
        The role name is resolved client-side via the cached
        :meth:`list_roles` result; this method only ships the id.
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT pm.user_id, u.username, "
                    "       pm.added_at, pm.custom_role_id "
                    "FROM project_members pm "
                    "JOIN users u ON u.id = pm.user_id "
                    "WHERE pm.project_id = ? "
                    "ORDER BY pm.added_at ASC",
                    (int(project_id),),
                ).fetchall()
                return [
                    (
                        int(r["user_id"]),
                        str(r["username"]),
                        str(r["added_at"]),
                        (
                            int(r["custom_role_id"])
                            if r["custom_role_id"] is not None
                            else None
                        ),
                    )
                    for r in rows
                ]
            finally:
                conn.close()

    # ---------- stage 2: delete + membership helpers ----------

    def delete(self, project_id: int) -> bool:
        """Delete a project. ON DELETE CASCADE removes its ``project_members``.

        Returns True if a project row was actually removed.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM projects WHERE id = ?", (int(project_id),),
                )
                removed = cur.rowcount > 0
                if removed:
                    logger.info("project deleted id=%s", int(project_id))
                return removed
            finally:
                conn.close()

    def is_member(self, project_id: int, user_id: int) -> bool:
        """True iff ``user_id`` is a row in ``project_members(project_id)``."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM project_members "
                    "WHERE project_id = ? AND user_id = ? LIMIT 1",
                    (int(project_id), int(user_id)),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def list_owned_by(self, user_id: int) -> list[ProjectRow]:
        """Return every project whose ``owner_id == user_id``.

        The owner list is one of the two project views on the /me
        consolidated profile page. The query is a single-table lookup
        with no JOIN; it relies on the ``idx_projects_owner`` index
        declared in ``_SCHEMA_SQL``.
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    _OWNED_LIST_SQL, (int(user_id),),
                ).fetchall()
                return [ProjectRow.from_row(r) for r in rows]
            finally:
                conn.close()

    def list_member_of(self, user_id: int) -> list[ProjectRow]:
        """Return every project the user is a member of (excluding their own).

        ``/me`` block 4 ("Projects I'm a member of") wants the
        non-owned slice so the user does not see their own projects twice.
        The ``AND p.owner_id != ?`` clause in the SQL enforces that here,
        server-side; callers (and the template) do not need to dedupe.
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    _MEMBER_OF_SQL, (int(user_id), int(user_id)),
                ).fetchall()
                return [ProjectRow.from_row(r) for r in rows]
            finally:
                conn.close()

    def list_owned_and_member_counts(
        self, user_ids: list[int],
    ) -> dict[int, dict[str, int]]:
        """Return ``{user_id: {owned, member}}`` counts in 2 batch queries.

        v0.9.2 sub-task 8 (perf 9 ops) -- N+1 to 2 queries for the /users
        directory page. The previous shape was one
        ``list_owned_by`` + one ``list_member_of`` call per user
        rendered — on a 8-user directory that's 16 round-trips.
        This helper is always exactly 2 round-trips regardless
        of user count. Members are counted as the number of
        distinct ``project_members`` rows for the user where
        the project is not owned by them (matches the
        :meth:`list_member_of` semantics so the /users page
        count agrees with the /me block 4 count for the same
        user).

        Empty ``user_ids`` short-circuits to ``{}`` (no SQL).
        Users with no projects appear in the result with
        ``{"owned": 0, "member": 0}`` so the caller can splat
        the dict without an ``.get()`` guard per row.
        """
        out: dict[int, dict[str, int]] = {
            int(uid): {"owned": 0, "member": 0} for uid in user_ids
        }
        if not user_ids:
            return out
        placeholders = ",".join("?" * len(user_ids))
        with self._lock:
            conn = self._connect()
            try:
                # owned count — one row per (owner, project)
                owned_rows = conn.execute(
                    f"SELECT owner_id, COUNT(*) AS n "
                    f"FROM projects WHERE owner_id IN ({placeholders}) "
                    f"GROUP BY owner_id",
                    [int(uid) for uid in user_ids],
                ).fetchall()
                # member count — exclude own projects, count distinct
                # project_members rows (DISTINCT project_id would
                # also work but the (project_id, user_id) PK makes
                # it implicit).
                member_rows = conn.execute(
                    f"SELECT pm.user_id, COUNT(*) AS n "
                    f"FROM project_members pm "
                    f"JOIN projects p ON p.id = pm.project_id "
                    f"WHERE pm.user_id IN ({placeholders}) "
                    f"  AND p.owner_id != pm.user_id "
                    f"GROUP BY pm.user_id",
                    [int(uid) for uid in user_ids],
                ).fetchall()
            finally:
                conn.close()
        for r in owned_rows:
            out[int(r["owner_id"])] = {
                "owned": int(r["n"]),
                # owner never counts as a member of their own project
                "member": out[int(r["owner_id"])]["member"],
            }
        for r in member_rows:
            uid = int(r["user_id"])
            existing = out[uid]
            out[uid] = {
                "owned": existing["owned"],
                "member": int(r["n"]),
            }
        return out

    # ---------- project owner write API ----------

    def update_owner(self, project_id: int, new_owner_id: int) -> bool:
        """Reassign a project's owner.

        Returns True iff a project row was changed. Server-side
        chokepoint for the ``POST /projects/<id>/owner`` endpoint
        (7/22 RBAC business-lock principle). The route handler is the
        only caller; it enforces every policy check (system project
        is permanent, target user must exist + have the
        ``project_leader`` role, etc.) before reaching this method
        so the storage layer stays policy-agnostic and trivially
        unit-testable.

        Mirrors the ``with self._lock`` + ``_connect`` pattern of the
        other write APIs so concurrent writers (e.g. an admin and a
        manager issuing two reassignments in parallel) cannot race.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE projects SET owner_id = ? WHERE id = ?",
                    (int(new_owner_id), int(project_id)),
                )
                changed = cur.rowcount > 0
            finally:
                conn.close()
        if changed:
            logger.info(
                "project owner changed project_id=%s new_owner_id=%s",
                int(project_id), int(new_owner_id),
            )
        return changed

    # ---------- v0.9.1 project write: name / description (single chokepoint) ----------

    def update(
        self,
        project_id: int,
        name: str,
        description: str,
    ) -> bool:
        """Update name + description (server-side chokepoint, 7/22 business-level lock).

        Only the two user-facing fields are written. ``owner_id`` and
        ``project_type`` are intentionally not in the parameter list
        so a hand-crafted POST cannot mutate them (owner is reassigned
        via ``/owner`` v0.7.2b, project_type is permanent).
        ``created_at`` is preserved as the row's history anchor.
        Raises ``sqlite3.IntegrityError`` on a duplicate name so the
        route layer can surface a 200-rendered "name taken" error.

        The :meth:`update_owner` chokepoint (above) and this method
        are the only server-side writers of the ``projects`` table.
        Endpoint handlers must go through one of these two methods —
        a hand-crafted raw UPDATE is a 7/22 business-lock violation.
        """
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE projects "
                    "SET name = ?, description = ?, updated_at = ? "
                    "WHERE id = ?",
                    (str(name), str(description), now, int(project_id)),
                )
                changed = cur.rowcount > 0
            finally:
                conn.close()
        if changed:
            logger.info(
                "project updated id=%s name=%s",
                int(project_id), str(name),
            )
        return changed

    # ---------- project member write APIs ----------

    def add_member(
        self,
        project_id: int,
        user_id: int,
        custom_role_id: int | None = None,
    ) -> bool:
        """Insert a project_members row. Returns True on success.

        Server-side chokepoint for the "Add member" endpoint
        (7/22 RBAC business-lock principle). The route handler is the
        only caller; rank-based RBAC lives in the ``@require_role``
        decorator on the endpoint, not here, so the storage layer
        stays policy-agnostic and trivially unit-testable.

        v0.9.2 sub-task 7 — the per-project role model is now
        a single-tier FK into ``project_custom_roles``. The
        default ``custom_role_id=None`` is the **null role**
        case: the member is in the project but has no role
        (no inherited grants). The route layer is responsible
        for auto-resolving a default role from the target
        user's system rank if it wants to seed a non-null
        role on add.

        Raises ``sqlite3.IntegrityError`` when ``(project_id, user_id)``
        already exists (composite PK in the schema) so the route can
        surface a 200-rendered "already a member" error. The FK
        to ``project_custom_roles`` is checked at insert time so
        an unknown ``custom_role_id`` raises
        ``sqlite3.IntegrityError`` too.

        The membership cache used by :func:`user_can_see_project` is
        invalidated after a successful write so the next read sees the
        new state.
        """
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO project_members "
                    "(project_id, user_id, added_at, custom_role_id) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        int(project_id),
                        int(user_id),
                        now,
                        (
                            int(custom_role_id)
                            if custom_role_id is not None
                            else None
                        ),
                    ),
                )
            finally:
                conn.close()
        _invalidate_member_cache(int(project_id), int(user_id))
        logger.info(
            "project member added project_id=%s user_id=%s custom_role_id=%s",
            int(project_id), int(user_id), str(custom_role_id),
        )
        return True

    def remove_member(self, project_id: int, user_id: int) -> bool:
        """Delete a project_members row. Returns True iff a row was removed.

        Server-side chokepoint for the "Remove member" endpoint.
        The route handler is the only caller; RBAC lives in the
        ``@require_role`` decorator. Returns False when the row was
        already absent so the route can decide between a 302 (success)
        and a 404 (nothing to remove).

        The membership cache is invalidated on every call (success or
        not) so a future "what if alice was already not a member"
        branch does not return a stale True. See :meth:`add_member`
        for the cache invalidation rationale.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM project_members "
                    "WHERE project_id = ? AND user_id = ?",
                    (int(project_id), int(user_id)),
                )
                removed = cur.rowcount > 0
            finally:
                conn.close()
        _invalidate_member_cache(int(project_id), int(user_id))
        if removed:
            logger.info(
                "project member removed project_id=%s user_id=%s",
                int(project_id), int(user_id),
            )
        return removed

    # v0.9.3 — per-role CRUD + per-role node permission methods live
    # in feature_storage_roles (split from the deleted
    # feature_storage_node_permissions). set_member_role stays here
    # because it mutates project_members — same chokepoint as
    # add_member / remove_member.

    def set_member_role(
        self,
        project_id: int,
        user_id: int,
        custom_role_id: int | None,
    ) -> bool:
        """Set (or clear) the member's role assignment.

        v0.9.2 sub-task 6 -- server-side chokepoint for the
        per-member role assignment (the third step of the
        "create role → assign permissions → assign to member"
        flow). ``custom_role_id`` of ``None`` is the
        **null role** case: the member is in the project
        but has no role (no inherited grants). A non-None
        int must reference an existing row in
        ``project_custom_roles`` for the same project (the
        ``UNIQUE (project_id, name)`` constraint plus the FK
        chain guard against cross-project / missing rows).

        Returns ``True`` iff a row was changed. Returns
        ``False`` when the user is not a project member so the
        route can decide between 302 (success) and 404.

        The membership cache is invalidated after a successful
        write so the next read sees the new assignment.
        """
        with self._lock:
            conn = self._connect()
            try:
                if custom_role_id is None:
                    cur = conn.execute(
                        "UPDATE project_members SET custom_role_id = NULL "
                        "WHERE project_id = ? AND user_id = ?",
                        (int(project_id), int(user_id)),
                    )
                else:
                    # Cross-project / missing-row guard: the
                    # SELECT in the same statement ensures a
                    # hand-crafted POST that names a
                    # custom_role_id from a different project
                    # (or a non-existent id) gets a no-op.
                    cur = conn.execute(
                        "UPDATE project_members "
                        "SET custom_role_id = ? "
                        "WHERE project_id = ? AND user_id = ? "
                        "AND (custom_role_id = ? OR "
                        "     EXISTS (SELECT 1 FROM project_custom_roles "
                        "             WHERE id = ? AND project_id = ?))",
                        (
                            int(custom_role_id),
                            int(project_id),
                            int(user_id),
                            int(custom_role_id),
                            int(custom_role_id),
                            int(project_id),
                        ),
                    )
                changed = cur.rowcount > 0
            finally:
                conn.close()
        if changed:
            _invalidate_member_cache(int(project_id), int(user_id))
            logger.info(
                "project member custom_role updated project_id=%s user_id=%s "
                "custom_role_id=%s",
                int(project_id), int(user_id),
                str(custom_role_id),
            )
        return changed

    # ---------- Feature Board (per-project kanban) ----------
    # The four feature methods live in feature_storage_features
    # for line-budget hygiene. They are installed via the
    # bottom side-effect import. project_features DDL stays
    # in ``_SCHEMA_SQL`` above.

    # ---------- project_nodes (v0.9.2 — 6-level tree) ----------
    # The seven node methods live in feature_storage_nodes for
    # line-budget hygiene. They are installed via the bottom
    # side-effect import. project_nodes DDL lives in
    # feature_storage_ddl_v092._V092_DDL.

# ---------- module-level helpers (internal) ----------

def _now_iso() -> str:
    """ISO 8601 UTC timestamp with microsecond + nanosecond suffix for uniqueness."""
    secs, ns = divmod(time.time_ns(), 1_000_000_000)
    base = _dt.datetime.fromtimestamp(secs, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ns:09d}Z"

def _normalise_project_type(value: str) -> str:
    """Return the canonical project-type literal for ``value``.

    Whitelist of ``{"common", "system"}``; anything else (including
    the incoming ``"user"`` value) falls back to ``"common"`` so a
    malformed caller (a future route, a test that forgets the new
    field, a manually-edited DB) still gets a row the rest of the app
    can render without crashing. The system literal is reserved for
    the bootstrap path (:meth:`create_system_project_if_missing`);
    the create route rejects a hand-crafted ``project_type=system``
    POST with 400 before this helper runs, so a caller cannot smuggle
    a system row through the form.
    """
    text = str(value or "").strip().lower()
    if text == _PROJECT_TYPE_SYSTEM:
        return _PROJECT_TYPE_SYSTEM
    return _PROJECT_TYPE_COMMON

# ---------- RBAC helpers (server-side, 7/22 business-level lock) ----------
# v0.7.1: auto-own check + membership cache live in
# feature_storage_rbac and are re-exported at the top of this file.
# v0.9.7p1: dropped the dead _get_project_role alias (0 caller).

def user_can_see_project(user, project, is_admin: bool) -> bool:
    """Read-side RBAC: may ``user`` see ``project``?

    * admin / manager → always
    * owner → always
    * member → always
    * anyone else → False (caller maps False to 404 — never leak existence)

    v0.7.1: T0/T1 are now uniformly treated via ``_is_auto_own`` so
    a manager (T1) sees every project without needing the legacy
    ``role == 'manager'`` string check; that string check stays in
    place as a belt-and-braces guard for any code path that has not
    yet been updated to populate ``user.rank``.
    """
    if _is_auto_own(user):
        return True
    if bool(is_admin):
        return True
    if project.owner_id == user.id:
        return True
    return _is_member_cached(project.id, user.id)

def require_owner_or_admin(user, project, is_admin: bool) -> None:
    """Write-side RBAC: raise ``PermissionError`` if not owner or admin/manager.

    The ``is_admin`` boolean passed by the caller is supplemented with
    a role-string check so a caller that only knows the ``is_admin``
    flag still grants manager access without an in-lock-step update.
    System projects are gated separately by the ``is_system`` check in
    the route handler.

    Caller maps PermissionError to 403.
    """
    is_admin_or_manager = bool(is_admin) or _is_auto_own(user)
    if is_admin_or_manager:
        return
    if project.owner_id != user.id:
        raise PermissionError(
            f"user_id={user.id} is not owner of project_id={project.id} "
            f"(and not admin/manager)"
        )

def can_manage_members(user, project) -> bool:
    """Owner-based gate for project member add/remove.

    * admin / manager → always (they auto-own every project)
    * owner → always (their own project)
    * anyone else → False

    Returns False for a ``None`` user so a defensive caller that
    forgot the ``@require_auth`` decorator still fails closed.

    v0.7.1: T0/T1 detection goes through ``_is_auto_own`` so the
    legacy ``role in (ADMIN, MANAGER)`` string check is no longer
    the source of truth.
    """
    if user is None or project is None:
        return False
    if _is_auto_own(user):
        return True
    return int(user.id) == int(project.owner_id)

# The membership-cache helpers live in feature_storage_rbac
# and are re-exported at the top of this file.

# v0.9.2 — install split-out methods onto ProjectStorage. The
# modules also self-install on import; the explicit calls below are
# a belt-and-braces guard against a future reorder of the import
# chain. v0.9.3: per-(user, node) installer dropped with the
# feature_storage_node_permissions module.
from .feature_storage_nodes import install_node_methods  # noqa: E402, F401
from .feature_storage_roles import install_role_methods  # noqa: E402, F401
from .feature_storage_features import install_feature_methods  # noqa: E402, F401
from .feature_storage_migrations import install_migration_methods  # noqa: E402, F401
from .feature_storage_bootstrap import install_bootstrap_methods  # noqa: E402, F401

install_node_methods()
install_role_methods()
install_feature_methods()
install_migration_methods()
install_bootstrap_methods()

__all__ = [
    "ProjectRow",
    "FeatureRow",
    "ProjectStorage",
    "user_can_see_project",
    "require_owner_or_admin",
    "can_manage_members",
]
