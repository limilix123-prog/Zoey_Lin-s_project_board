"""v0.9.2 — :class:`ProjectStorage` node methods split-out.

The seven ``project_nodes`` methods — ``create_node``, ``find_node_by_id``,
``list_children``, ``list_tree``, ``get_tree``, ``update_node``,
``move_node``, ``delete_node`` — live here rather than in
:mod:`project_board.projects.feature_storage` so the latter stays
under the 1000-line cleancode threshold. The methods are attached
to :class:`ProjectStorage` at import time via
:func:`install_node_methods` below so the public API
(``storage.create_node(...)`` etc.) is unchanged when called from
the v0.9.3 board route layer.

6-level invariant
-----------------
* ``level`` must be in ``[1, 6]`` (server-side ``ValueError``)
* a new node's ``parent_id`` must belong to the same
  ``project_id`` (server-side ``ValueError``)
* the new node's depth (= ``parent.level + 1``) must be ≤ 6
  (server-side ``ValueError``); a chain of 6 levels is OK
  (``1→2→3→4→5→6``), inserting a level-7 child of a level-6
  parent fails.
* the FK on ``parent_id`` plus the ``ON DELETE CASCADE`` clause
  take care of the rest (an unknown parent raises
  ``sqlite3.IntegrityError``; deleting a node removes its
  subtree).

The status whitelist (``backlog`` / ``in_progress`` / ``done`` /
``archived``) is shared with the legacy :mod:`feature_storage`
feature methods so a hybrid board can render rows from both tables
under the same column logic in v0.9.3.

v0.9.2 vs v0.9.4 split
----------------------
The permission helpers (``grant`` / ``revoke`` / ``can_write_node``)
land in :mod:`feature_node_permissions` in sub-task 2 (完整权限设计).
The v0.9.2 storage layer is intentionally policy-free — the
``project_node_permissions`` table is created in v0.9.2 (empty
schema) so the FK chain is installed in one shot; no grant /
revoke code lives in this module.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)


# v0.9.2 — 6-level tree cap. Centralised here so the magic
# number never appears twice. The CHECK constraint in
# ``_V092_DDL`` enforces the same bound at the SQL level.
MAX_NODE_LEVEL: int = 6

# v0.9.2 — status whitelist. Same 4 literals as the legacy
# ``project_features`` table; enforced at SQL by the CHECK
# clause and at storage by the ``_clean_status`` helper below.
# A hand-crafted POST that smuggles status='unknown' raises
# ValueError (route maps to 400) — same UX as the legacy board.
_NODE_STATUSES: frozenset[str] = frozenset(
    {"backlog", "in_progress", "done", "archived"}
)


def _clean_name(name: str) -> str:
    """Return the trimmed name; raise ``ValueError`` if empty.

    Mirrors the legacy ``create_feature`` trim + check so the
    behaviour is identical between the two surfaces.
    """
    clean = str(name or "").strip()
    if not clean:
        raise ValueError("node name is required")
    return clean


def _clean_status(status: str) -> str:
    """Return the lowercased, validated status literal.

    Defaults to ``"backlog"`` when the caller passes a falsy value
    so the route layer can pass an empty form field without a
    pre-check. Raises ``ValueError`` on any unknown literal so the
    route can surface a 400 instead of planting an unrenderable
    row.
    """
    text = str(status or "backlog").strip().lower()
    if text not in _NODE_STATUSES:
        raise ValueError(f"invalid status: {text!r}")
    return text


def _row_to_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict (so callers can
    introspect without touching sqlite3.Row semantics)."""
    return {key: row[key] for key in row.keys()}


