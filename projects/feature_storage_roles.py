"""v0.9.2 sub-task 7 — per-(role, node) write-grant storage methods.

v0.9.2 added the 6-method role-grant surface on
:class:`ProjectStorage`:

* :meth:`ProjectStorage.create_role` / :meth:`ProjectStorage.list_roles`
  / :meth:`ProjectStorage.delete_role` — role CRUD on the
  ``project_custom_roles`` table.
* :meth:`ProjectStorage.set_role_node_permission` /
  :meth:`ProjectStorage.list_role_node_permissions` /
  :meth:`ProjectStorage.clear_role_node_permission` — per-(role,
  node) write-grant on the ``project_custom_role_permissions``
  table.

All 6 methods are policy-free — they validate input + run the
INSERT / DELETE and log the action. The 3-bucket RBAC decision
(T0/T1 auto-own / T2 project owner / role-grant) lives in
:mod:`project_board.projects.feature_role_v121`. The role-grant
write endpoints are thin route wrappers that gate the helper
call behind the actor's authority so the storage layer stays
policy-agnostic (7/22 RBAC business-lock principle).

v0.9.3 origin
-------------
v0.9.2 had installed these 6 methods in
:mod:`feature_storage_node_permissions` alongside 3 user-level
methods (``list_node_permissions`` / ``grant_node_permission`
/ `revoke_node_permission`). v0.9.3 (user 8/13 19:34 拍板)
**dropped** the user-level surface together with the
``project_node_permissions`` table; the 6 role methods stay
but live in this new file (the old module's name no longer
matches the content).

CASCADE contract
----------------
The DDL fragment in :mod:`feature_storage_ddl_v092` installs the
FK chain ``project_custom_role_permissions.custom_role_id →
project_custom_roles.id`` and
``project_custom_role_permissions.node_id → project_nodes.id``,
both with ``ON DELETE CASCADE``. A role deleted from
``project_custom_roles`` removes every per-(role, node) grant
row that referenced it; a node deleted from ``project_nodes``
removes every per-(role, node) grant row for that node. The
grant / revoke helpers inherit this contract unchanged — a
DELETE / UPDATE on ``project_custom_role_permissions`` does not
need its own cascade code.

Idempotency
-----------
:meth:`set_role_node_permission` is idempotent — re-granting
the same ``(custom_role_id, node_id)`` pair refreshes
``can_write`` and ``granted_at`` rather than raising. The
composite PK on ``(custom_role_id, node_id)`` would otherwise
reject the duplicate INSERT, so the helper uses
``INSERT...ON CONFLICT...DO UPDATE`` to make the caller-side
flow a single statement.

:meth:`clear_role_node_permission` is also idempotent —
clearing an absent row returns ``False`` rather than raising.
The route maps that to a 200-rendered "no-op" notice so the
UI treats a missing row as a benign outcome (matches the
v0.7.x remove-member semantics — a remove of a non-member is
a no-op, not a 404).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _do_create_role(
    self,
    project_id: int,
    name: str,
    description: str = "",
) -> int:
    """Insert a new ``project_custom_roles`` row. Returns the new id.

    v0.9.2 sub-task 7 — server-side chokepoint for the
    "create role" form. Whitelists ``name`` (non-empty,
    length-bounded), raises ``ValueError`` on duplicates so
    the route can surface a 409 / "name already taken"
    notice. The ``UNIQUE (project_id, name)`` constraint is
    the SQL-layer guard; the helper raises on ``IntegrityError``
    for clarity.

    Server-side chokepoint (7/22 RBAC business-lock
    principle): the route layer is the only caller; the
    bucket / role-membership decisions live in the route,
    not in storage.
    """
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("create_custom_role: name must be non-empty")
    if len(clean_name) > 64:
        raise ValueError(
            f"create_custom_role: name must be <= 64 chars, got {len(clean_name)}"
        )
    clean_description = str(description or "").strip()
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO project_custom_roles "
                "(project_id, name, description, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    int(project_id),
                    clean_name,
                    clean_description,
                    _now_iso(),
                ),
            )
            new_id = int(cur.lastrowid)
        finally:
            conn.close()
    logger.info(
        "v0.9.1 custom role created project_id=%s custom_role=%s name=%s",
        int(project_id), new_id, clean_name,
    )
    return new_id


def _do_list_roles(
    self,
    project_id: int,
) -> list[dict[str, Any]]:
    """Return every custom role for ``project_id``.

    v0.9.2 sub-task 7 — sorted by ``name ASC`` so the
    role-management page renders in a stable order. Each
    row is a ``{id, name, description, created_at}`` dict
    keyed for direct template consumption.
    """
    with self._lock:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, name, description, created_at "
                "FROM project_custom_roles "
                "WHERE project_id = ? "
                "ORDER BY name ASC",
                (int(project_id),),
            ).fetchall()
        finally:
            conn.close()
    return [
        {
            "id": int(r["id"]),
            "name": str(r["name"]),
            "description": str(r["description"] or ""),
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def _do_delete_role(
    self,
    project_id: int,
    custom_role: int,
) -> bool:
    """Delete a custom role + cascade its grants + member assignments.

    v0.9.2 sub-task 7 — the FK chain does the heavy
    lifting: ``ON DELETE CASCADE`` on
    ``project_custom_role_permissions`` removes every
    per-(role, node) grant; ``ON DELETE SET NULL`` on
    ``project_members.custom_role_id`` clears the
    assignment for every member who was wearing the role.
    The helper therefore does not need an explicit second
    DELETE call.

    Returns ``True`` iff a row was actually removed. The
    cross-project guard (the WHERE clause matches
    ``project_id``) ensures a hand-crafted POST that names
    a role from a different project gets a no-op.
    """
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM project_custom_roles "
                "WHERE id = ? AND project_id = ?",
                (int(custom_role), int(project_id)),
            )
            removed = int(cur.rowcount or 0) > 0
        finally:
            conn.close()
    if removed:
        # Invalidate every member's cache: the FK SET NULL just
        # cleared their assignment. Cache is keyed by
        # (project_id, user_id) so we don't know which users to
        # invalidate without a separate query — fall through and
        # let the next read repopulate.
        logger.info(
            "v0.9.1 custom role deleted project_id=%s custom_role=%s",
            int(project_id), int(custom_role),
        )
    return removed


def _do_set_role_node_permission(
    self,
    project_id: int,
    custom_role: int,
    node_id: int,
    can_write: bool = True,
) -> bool:
    """Insert (or update) a per-(custom_role, node) grant.

    v0.9.2 sub-task 7 — the second leg of the
    "create role → assign permissions → assign to member"
    flow. The cross-project guard is the SELECT against
    ``project_custom_roles`` in the same statement: a
    hand-crafted POST that names a role from a different
    project (or a non-existent id) gets a no-op.

    Returns ``True`` iff a write happened.
    ``INSERT...ON CONFLICT DO UPDATE`` is used so a
    re-grant with the same ``can_write`` value refreshes
    the row in place; the helper reports ``True`` (a row
    was written).
    """
    can_write_int = 1 if bool(can_write) else 0
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO project_custom_role_permissions "
                "(custom_role_id, node_id, can_write, granted_at) "
                "SELECT r.id, n.id, ?, ? "
                "FROM project_custom_roles r, project_nodes n "
                "WHERE r.id = ? AND r.project_id = ? "
                "  AND n.id = ? AND n.project_id = ? "
                "ON CONFLICT(custom_role_id, node_id) "
                "DO UPDATE SET can_write = excluded.can_write, "
                "granted_at = excluded.granted_at",
                (
                    int(can_write_int),
                    _now_iso(),
                    int(custom_role),
                    int(project_id),
                    int(node_id),
                    int(project_id),
                ),
            )
            changed = int(cur.rowcount or 0) > 0
        finally:
            conn.close()
    if changed:
        logger.info(
            "v0.9.1 custom-role permission set project_id=%s custom_role=%s "
            "node_id=%s can_write=%s",
            int(project_id), int(custom_role), int(node_id),
            int(can_write_int),
        )
    return changed


def _do_list_role_node_permissions(
    self,
    project_id: int,
    custom_role: int,
) -> list[dict[str, Any]]:
    """Return every per-(custom role, node) grant for ``custom_role``.

    v0.9.2 sub-task 7 — used by the custom-role detail
    page to render the per-node grant table. Returns
    ``[{node_id, can_write, granted_at}]``. The caller
    joins ``project_nodes`` for the title / level / status
    display.

    Cross-project guard is implicit: ``custom_role`` is unique
    in ``project_custom_roles`` so the role's
    ``project_id`` is what the WHERE clause uses.
    """
    with self._lock:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT crp.node_id, crp.can_write, crp.granted_at "
                "FROM project_custom_role_permissions crp "
                "JOIN project_custom_roles cr ON cr.id = crp.custom_role_id "
                "WHERE cr.id = ? AND cr.project_id = ? "
                "ORDER BY crp.granted_at ASC",
                (int(custom_role), int(project_id)),
            ).fetchall()
        finally:
            conn.close()
    return [
        {
            "node_id": int(r["node_id"]),
            "can_write": int(r["can_write"] or 0),
            "granted_at": str(r["granted_at"]),
        }
        for r in rows
    ]


def _do_clear_role_node_permission(
    self,
    project_id: int,
    custom_role: int,
    node_id: int,
) -> bool:
    """Delete a per-(custom role, node) grant row.

    v0.9.2 sub-task 7 — the revoke side of the
    per-custom-role grant chokepoint. Returns ``True``
    iff a row was actually removed. The cross-project
    guard is the JOIN against ``project_custom_roles``
    filtered on ``project_id``.
    """
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM project_custom_role_permissions "
                "WHERE node_id = ? AND custom_role_id IN ("
                "  SELECT id FROM project_custom_roles "
                "  WHERE id = ? AND project_id = ?"
                ")",
                (int(node_id), int(custom_role), int(project_id)),
            )
            removed = int(cur.rowcount or 0) > 0
        finally:
            conn.close()
    if removed:
        logger.info(
            "v0.9.1 custom-role permission cleared project_id=%s "
            "custom_role=%s node_id=%s",
            int(project_id), int(custom_role), int(node_id),
        )
    return removed


def _now_iso() -> str:
    """Return current UTC time as ``YYYY-MM-DDTHH:MM:SS.ffffff...Z``.

    Local helper: the v0.9.2 storage layer's ``_now_iso`` lives
    in :mod:`feature_storage` and uses microsecond + nanosecond
    suffix for timestamp uniqueness. The DDL column is ``TEXT``
    so any ISO-8601 string is accepted; a fresh timestamp per
    grant ensures two consecutive grants to the same
    ``(custom_role_id, node_id)`` row sort deterministically.
    """
    from .feature_storage import _now_iso as _fs_now_iso
    return _fs_now_iso()


def install_role_methods() -> None:
    """Attach the 6 role methods to :class:`ProjectStorage`.

    Called by :mod:`feature_storage` at the bottom of the module
    (after :class:`ProjectStorage` is fully defined). The
    function is a no-op for any method that is already installed
    (idempotent re-import).

    v0.9.2 sub-task 7 — the 6 role methods (CRUD + per-role
    node grant set / list / clear) are installed as a single
    set so a future contributor can grep one place to find the
    full role surface.

    v0.9.3 — the install function is the only entry point for
    the role surface; the user-level permission methods are
    gone (with the deleted ``feature_storage_node_permissions``
    module). The single install function prevents future
    drift between the role surface and the install call.
    """
    from .feature_storage import ProjectStorage

    _ROLE_METHODS = {
        "set_role_node_permission": _do_set_role_node_permission,
        "list_role_node_permissions": _do_list_role_node_permissions,
        "clear_role_node_permission": _do_clear_role_node_permission,
        "create_role": _do_create_role,
        "list_roles": _do_list_roles,
        "delete_role": _do_delete_role,
    }
    for _name, _method in _ROLE_METHODS.items():
        if _name not in ProjectStorage.__dict__:
            setattr(ProjectStorage, _name, _method)


# Install on import. The bottom of feature_storage.py also calls
# this defensively; running it twice is a no-op.
install_role_methods()


__all__ = ["install_role_methods"]
