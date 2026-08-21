"""SQLite storage layer for users and server-side sessions.

Single chokepoint for all DB writes (7/22 RBAC business-lock principle):
- Every write goes through this module
- Callers (routes, decorators) never run SQL directly
- All SQL strings are parameterised — no string concatenation of user input

v0.7.1 schema notes
-------------------
The ``users`` table grew a ``rank`` column (INTEGER NOT NULL DEFAULT 4) —
the new T-scale (0=admin/T0 .. 4=user/T4). The pre-existing ``role``
column is kept for backward compatibility and the v0.7.1 migration
(:mod:`project_board.accounts.feature_migrate_v071`) back-fills ``rank``
from the existing ``role`` value. The legacy ``role`` column is no
longer written by any storage method; ``rank`` is the single source
of truth for all authority decisions (v0.9.2 sub-task 3).
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .feature_user_model import User
from ..rbac.feature_role import (
    ADMIN, MANAGER, PROJECT_LEADER, TEAM_LEADER, USER,
    rank_for_role,
)

logger = logging.getLogger(__name__)

# v0.7.1: ``rank`` column added. ``DEFAULT 4`` (T4 = user) so a row
# written by a code path that hasn't yet been updated to set rank still
# gets a sensible value. ``role`` column kept for backward compat.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user',
    rank          INTEGER NOT NULL DEFAULT 4,
    created_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    sid         TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    expires_at  TEXT    NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_users_username   ON users(username);
"""


# v0.9.2 sub-task 3 — ``_LEGACY_ROLE_FOR_RANK`` retired. The legacy
# ``role`` column is no longer written by any storage method; rank is
# the single source of truth. The canonical role → rank table lives in
# :mod:`project_board.rbac.feature_role` and is the one place the
# reverse direction (``rank_for_role``) is defined.