def _do_create_node(
    self,
    project_id: int,
    parent_id: Optional[int],
    level: int,
    name: str,
    description: str,
    status: str = "backlog",
) -> int:
    """Insert a ``project_nodes`` row. Returns the new id.

    Server-side chokepoint for the v0.9.3 "add node" endpoint.
    Validates the 6-level invariant + parent-chain depth + status
    whitelist before any INSERT so a hand-crafted POST cannot
    plant a row the rest of the app cannot render. ``level`` is
    authoritative for the storage layer (the route may compute
    it from ``parent.level + 1`` or pass it explicitly; this
    method trusts the value but verifies the chain).

    ``position`` defaults to ``0`` because the v0.9.2 UI does
    not yet expose an ordering control; the board view sorts
    by ``(parent_id, position, created_at)`` so the position
    field is reserved for a future patch.

    Raises
    ------
    ValueError
        * empty name
        * level ∉ [1, 6]
        * unknown status
        * ``parent_id`` belongs to a different project
        * ``parent.level + 1 != level`` (chain consistency)
    sqlite3.IntegrityError
        * unknown ``parent_id`` (FK violation)
    """
    # Local imports keep the cycle soft: this module is imported
    # by feature_storage at module-body level, so any module-level
    # reference would resolve before the constant exists. A
    # function-body import resolves lazily on the first call.
    from .feature_storage import _now_iso

    clean_name = _clean_name(name)
    clean_status = _clean_status(status)
    clean_level = int(level)
    if clean_level < 1 or clean_level > MAX_NODE_LEVEL:
        raise ValueError(
            f"invalid level: {clean_level!r}; "
            f"must be in [1, {MAX_NODE_LEVEL}]"
        )

    with self._lock:
        conn = self._connect()
        try:
            # If parent_id is given, verify it belongs to the
            # same project AND its level is exactly
            # (clean_level - 1). The two-step query (parent
            # lookup + insert) is wrapped in the storage lock
            # so a concurrent move / delete cannot race it.
            if parent_id is not None:
                prow = conn.execute(
                    "SELECT project_id, level, parent_id "
                    "FROM project_nodes WHERE id = ?",
                    (int(parent_id),),
                ).fetchone()
                if prow is None:
                    # FK will catch it too, but a friendlier
                    # ValueError is easier to surface than an
                    # IntegrityError on a hand-crafted POST.
                    raise ValueError(
                        f"parent_id={int(parent_id)} does not exist"
                    )
                if int(prow["project_id"]) != int(project_id):
                    raise ValueError(
                        f"parent_id={int(parent_id)} belongs to a "
                        f"different project (parent.project_id="
                        f"{int(prow['project_id'])} != "
                        f"project_id={int(project_id)})"
                    )
                expected_level = int(prow["level"]) + 1
                if expected_level != clean_level:
                    raise ValueError(
                        f"chain inconsistency: parent.level="
                        f"{int(prow['level'])} but child.level="
                        f"{clean_level} (expected {expected_level})"
                    )

            now = _now_iso()
            cur = conn.execute(
                "INSERT INTO project_nodes "
                "(project_id, parent_id, level, name, "
                "description, status, position, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(project_id),
                    None if parent_id is None else int(parent_id),
                    clean_level,
                    clean_name,
                    str(description or ""),
                    clean_status,
                    0,
                    now,
                    now,
                ),
            )
            new_id = int(cur.lastrowid)
            # v0.9.2 sub-task 7 — auto-grant the 3
            # baseline roles on the new node. The
            # baseline role IDs are looked up by name so
            # the call does not depend on the seed
            # having run at a particular time. New

            # nodes get project_leader=write,
            # team_leader=write, user=read by default.
            for role_name, can_write in (
                ("project_leader", 1),
                ("team_leader", 1),
                ("user", 0),
            ):
                conn.execute(
                    "INSERT OR IGNORE INTO "
                    "project_custom_role_permissions "
                    "(custom_role_id, node_id, can_write, "
                    "granted_at) "
                    "SELECT cr.id, ?, ?, datetime('now') "
                    "FROM project_custom_roles cr "
                    "WHERE cr.project_id = ? AND cr.name = ?",
                    (int(new_id), int(can_write),
                     int(project_id), role_name),
                )
        finally:
            conn.close()
    logger.info(
        "project node created id=%s project_id=%s level=%s "
        "parent_id=%s status=%s",
        new_id, int(project_id), clean_level,
        parent_id, clean_status,
    )
    return new_id


