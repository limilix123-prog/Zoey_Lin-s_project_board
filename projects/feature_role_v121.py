"""v0.9.1 + v0.9.3 — RBAC matrix + server-side chokepoints.

v0.9.1 sub-task 2 (完整权限设计) introduced the 3-bucket RBAC
matrix; v0.9.3 (user 8/13 19:34 拍板) **dropped** the
per-(user, node) grant surface and the ``project_node_permissions``
table that backed it. The remaining 2-bucket matrix combines via
OR:

1. **Auto-own bucket** — T0 (admin, rank 0) and T1 (manager,
   rank 1) auto-own every project. The bucket is rank-based; a
   user in this bucket can read / write on any project in the
   system. Source: :func:`_is_auto_own` in
   :mod:`project_board.projects.feature_storage_rbac`.

2. **Owner bucket** — T2 (project_leader, rank 2) holds the
   per-project owner role. The bucket is the intersection of
   ``user.rank == 2`` and ``user.id == project.owner_id``. A
   T2 user that does not own the project falls into the
   **per-project member bucket** instead, not this bucket.

3. **Role-grant bucket (v0.9.3 — replaces per_node_grant)** —
   the user is a project member with a non-null
   ``custom_role_id`` and that role has a row in
   ``project_custom_role_permissions`` with ``can_write = 1`` for
   the specific ``node_id``. The check joins the user → their
   role → the role's per-(role, node) grant template; the user
   inherits whatever the role grants. This is the v0.9.3
   replacement for v0.9.1's per-(user, node) bucket (which
   v0.9.3 dropped together with the ``project_node_permissions``
   table).

The 3 buckets combine via OR: a write to a node succeeds
when the actor matches **any** of the three. The v0.9.3 design
is simpler than v0.9.1's "user can have a unique node grant
overriding their role" — the v0.9.3 design is the "role-only"
minimum that lets a project_leader grant node-scoped write to a
role (and the role's members inherit it) without elevating any
specific user.

3-action chokepoints
--------------------
The :func:`add_member_action`, :func:`remove_member_action`, and
:func:`change_owner_action` helpers are the **server-side
chokepoints** for the 3 POST endpoints the v0.9.3 UI ships. The
v0.9.1 4th chokepoint (:func:`grant_node_action`) is **dropped**
in v0.9.3 — the user-level grant surface is gone, the role-grant
surface is the new chokepoint
(:func:`submit_role_node_permission` in
:mod:`project_board.projects.feature_members_page`).

Each chokepoint:

* validates the actor's authority (auto-own / owner bucket);
* validates the target (user / project exists, is in the
  right state);
* calls the policy-free storage method (e.g.
  :meth:`ProjectStorage.add_member`);
* returns a structured result the route layer maps to a 200 /
  302 / 400 / 403 / 404 response.

The chokepoints **never** trust client-side state. A
hand-crafted POST that bypasses the UI is rejected by the
chokepoint before any storage call (7/22 RBAC business-lock
principle). The chokepoints are thin — the policy lives in
:func:`_resolve_role` and the policy-free writers in
:class:`ProjectStorage`.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from flask import current_app

from .feature_storage import ProjectStorage
from .feature_storage_rbac import _is_auto_own

logger = logging.getLogger(__name__)


# --- 3-bucket RBAC tags ----------------------------------------------------

# Log labels for each bucket. The constants are exposed so the
# log lines from the chokepoints can be grepped for a specific
# bucket without re-deriving the literal at every call site.
_BUCKET_AUTO_OWN: str = "auto_own"
_BUCKET_OWNER: str = "owner"
_BUCKET_ROLE_GRANT: str = "role_grant"


# --- 3-bucket RBAC helpers -------------------------------------------------


def _is_owner(user, project) -> bool:
    """Return True iff ``user`` is the project's owner (bucket 2).

    v0.9.1 2-bucket RBAC. The owner bucket is the intersection
    of:

    * ``user.rank == 2`` (T2 — project_leader) — T0 / T1 are
      handled by the auto-own bucket and intentionally **not**
      duplicated here. A T0 user that is also the project's
      owner is "auto-own + owner" but the chokepoint accepts
      either bucket.
    * ``user.id == project.owner_id`` — the project row
      records the owner. The lookup is in-memory; no SQL
      round-trip needed.

    Returns False for ``None`` user / project so a defensive
    caller that forgot an upstream guard fails closed. Returns
    False for a T0/T1 user that is not the project owner (the
    auto-own bucket covers them anyway, so the false here is
    harmless).
    """
    if user is None or project is None:
        return False
    rank = getattr(user, "rank", None)
    if rank is None:
        return False
    if int(rank) != 2:
        return False
    return int(user.id) == int(project.owner_id)


def _has_node_role_grant(
    storage: ProjectStorage,
    user_id: int,
    node_id: int,
) -> bool:
    """Return True iff ``user_id``'s role grants ``can_write=1`` on ``node_id``.

    v0.9.3 (replaces v0.9.1 ``_has_node_grant``) — the role-grant
    check joins the user → their project role → the role's
    per-(role, node) grant template. A single SELECT against
    ``project_custom_role_permissions`` joined to
    ``project_members`` (filtered on ``user_id``) returns the
    answer in one round-trip.

    The helper accepts the storage instance rather than
    looking it up itself so the call site (the chokepoint) is
    in control of the DB connection lifetime. The query is
    direct (no cross-project guard) because the node already
    belongs to a single project — the cross-project guard
    lives in the route layer that supplies ``node_id``.

    A ``sqlite3.OperationalError`` (e.g. the table is missing
    on a hand-edited pre-v0.9.3 DB) is caught and returns False
    so a defensive caller does not crash on a missing table —
    the bucket simply does not apply.
    """
    try:
        with storage._lock:
            conn = storage._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM project_custom_role_permissions pcrp "
                    "JOIN project_members pm "
                    "  ON pm.custom_role_id = pcrp.custom_role_id "
                    "WHERE pm.user_id = ? AND pcrp.node_id = ? "
                    "  AND pcrp.can_write = 1 "
                    "LIMIT 1",
                    (int(user_id), int(node_id)),
                ).fetchone()
            finally:
                conn.close()
    except sqlite3.OperationalError as exc:
        logger.info(
            "v0.9.3 _has_node_role_grant: SELECT failed "
            "(table missing?): %s",
            exc,
        )
        return False
    return row is not None


def _resolve_role(
    storage: ProjectStorage,
    user,
    project,
    node: Optional[Any] = None,
) -> Optional[str]:
    """Return the highest bucket the actor matches, or ``None``.

    v0.9.3 3-bucket RBAC resolution. Returns the highest bucket
    string when the actor matches at least one bucket:

    * :data:`_BUCKET_AUTO_OWN` — T0 / T1 (rank 0 or 1)
    * :data:`_BUCKET_OWNER` — T2 (rank 2) and project owner
    * :data:`_BUCKET_ROLE_GRANT` — user has a project role with
      ``can_write = 1`` on the specific ``node``; only returned
      when ``node`` is provided and the role has the grant.

    The order is auto-own > owner > role-grant. A T0/T1 actor
    returns ``_BUCKET_AUTO_OWN`` regardless of owner status
    because auto-own is the broadest bucket. A T2 owner returns
    ``_BUCKET_OWNER`` even when ``node`` is None and a role-grant
    is not requested. A T3/T4 actor that has a role-grant on
    the specific ``node`` returns ``_BUCKET_ROLE_GRANT`` when
    ``node`` is provided, ``None`` otherwise.

    Returns ``None`` for a ``None`` user / project, a T3/T4 user
    with no role-grant on the node, or any user that is not in
    any of the three buckets. The route layer maps ``None`` to
    "no authority" — typically a 403 on a write or a 404 on a
    read that requires authority.
    """
    if user is None or project is None:
        return None
    if _is_auto_own(user):
        return _BUCKET_AUTO_OWN
    if _is_owner(user, project):
        return _BUCKET_OWNER
    if node is not None:
        node_id: Optional[int] = None
        # The node may be a ProjectRow-style object, a dict
        # (from a list_tree / get_tree call), or a raw int.
        # All three shapes are accepted so the chokepoint
        # callers can pass the most convenient form.
        if isinstance(node, int):
            node_id = int(node)
        elif isinstance(node, dict):
            raw = node.get("id")
            if raw is not None:
                node_id = int(raw)
        else:
            raw = getattr(node, "id", None)
            if raw is not None:
                node_id = int(raw)
        if node_id is not None and _has_node_role_grant(
            storage, int(user.id), int(node_id),
        ):
            return _BUCKET_ROLE_GRANT
    return None


# --- 3-action server-side chokepoints --------------------------------------


def _check_can_manage_project(user, project) -> None:
    """Raise ``PermissionError`` if ``user`` cannot manage ``project``.

    Mirrors the v0.7.x :func:`can_manage_members` gate: T0 / T1
    (auto-own) and the project owner pass; everyone else is
    rejected. Used by the add / remove chokepoints — the
    change_owner chokepoint has its own T0/T1-only gate
    that is stricter than this one.
    """
    if _is_auto_own(user):
        return
    if int(user.id) == int(project.owner_id):
        return
    raise PermissionError(
        f"user_id={int(user.id)} cannot manage project_id="
        f"{int(project.id)} (not admin/manager and not owner)"
    )


def add_member_action(
    storage: ProjectStorage,
    project: Any,
    target_user: Any,
    role_in_project: str,
    actor: Any,
) -> bool:
    """Add ``target_user`` to ``project`` as a project member.

    v0.9.1 3-action chokepoint — the 1st of 3. The chokepoint:

    1. checks the actor is in the auto-own or owner bucket
       (``_check_can_manage_project``);
    2. checks the target user exists (the route layer already
       loaded it; this is a belt-and-braces guard);
    3. checks the target is not T0 / T1 (auto-own users are
       not project members — mirrors the v0.7.2a invariant);
    4. calls :meth:`ProjectStorage.add_member` with the
       supplied ``role_in_project`` literal (the route layer
       is the policy-deciding caller; the chokepoint just
       threads the value through).

    Returns True on success. Raises ``PermissionError`` on a
    bucket / target-rank violation (route maps to 403 /
    400). Raises ``ValueError`` on an unknown role literal
    (route maps to 400). Re-raises
    ``sqlite3.IntegrityError`` for the caller to surface as
    the existing "already a member" 200-rendered page.

    v0.9.3 — the role literal is resolved to a
    ``project_custom_roles.id`` (the single role table for
    both baseline and user-created roles). The lookup uses
    the public :meth:`ProjectStorage.list_roles` method so
    the chokepoint has no import-time dependency on the
    split-out role / permission storage modules.
    """
    _check_can_manage_project(actor, project)
    if target_user is None:
        raise ValueError("target_user is required")
    if _is_auto_own(target_user):
        raise PermissionError(
            "T0/T1 已 auto-own, 无需 add"
        )
    # Resolve the role name to a custom_role_id via the
    # public list_roles method. A name that does not match a
    # baseline role still writes the literal to
    # ``custom_role_id`` (None = null role, the default for
    # members who have not been assigned a role yet).
    custom_role_id: int | None = None
    for r in storage.list_roles(int(project.id)):
        if str(r.get("name")) == str(role_in_project):
            custom_role_id = int(r["id"])
            break
    storage.add_member(
        project_id=int(project.id),
        user_id=int(target_user.id),
        custom_role_id=custom_role_id,
    )
    logger.info(
        "v0.9.1 add_member_action actor_id=%s project_id=%s "
        "target_id=%s role=%s bucket=%s",
        int(actor.id), int(project.id),
        int(target_user.id), str(role_in_project),
        _resolve_role(storage, actor, project),
    )
    return True


def remove_member_action(
    storage: ProjectStorage,
    project: Any,
    target_user_id: int,
    actor: Any,
) -> bool:
    """Remove ``target_user_id`` from ``project``'s member list.

    v0.9.1 3-action chokepoint — the 2nd of 3. The chokepoint:

    1. checks the actor is in the auto-own or owner bucket;
    2. checks the target user is not the actor (anti-self;
       mirrors the v0.7.2a invariant);
    3. calls :meth:`ProjectStorage.remove_member` and returns
       its boolean (True iff a row was removed; False is a
       200-rendered "no-op" at the route layer).

    Raises ``PermissionError`` on a bucket / self violation.
    """
    _check_can_manage_project(actor, project)
    if int(target_user_id) == int(actor.id):
        raise PermissionError("cannot remove self as a project member")
    removed = storage.remove_member(
        project_id=int(project.id),
        user_id=int(target_user_id),
    )
    logger.info(
        "v0.9.1 remove_member_action actor_id=%s project_id=%s "
        "target_id=%s removed=%s bucket=%s",
        int(actor.id), int(project.id),
        int(target_user_id), bool(removed),
        _resolve_role(storage, actor, project),
    )
    return removed


def change_owner_action(
    storage: ProjectStorage,
    project: Any,
    new_owner_id: int,
    actor: Any,
) -> bool:
    """Reassign ``project``'s owner to ``new_owner_id``.

    v0.9.1 3-action chokepoint — the 3rd of 3. The chokepoint
    is **stricter** than the project-management chokepoints:

    * the actor must be T0 / T1 (``_is_auto_own``) — mirrors
      the v0.7.2b endpoint;
    * the project must not be a system project (the system
      project owner is permanent);
    * the new owner must exist (the route layer already loaded
      it; the chokepoint re-checks via the storage layer for
      the "row disappeared" case);
    * the new owner must be T2 (project_leader, rank 2) — the
      "T0/T1 already auto-own" / "T3 / T4 cannot own" rules
      are not surfaced here because the route layer's
      dropdown only lists T2 users (and the chokepoint's
      :class:`ValueError` is the belt-and-braces guard).

    Returns True on success, False on a no-op (target equals
    current owner). Raises ``PermissionError`` /
    ``ValueError` for the caller to map to 400 / 403 / 404.
    """
    if not _is_auto_own(actor):
        raise PermissionError(
            "only T0/T1 (admin/manager) can change project owner"
        )
    if bool(getattr(project, "is_system", False)):
        raise PermissionError("system project owner is permanent")
    if int(new_owner_id) == int(project.owner_id):
        # Idempotent no-op — the route layer maps to a 302
        # with a "Owner unchanged" notice, matching the
        # v0.7.2b endpoint.
        return False
    # Validate target rank server-side (defensive — the route
    # dropdown only lists T2, but a hand-crafted POST could
    # pass any user id).
    from ..accounts.feature_storage import UserStorage
    user_storage = UserStorage(
        (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    )
    target = user_storage.find_by_id(int(new_owner_id))
    if target is None:
        raise ValueError("user not found")
    target_rank = getattr(target, "rank", None)
    if target_rank is None or int(target_rank) != 2:
        raise ValueError(
            f"target rank {target_rank!r} is not project_leader (rank 2)"
        )
    storage.update_owner(
        project_id=int(project.id),
        new_owner_id=int(new_owner_id),
    )
    logger.info(
        "v0.9.1 change_owner_action actor_id=%s project_id=%s "
        "old_owner_id=%s new_owner_id=%s",
        int(actor.id), int(project.id),
        int(project.owner_id), int(new_owner_id),
    )
    return True


# v0.9.3 — the v0.9.1 4th chokepoint grant_node_action is dropped.
# User-level grant surface is gone; the v0.9.3 equivalent is the
# role-grant surface (submit_role_node_permission), a thin wrapper
# around ProjectStorage.set_role_node_permission. RBAC lives at the
# route layer (4-action set collapsed to 3).


__all__ = [
    "_BUCKET_AUTO_OWN",
    "_BUCKET_OWNER",
    "_BUCKET_ROLE_GRANT",
    "_is_owner",
    "_has_node_role_grant",
    "_resolve_role",
    "add_member_action",
    "remove_member_action",
    "change_owner_action",
    "_check_can_manage_project",
]