class UserStorage:
    """Thread-safe SQLite wrapper for users + sessions.

    Each public method opens a short-lived connection guarded by a lock so
    concurrent Flask request workers do not collide on the underlying file.
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
        """Create tables, indexes, and the v0.7.1 ``rank`` column if absent.

        The ``rank`` column is added in an idempotent ``ALTER TABLE`` step
        guarded by an ``OperationalError`` check on the "duplicate column"
        message — the standard SQLite idiom for an "ADD COLUMN if missing"
        operation (SQLite has no native ``IF NOT EXISTS`` for columns).
        Migration of the column *values* is handled separately by
        :mod:`project_board.accounts.feature_migrate_v071` so this method
        stays a pure DDL function.
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA_SQL)
                try:
                    conn.execute(
                        "ALTER TABLE users ADD COLUMN "
                        "rank INTEGER NOT NULL DEFAULT 4"
                    )
                    logger.info(
                        "users schema migrated: added rank column (v0.7.1)"
                    )
                except sqlite3.OperationalError as exc:
                    # "duplicate column name: rank" is the steady-state
                    # signal — fresh installs and post-migration DBs both
                    # hit it. Anything else (table missing, lock failure)
                    # is re-raised so the caller sees a real error.
                    if "duplicate column" not in str(exc).lower():
                        raise
                logger.info("storage schema initialised at %s", self._db_path)
            finally:
                conn.close()

    # ---------- users ----------

    def create_user(self, username: str, password_hash: str, rank: int) -> int:
        """Insert a user. Returns the new id. Raises sqlite3.IntegrityError
        on duplicate username so callers can surface a 409.

        v0.9.2 sub-task 3 (Full RBAC 迁 rank) -- rank-based write. The signature now takes
        a T-scale ``rank`` (0=admin/T0 .. 4=user/T4) instead of a role
        string. The legacy ``role`` column is **not** written here — it
        stays whatever it was (typically NULL after the v0.9.1 role-
        deprecate migration). All authority decisions go through
        ``User.rank``; ``User.role`` is read-only legacy.

        Validates ``rank`` against the 0..4 set; unknown values raise
        ``ValueError`` so the caller fails loud rather than silently
        creating a user with a meaningless rank.
        """
        if not isinstance(rank, int) or rank not in (0, 1, 2, 3, 4):
            raise ValueError(
                f"create_user: rank must be in {{0, 1, 2, 3, 4}}, got {rank!r}"
            )
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash, rank, "
                    "created_at) VALUES (?, ?, ?, ?)",
                    (username, password_hash, int(rank), now),
                )
                new_id = int(cur.lastrowid)
                logger.info(
                    "user created id=%s username=%s rank=%s",
                    new_id, username, int(rank),
                )
                return new_id
            finally:
                conn.close()

    def find_by_username(self, username: str) -> Optional[User]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT id, username, password_hash, role, rank, "
                    "created_at FROM users WHERE username = ?",
                    (username,),
                ).fetchone()
                return User.from_row(row) if row is not None else None
            finally:
                conn.close()

    def find_by_id(self, user_id: int) -> Optional[User]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT id, username, password_hash, role, rank, "
                    "created_at FROM users WHERE id = ?",
                    (int(user_id),),
                ).fetchone()
                return User.from_row(row) if row is not None else None
            finally:
                conn.close()

    def find_usernames_by_ids(
        self, user_ids: list[int],
    ) -> dict[int, Optional[str]]:
        """Return ``{user_id: username or None}`` for every id in ``user_ids``.

        v0.9.2 sub-task 8 (perf 9 ops) -- N+1 to 1 query for the /projects
        owner-name lookup. The previous shape was one
        ``find_by_id`` per owner (which loads the password hash +
        every other column even though the caller only needs
        the username); this batch helper returns just the
        ``username`` column in a single SELECT, indexed by id.
        Empty ``user_ids`` short-circuits to ``{}`` (no SQL).
        """
        out: dict[int, Optional[str]] = {int(uid): None for uid in user_ids}
        if not user_ids:
            return out
        placeholders = ",".join("?" * len(user_ids))
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT id, username FROM users WHERE id IN ({placeholders})",
                    [int(uid) for uid in user_ids],
                ).fetchall()
            finally:
                conn.close()
        for r in rows:
            out[int(r["id"])] = str(r["username"])
        return out

    def list_all_users(self) -> list[User]:
        """Return every user in id order. Powers the /users list page.

        Read-side helper for the project-level project_leader / platform
        admin user directory. No filtering — the route handler decides
        who is allowed to call this (RBAC is enforced in the
        ``@require_role`` decorator upstream, not here).
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT id, username, password_hash, role, rank, "
                    "created_at FROM users ORDER BY id ASC"
                ).fetchall()
                return [User.from_row(r) for r in rows]
            finally:
                conn.close()

    def count_users_by_role(self, role: str) -> int:
        """Count users whose rank matches ``role``.

        v0.9.2 sub-task 3 — query filters on ``rank`` (the canonical
        T-scale) rather than the deprecated ``role`` column, so the
        count is correct even after a role-deprecate migration that
        left ``role`` NULL for fresh rows.

        Seeders use this to detect "is there already a user with this
        role in the DB" without re-implementing the COUNT(*) query.
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE rank = ?",
                    (int(_rank_for_role(role)),),
                ).fetchone()
                return int(row["n"]) if row is not None else 0
            finally:
                conn.close()

    def update_role(self, user_id: int, new_role: str) -> bool:
        """Promote/demote a user via the role-change endpoint.

        Server-side chokepoint (7/22 RBAC business-lock principle):
        ``new_role`` must be one of the downgradable roles
        ``(MANAGER, PROJECT_LEADER, TEAM_LEADER, USER)``.
        This is the *only* storage-level write API the role-change route
        uses; the route handler enforces the per-actor RBAC matrix and then
        delegates here.

        v0.9.2 sub-task 6 — rank-based write. The ``role`` column is
        deprecated; only ``rank`` is written. The signature still takes
        a role string for backward compatibility with callers, but the
        rank is what ends up in the DB.

        Hard rule: ``new_role`` MUST be one of
        ``(MANAGER, PROJECT_LEADER, TEAM_LEADER, USER)``. Granting ``ADMIN``
        is rejected with ``ValueError`` because the admin role is permanent
        — it can only originate from the config-seed bootstrap path
        (``ensure_admin_exists``) and never from a runtime role-change
        request. Even the admin user cannot promote another user to admin
        via this method.

        Returns True iff a row was changed. Unknown role strings fall
        through to the same ValueError so callers fail closed.
        """
        allowed = (MANAGER, PROJECT_LEADER, TEAM_LEADER, USER)
        if new_role not in allowed:
            # Reject ADMIN explicitly with the rationale spelled out; any
            # other unknown string is rejected the same way to keep the
            # contract "this method only assigns the downgradable roles"
            # simple to reason about.
            raise ValueError(
                f"update_role: refused to assign role {new_role!r}; "
                f"admin is permanent, allowed roles are {allowed}"
            )
        new_rank = _rank_for_role(new_role)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE users SET rank = ? WHERE id = ?",
                    (int(new_rank), int(user_id)),
                )
                changed = cur.rowcount > 0
                if changed:
                    logger.info(
                        "user id=%s rank -> %s (via update_role role=%s)",
                        int(user_id), int(new_rank), new_role,
                    )
                return changed
            finally:
                conn.close()

    def set_rank_by_id(self, user_id: int, new_rank: int) -> bool:
        """Set a user's rank directly by id. The rank-based replacement
        for ``update_role``; new code should prefer this API.

        Validates ``new_rank`` against the 0..4 T-scale. ``ADMIN`` (0)
        is allowed here because this is the *direct* write path; the
        "admin permanent" rule is enforced at the route layer
        (:func:`feature_user_role._can_change_rank`), not here. The
        bootstrap path (``ensure_admin_exists``) also uses this method.

        Returns True iff a row was changed.
        """
        if not isinstance(new_rank, int) or new_rank not in (0, 1, 2, 3, 4):
            raise ValueError(
                f"set_rank_by_id: rank must be in {{0, 1, 2, 3, 4}}, got {new_rank!r}"
            )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE users SET rank = ? WHERE id = ?",
                    (int(new_rank), int(user_id)),
                )
                changed = cur.rowcount > 0
                if changed:
                    logger.info(
                        "user id=%s rank -> %s (via set_rank_by_id)",
                        int(user_id), int(new_rank),
                    )
                return changed
            finally:
                conn.close()

    def set_role_admin(self, user_id: int) -> bool:
        """Bootstrap-only: set a user's rank to 0 (T0 = admin).

        This is the *one* path that may write the admin rank after the
        initial schema seed — used exclusively by ``ensure_admin_exists``
        to recover an admin row that was downgraded (e.g. by a manual SQL
        edit or a future bug). The runtime rank-change endpoint
        (``/users/<id>/rank``) never calls this; that endpoint uses
        :meth:`set_rank_by_id` which goes through the route's RBAC
        matrix (admin target is permanent).

        v0.9.2 sub-task 3: now delegates to :meth:set_rank_by_id so the
        bootstrap path and the runtime path cannot drift; the legacy
        ``role`` column is no longer written anywhere.

        Do not call from route handlers. The leading verb in the name and
        the dedicated docstring are intentional so a future contributor
        reading ``grep -n set_role_admin`` sees "bootstrap only".
        """
        changed = self.set_rank_by_id(int(user_id), 0)
        if changed:
            logger.warning(
                "bootstrap set_role_admin id=%s (admin-only path)",
                int(user_id),
            )
        return changed

    def update_password(self, user_id: int, new_password_hash: str) -> bool:
        """Re-hash and update a user's password. Returns True if a row was changed.

        Used by the admin-seed sync path when ADMIN_PASSWORD changes in config.yaml.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (new_password_hash, int(user_id)),
                )
                changed = cur.rowcount > 0
                if changed:
                    logger.info("user id=%s password updated", int(user_id))
                return changed
            finally:
                conn.close()

    def set_username(self, user_id: int, new_username: str) -> bool:
        """Rename a user. Returns True iff a row was changed.

        Server-side chokepoint (7/22 RBAC business-lock principle).
        Used by the bootstrap migration path to rename the older bootstrap
        usernames (``leader`` → ``manager``, ``mavis`` → ``project_leader``)
        so existing deployments can upgrade in place.

        This is the *only* storage-level write API that mutates a row's
        username. The role-change route never calls it — username renames
        are bootstrap-only, not user-driven. The lock + ``_connect`` pattern
        matches the other write APIs so concurrent seeders don't race.

        Raises ``sqlite3.IntegrityError`` if ``new_username`` is already
        taken so the caller can surface a 409 / retry-with-different-name.
        """
        if not new_username:
            raise ValueError("set_username: new_username must be non-empty")
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE users SET username = ? WHERE id = ?",
                    (str(new_username), int(user_id)),
                )
                changed = cur.rowcount > 0
                if changed:
                    logger.info(
                        "user renamed user_id=%s new_username=%s",
                        int(user_id), new_username,
                    )
                return changed
            finally:
                conn.close()

    def count_admins(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                # v0.7.1: check rank (the new T-scale) for T0 = admin.
                # The legacy role column is kept in sync by update_role
                # and set_role_admin so the count matches either way;
                # rank is preferred because it is the v0.7.1 source of
                # truth.
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE rank = 0"
                ).fetchone()
                return int(row["n"]) if row is not None else 0
            finally:
                conn.close()

    def count_users(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
                return int(row["n"]) if row is not None else 0
            finally:
                conn.close()

    # ---------- sessions ----------

    def create_session(self, sid: str, user_id: int, expires_at: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO sessions (sid, user_id, expires_at) VALUES (?, ?, ?)",
                    (sid, int(user_id), expires_at),
                )
                logger.info("session created sid=%s user_id=%s", sid, int(user_id))
            finally:
                conn.close()

    def get_session(self, sid: str) -> Optional[tuple[int, str]]:
        """Return (user_id, expires_at) or None. Expired rows are deleted lazily."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT user_id, expires_at FROM sessions WHERE sid = ?",
                    (sid,),
                ).fetchone()
                if row is None:
                    return None
                expires_at = str(row["expires_at"])
                if _is_expired(expires_at):
                    conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
                    return None
                return int(row["user_id"]), expires_at
            finally:
                conn.close()

    def delete_session(self, sid: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
            finally:
                conn.close()


# ---------- module-level helpers (internal) ----------


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with microsecond + nanosecond suffix for uniqueness."""
    secs, ns = divmod(time.time_ns(), 1_000_000_000)
    base = _dt.datetime.fromtimestamp(secs, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ns:09d}Z"


def _is_expired(expires_at: str) -> bool:
    """Lexicographic compare is safe because the format is fixed-width ISO-8601 UTC."""
    return expires_at <= _now_iso()


def _rank_for_role(role: str) -> int:
    """Map a v0.7.0 role string to the v0.7.1 T-scale rank (0-4).

    v0.9.2 sub-task 3 (Full RBAC 迁 rank) -- thin wrapper around
    :func:`rbac.feature_role.rank_for_role` so the rank table has a
    single source of truth. An unknown role is mapped to T4 (user) so
    the row stays usable; the public write APIs raise ValueError on
    unknown roles long before this helper runs.
    """
    return rank_for_role(role)


__all__ = ["UserStorage"]