def _do_find_node_by_id(self, node_id: int) -> Optional[dict[str, Any]]:
    """Return the node row as a dict, or ``None`` if missing.

    Returns a plain ``dict`` (not a dataclass) because the
    v0.9.2 storage surface is the minimum that v0.9.3's UI
    needs; a frozen dataclass can be added in a later patch
    when the read-side consumers stabilise. Callers that want
    a typed shape can convert at the route layer.
    """
    with self._lock:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, project_id, parent_id, level, name, "
                "description, status, position, created_at, "
                "updated_at "
                "FROM project_nodes WHERE id = ?",
                (int(node_id),),
            ).fetchone()
            return _row_to_mapping(row) if row is not None else None
        finally:
            conn.close()


def _do_list_children(
    self, project_id: int, parent_id: Optional[int]
) -> list[dict[str, Any]]:
    """Return every direct child of ``parent_id`` in ``project_id``.

    The result is sorted by ``(position ASC, created_at ASC)``
    so the v0.9.3 board view can iterate siblings in
    deterministic order. ``parent_id=None`` returns every
    top-level (level=1) node in the project — the entry point
    for the board view's first render.

    The composite index ``idx_nodes_project_parent`` covers
    the leading ``project_id, parent_id`` columns so the
    query is a single index scan on the project subtree.
    """
    with self._lock:
        conn = self._connect()
        try:
            if parent_id is None:
                rows = conn.execute(
                    "SELECT id, project_id, parent_id, level, name, "
                    "description, status, position, created_at, "
                    "updated_at "
                    "FROM project_nodes "
                    "WHERE project_id = ? AND parent_id IS NULL "
                    "ORDER BY position ASC, created_at ASC",
                    (int(project_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, project_id, parent_id, level, name, "
                    "description, status, position, created_at, "
                    "updated_at "
                    "FROM project_nodes "
                    "WHERE project_id = ? AND parent_id = ? "
                    "ORDER BY position ASC, created_at ASC",
                    (int(project_id), int(parent_id)),
                ).fetchall()
            return [_row_to_mapping(r) for r in rows]
        finally:
            conn.close()


def _do_list_tree(self, project_id: int) -> list[dict[str, Any]]:
    """Return every node in ``project_id`` in (parent, position) order.

    The flat-list shape lets the v0.9.3 board view build the
    tree in one pass without recursive SELECTs (which SQLite
    has no native syntax for anyway). The board view re-orders
    the rows into a tree by walking the ``parent_id`` chain
    in-memory; a future patch can swap this for a recursive CTE
    if the project grows large enough to make the in-memory
    walk expensive.

    Sorted by ``(parent_id, position, created_at)`` so a
    depth-first walk of the result visits siblings in the
    same order as the board view's per-level render.
    """
    with self._lock:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, project_id, parent_id, level, name, "
                "description, status, position, created_at, "
                "updated_at "
                "FROM project_nodes "
                "WHERE project_id = ? "
                "ORDER BY parent_id ASC, position ASC, "
                "created_at ASC",
                (int(project_id),),
            ).fetchall()
            return [_row_to_mapping(r) for r in rows]
        finally:
            conn.close()


def _do_get_tree(self, project_id: int) -> list[dict[str, Any]]:
    """Build the parent -> children tree from :meth:`list_tree`.

    Returns a **flat list of top-level nodes** (``parent_id IS
    NULL``), each carrying a ``children`` list of the same shape
    recursively nested. The v0.9.3 board view's template iterates
    this list and recurses through ``children`` via a Jinja2 macro
    so the page renders the 6-level tree in one pass without a
    second SQL round-trip per node.

    Each row carries the same fields as :meth:`list_tree` plus
    an extra ``children`` list (possibly empty). The
    ``children`` list is *always* present (empty for leaves) so
    the template can iterate without a ``{% if %}`` guard.

    Top-level nodes are returned in ``(position, created_at)``
    order via :meth:`list_tree`'s already-sorted output. The
    children of any parent are visited in the same order because
    the parent->children map preserves the SQL row order.
    """
    flat = self.list_tree(int(project_id))
    by_id: dict[int, dict[str, Any]] = {}
    children_of: dict[Optional[int], list[dict[str, Any]]] = {None: []}
    for row in flat:
        node = dict(row)
        node["children"] = []
        node_id_int = int(node["id"])
        by_id[node_id_int] = node
        pid = node["parent_id"]
        pid_int = int(pid) if pid is not None else None
        children_of.setdefault(pid_int, []).append(node)
    for node_id_int, node in by_id.items():
        node["children"] = children_of.get(node_id_int, [])
    return children_of.get(None, [])


def _do_update_node(
    self,
    node_id: int,
    name: str,
    description: str,
    status: str,
) -> bool:
    """Update name / description / status. Returns True iff a row
    was changed.

    The cross-project guard is enforced by the caller (the route
    layer reads the node, finds its ``project_id``, and verifies
    the actor's permission before reaching this method). This
    method is policy-free; the storage layer's 6-level invariant
    only needs the status whitelist to remain consistent.

    Note: ``level`` and ``parent_id`` are **not** in the
    parameter list — a node's depth is set at create time and
    only :meth:`move_node` may re-parent a node.
    """
    from .feature_storage import _now_iso

    clean_name = _clean_name(name)
    clean_status = _clean_status(status)
    now = _now_iso()
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE project_nodes "
                "SET name = ?, description = ?, status = ?, "
                "updated_at = ? "
                "WHERE id = ?",
                (
                    clean_name,
                    str(description or ""),
                    clean_status,
                    now,
                    int(node_id),
                ),
            )
            changed = cur.rowcount > 0
        finally:
            conn.close()
    if changed:
        logger.info(
            "project node updated id=%s status=%s",
            int(node_id), clean_status,
        )
    return changed


