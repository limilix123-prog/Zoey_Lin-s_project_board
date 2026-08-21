"""Project member add/remove endpoints.

POST ``/projects/<int:project_id>/members``                 — add a user
POST ``/projects/<int:project_id>/members/<int:user_id>/remove`` — remove

Owner-based gate
----------------
The endpoints are guarded by ``@require_auth`` plus the helper
:func:`can_manage_members` (admin / manager auto-own every project,
otherwise the actor must be the project's owner). A project_leader
(T2) can manage their own projects (they are the owner) but cannot
manage projects owned by other users. team_leader (T3) and plain
user (T4) never satisfy :func:`can_manage_members` and are rejected
by the gate before any handler logic runs. The 7/22 RBAC
business-lock principle keeps the owner check in the route handler;
the storage layer stays policy-agnostic.

v0.7.2a target-rank gate
------------------------
The handler additionally rejects targets that are T0/T1 (auto-own
ranks) — they do not appear in ``project_members`` and the UI
already filters them out. Concretely:

* add    : target rank 0/1 -> 400 "T0/T1 已 auto-own, 无需 add"
* remove : target rank 0/1 -> 400 "T0/T1 auto-own, 不能 remove"

The check is enforced server-side (7/22) so a hand-crafted POST
that smuggles a T0/T1 user id past the dropdown still gets a clean
400 with a descriptive message. The rank is read off the target's
``rank`` column via :func:`_is_auto_own` (which falls back to the
legacy ``role`` string when ``rank`` is missing).

Anti-self
---------
The actor cannot add or remove themselves:

* add: ``actor.id == target_user_id`` -> 400 "cannot add self"
* remove: ``actor.id == user_id`` -> 400 "cannot remove self"

The check guards against a project_leader accidentally demoting
themselves out of the system project (where the owner=admin, the
actor is a project_leader, and removing themselves is a no-op for
visibility but still semantically wrong). The system project owner
(admin) is permanently a viewer via the owner check in
``user_can_see_project``; the storage layer keeps a redundant
``project_members`` row out of the way by rejecting the self-add.

Audit log
---------
Every successful add emits a ``project member added project_id=X
user_id=Y role=Z`` line and every successful remove emits a
``project member removed project_id=X user_id=Y`` line. Both come
from :class:`ProjectStorage` so the route handler stays thin.
"""

from __future__ import annotations

import logging
import sqlite3

from flask import Blueprint, abort, current_app, g, redirect, request, url_for

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_require_auth import require_auth
from .feature_storage import ProjectStorage, can_manage_members
from .feature_storage_rbac import _is_auto_own

logger = logging.getLogger(__name__)

bp = Blueprint("project_members", __name__)

_USER_ID_FIELD: str = "user_id"

_ERR_FORBIDDEN: str = "you cannot manage members of this project"
_ERR_SELF_ADD: str = "cannot add self as a project member"
_ERR_SELF_REMOVE: str = "cannot remove self as a project member"
_ERR_USER_NOT_FOUND: str = "user not found"
_ERR_ALREADY_MEMBER: str = "already a project member"
_ERR_NOT_A_MEMBER: str = "user is not a member of this project"
# v0.7.2a — T0/T1 (auto-own) cannot be project_members rows; the
# endpoints reject any attempt to insert or remove them so the
# invariant survives a hand-crafted POST that bypasses the UI.
_ERR_AUTO_OWN_ADD: str = "T0/T1 已 auto-own, 无需 add"
_ERR_AUTO_OWN_REMOVE: str = "T0/T1 auto-own, 不能 remove"


def _project_storage() -> ProjectStorage:
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


def _user_storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _check_manage_members(actor, project, action: str) -> None:
    """Owner-based gate; abort 403 if the actor cannot manage members.

    The same helper is shared by the add and remove endpoints so the
    log / abort path is identical. ``action`` is "add" or "remove" —
    it lands in the log line so an operator chasing a 403 can
    disambiguate which endpoint rejected the request.
    """
    if can_manage_members(actor, project):
        return
    logger.warning(
        "project member %s denied actor_id=%s project_id=%s role=%s "
        "owner_id=%s (403 — not admin/manager and not owner)",
        action, actor.id, project.id, actor.role, project.owner_id,
    )
    abort(403, _ERR_FORBIDDEN)