def _do_move_node(
    self,
    node_id: int,
    new_parent_id: Optional[int],
    new_position: int,
) -> bool:
    """Re-parent a node. Returns True iff a row was changed.

    The 6-level invariant is re-validated on the **subtree**
    because moving a level-2 node to a level-5 subtree would
    push its descendants past the cap. The check walks the
    subtree in Python (recursive CTE would be cleaner but the
    board view's flat-list shape already keeps the tree
    small enough that a Python walk is fine for v0.9.2).

    Cycle detection: a move cannot target a descendant of
    itself. The check is implicit — the subtree walk
    short-circuits if the target appears in the moved node's
    descendants.

    Raises
    ------
    ValueError
        * target ``parent_id`` does not exist
        * target parent belongs to a different project
        * the move would create a cycle (target is a descendant
          of the moved node)
        * the move would push a descendant past the 6-level
          cap
    sqlite3.IntegrityError
        * unknown ``new_parent_id`` (FK violation)
    """
    with self._lock:
        conn = self._connect()
        try:
            # 1. Read the moved node.
            moved = conn.execute(
                "SELECT id, project_id, level, parent_id "
                "FROM project_nodes WHERE id = ?",
                (int(node_id),),
            ).fetchone()
            if moved is None:
                return False
            moved_level = int(moved["level"])
            moved_pid = int(moved["project_id"])

            # 2. Resolve the new parent's level (None for top-level).
            if new_parent_id is None:
                new_parent_level = 0
            else:
                prow = conn.execute(
                    "SELECT project_id, level FROM project_nodes "
                    "WHERE id = ?",
                    (int(new_parent_id),),
                ).fetchone()
                if prow is None:
                    raise ValueError(
                        f"new_parent_id={int(new_parent_id)} "
                        f"does not exist"
                    )
                if int(prow["project_id"]) != moved_pid:
                    raise ValueError(
                        f"new_parent_id={int(new_parent_id)} "
                        f"belongs to a different project"
                    )
                new_parent_level = int(prow["level"])

            # 3. Compute the new level for the moved node.
            new_level = new_parent_level + 1
            if new_level < 1 or new_level > MAX_NODE_LEVEL:
                raise ValueError(
                    f"move would push node to level={new_level} "
                    f"(cap is {MAX_NODE_LEVEL})"
                )

            # 4. Collect every descendant id (DFS via repeated
            #    one-level queries — the tree is small enough
            #    in v0.9.2 to make this O(depth) Python loop
            #    preferable to a recursive CTE).
            descendants: set[int] = set()
            frontier: list[int] = [int(node_id)]
            while frontier:
                children = [
                    int(r["id"]) for r in conn.execute(
                        "SELECT id FROM project_nodes "
                        "WHERE parent_id IN ("
                        + ",".join("?" * len(frontier))
                        + ")",
                        tuple(frontier),
                    ).fetchall()
                ]
                new_frontier: list[int] = []
                for cid in children:
                    if cid in descendants:
                        continue
                    descendants.add(cid)
                    new_frontier.append(cid)
                frontier = new_frontier

            # 5. Cycle check: new_parent_id cannot be a
            #    descendant of the moved node.
            if new_parent_id is not None and int(new_parent_id) in descendants:
                raise ValueError(
                    f"cannot move node_id={int(node_id)} under its "
                    f"own descendant parent_id={int(new_parent_id)}"
                )

            # 6. Subtree cap check: every descendant's level
            #    shifts by the same delta as the moved node.
            level_delta = new_level - moved_level
            if descendants:
                placeholders = ",".join("?" * len(descendants))
                max_desc_row = conn.execute(
                    "SELECT MAX(level) AS m FROM project_nodes "
                    f"WHERE id IN ({placeholders})",
                    tuple(descendants),
                ).fetchone()
                max_desc_level = int(max_desc_row["m"] or 0)
                if max_desc_level + level_delta > MAX_NODE_LEVEL:
                    raise ValueError(
                        f"move would push a descendant past "
                        f"level-{MAX_NODE_LEVEL}: max_descendant="
                        f"{max_desc_level} + delta={level_delta}"
                        f" = {max_desc_level + level_delta}"
                    )

            # 7. Update the moved node.
            from .feature_storage import _now_iso
            now = _now_iso()
            cur = conn.execute(
                "UPDATE project_nodes "
                "SET parent_id = ?, level = ?, position = ?, "
                "updated_at = ? "
                "WHERE id = ?",
                (
                    None if new_parent_id is None else int(new_parent_id),
                    new_level,
                    int(new_position),
                    now,
                    int(node_id),
                ),
            )
            changed_root = cur.rowcount > 0

            # 8. Update the subtree's level by the same delta.
            if changed_root and descendants:
                placeholders = ",".join("?" * len(descendants))
                conn.execute(
                    "UPDATE project_nodes "
                    "SET level = level + ?, updated_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (level_delta, now, *descendants),
                )
            changed = changed_root
        finally:
            conn.close()
    if changed:
        logger.info(
            "project node moved id=%s new_parent_id=%s new_level=%s",
            int(node_id), new_parent_id, new_level,
        )
    return changed


def _do_delete_node(self, node_id: int) -> bool:
    """Delete a node and its subtree (via FK ``ON DELETE CASCADE``).

    Returns True iff the root row was removed. The cascade
    removes every descendant in a single statement; the
    "descendants removed" count is exposed via the SQL return
    (``rowcount`` is the **root** row count because the DELETE
    is a single-row WHERE clause; the cascade is invisible to
    the storage layer's return value, which is intentional —
    the route layer only needs to know whether the root
    deletion happened).
    """
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM project_nodes WHERE id = ?",
                (int(node_id),),
            )
            removed = cur.rowcount > 0
        finally:
            conn.close()
    if removed:
        logger.info("project node deleted id=%s", int(node_id))
    return removed


def _do_delete_subtree(self, node_id: int) -> int:
    """Physically delete a node and its entire subtree.

    v0.9.1 sub-task 11 — 8/12 17:45 user 拍: 撤回 soft delete, **真删**.
    Rationale: soft delete (status='archived') only grows the table;
    every "delete" the user performs piles up archived rows that
    pollute the sidebar / board and bloat the DB. The user-facing
    "delete" action must physically remove the row, full stop.
    The 7/22 RBAC business-level lock still guards the operation
    (server auth + chokepoint + 二次确认 + 不可逆) — the lock is
    about who can call this, not about whether the row should
    survive. A misclick / hand-crafted POST is still rejected at
    the auth + 二次确认 layers; once past those, the destruction
    is intentional, the same as pen and paper.

    Walks the subtree breadth-first via Python (same pattern as
    :func:`_do_move_node` — the v0.9.2 tree is small enough that
    a Python walk is preferable to a recursive CTE). The single
    bulk DELETE on the collected id list is wrapped in the
    storage lock so a concurrent create / move cannot race it.

    Returns the number of rows removed (root + every descendant).
    A root that does not exist returns 0 — the route layer maps
    that to a 404.
    """
    with self._lock:
        conn = self._connect()
        try:
            root = conn.execute(
                "SELECT id FROM project_nodes WHERE id = ?",
                (int(node_id),),
            ).fetchone()
            if root is None:
                return 0
            descendants: set[int] = {int(node_id)}
            frontier: list[int] = [int(node_id)]
            while frontier:
                children = [
                    int(r["id"]) for r in conn.execute(
                        "SELECT id FROM project_nodes "
                        "WHERE parent_id IN ("
                        + ",".join("?" * len(frontier))
                        + ")",
                        tuple(frontier),
                    ).fetchall()
                ]
                new_frontier: list[int] = []
                for cid in children:
                    if cid in descendants:
                        continue
                    descendants.add(cid)
                    new_frontier.append(cid)
                frontier = new_frontier
            placeholders = ",".join("?" * len(descendants))
            cur = conn.execute(
                "DELETE FROM project_nodes "
                f"WHERE id IN ({placeholders})",
                tuple(descendants),
            )
            removed = int(cur.rowcount)
        finally:
            conn.close()
    if removed:
        logger.info(
            "project node subtree physically deleted root_id=%s rows=%s",
            int(node_id), removed,
        )
    return removed