@bp.post("/projects/<int:project_id>/members")
@require_auth
def add_project_member(project_id: int):
    """Add a user as a member of ``project_id``.

    Form contract: a single ``user_id`` field. The endpoint runs after
    ``@require_auth`` so the owner-based gate (:func:`can_manage_members`)
    is enforced here; this handler enforces the anti-self rule and
    the membership uniqueness (composite PK on ``project_members``).
    """
    actor = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "project member add 404 actor_id=%s project_id=%s",
            actor.id, project_id,
        )
        abort(404)

    _check_manage_members(actor, project, "add")

    raw = str(request.form.get(_USER_ID_FIELD, "") or "").strip()
    if not raw:
        logger.info(
            "project member add rejected actor_id=%s project_id=%s reason=missing-user-id",
            actor.id, project_id,
        )
        abort(400, "user_id is required")
    try:
        target_id = int(raw)
    except ValueError:
        logger.info(
            "project member add rejected actor_id=%s project_id=%s raw=%r reason=bad-user-id",
            actor.id, project_id, raw,
        )
        abort(400, "user_id must be an integer")

    # Anti-self: an actor cannot add themselves as a member.
    if target_id == int(actor.id):
        logger.warning(
            "project member add rejected actor_id=%s project_id=%s reason=self",
            actor.id, project_id,
        )
        abort(400, _ERR_SELF_ADD)

    target = _user_storage().find_by_id(target_id)
    if target is None:
        logger.info(
            "project member add 404 actor_id=%s project_id=%s target_id=%s",
            actor.id, project_id, target_id,
        )
        abort(404, _ERR_USER_NOT_FOUND)

    # v0.7.2a — T0/T1 are auto-own and never appear in
    # project_members. Reject the add so the invariant survives a
    # hand-crafted POST that bypasses the UI. The rank is read via
    # _is_auto_own (which falls back to the legacy role string when
    # rank is missing).
    if _is_auto_own(target):
        logger.warning(
            "project member add rejected actor_id=%s project_id=%s "
            "target_id=%s reason=auto-own",
            actor.id, project_id, target_id,
        )
        abort(400, _ERR_AUTO_OWN_ADD)

    try:
        storage.add_member(project_id=project_id, user_id=target_id)
    except sqlite3.IntegrityError:
        # The composite PK ``(project_id, user_id)`` rejects duplicate
        # adds. The error is benign: the actor clicked Add on a user
        # who is already a member. We surface it as a 200-rendered
        # project detail with a flash-style query so the UX matches the
        # rest of the project module.
        logger.info(
            "project member add rejected actor_id=%s project_id=%s "
            "target_id=%s reason=already-member",
            actor.id, project_id, target_id,
        )
        target_url = url_for("project_view.show_project", project_id=project_id)
        return redirect(f"{target_url}?error={_ERR_ALREADY_MEMBER}")

    return redirect(url_for("project_view.show_project", project_id=project_id))


@bp.post("/projects/<int:project_id>/members/<int:user_id>/remove")
@require_auth
def remove_project_member(project_id: int, user_id: int):
    """Remove ``user_id`` from the member list of ``project_id``.

    Owner-based gate via :func:`can_manage_members`. The endpoint
    still enforces anti-self: an actor cannot remove themselves. The
    actor's permanent visibility into the project (admin / manager /
    owner / member) is enforced elsewhere; this check guards against
    the "I clicked my own row" footgun.
    """
    actor = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "project member remove 404 actor_id=%s project_id=%s user_id=%s",
            actor.id, project_id, user_id,
        )
        abort(404)

    _check_manage_members(actor, project, "remove")

    if int(user_id) == int(actor.id):
        logger.warning(
            "project member remove rejected actor_id=%s project_id=%s reason=self",
            actor.id, project_id,
        )
        abort(400, _ERR_SELF_REMOVE)

    target = _user_storage().find_by_id(user_id)
    if target is None:
        logger.info(
            "project member remove 404 actor_id=%s project_id=%s user_id=%s",
            actor.id, project_id, user_id,
        )
        abort(404, _ERR_USER_NOT_FOUND)

    # v0.7.2a — T0/T1 are auto-own; removing them from a project's
    # membership roster is meaningless and is rejected so a stale
    # project_members row from a v0.7.0 deployment cannot be silently
    # deleted. Mirrors the add endpoint's auto-own check above.
    if _is_auto_own(target):
        logger.warning(
            "project member remove rejected actor_id=%s project_id=%s "
            "user_id=%s reason=auto-own",
            actor.id, project_id, user_id,
        )
        abort(400, _ERR_AUTO_OWN_REMOVE)

    removed = storage.remove_member(project_id=project_id, user_id=user_id)
    if not removed:
        # The user was already not a member. We surface a 200-rendered
        # detail page with a flash-style error so the operator chasing
        # a stale page still gets a clear signal.
        logger.info(
            "project member remove rejected actor_id=%s project_id=%s "
            "user_id=%s reason=not-a-member",
            actor.id, project_id, user_id,
        )
        target_url = url_for("project_view.show_project", project_id=project_id)
        return redirect(f"{target_url}?error={_ERR_NOT_A_MEMBER}")

    return redirect(url_for("project_view.show_project", project_id=project_id))


__all__ = ["bp"]