def install_node_methods() -> None:
    """Attach the seven node methods to :class:`ProjectStorage`.

    Called by :mod:`feature_storage` at the bottom of the module
    (after :class:`ProjectStorage` is fully defined). The
    function is a no-op for any method that is already installed
    (idempotent re-import).

    The seven methods are installed in one pass to keep the
    public surface stable: a v0.9.3 route that calls
    ``storage.create_node(...)`` etc. before this module is
    imported gets the same call shape as after the import.
    """
    # Local import: ProjectStorage is defined in feature_storage,
    # which imports this module. Doing the import here keeps the
    # top-of-module cycle at "soft" status (function body, not
    # module body).
    from .feature_storage import ProjectStorage

    _NODE_METHODS = {
        "create_node": _do_create_node,
        "find_node_by_id": _do_find_node_by_id,
        "list_children": _do_list_children,
        "list_tree": _do_list_tree,
        "get_tree": _do_get_tree,
        "update_node": _do_update_node,
        "move_node": _do_move_node,
        "delete_node": _do_delete_node,
        "delete_subtree": _do_delete_subtree,
    }
    for _name, _method in _NODE_METHODS.items():
        if _name not in ProjectStorage.__dict__:
            setattr(ProjectStorage, _name, _method)


# Install on import. The bottom of feature_storage.py also calls
# this defensively; running it twice is a no-op.
install_node_methods()


__all__ = [
    "MAX_NODE_LEVEL",
    "install_node_methods",
]
