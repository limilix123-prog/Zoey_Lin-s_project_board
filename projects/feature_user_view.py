"""Per-user detail endpoint.

GET ``/users/<int:user_id>`` — read-only view of one user's account,
created projects, and project memberships. Reachable by every
authenticated user; anonymous visitors are redirected to ``/login``.

Scope
-----
The "Change rank" form stays on this page so admin / manager /
project_leader / team_leader viewers can re-assign the target's
T-scale rank per the rank-based RBAC matrix. A plain ``user`` (T4)
viewer sees the page but the form is hidden and a ``(read-only)``
placeholder is rendered. The form delegates to
``/users/<id>/rank`` (see :mod:`project_board.projects.feature_user_role`);
the same ``_available_new_ranks`` whitelist drives the ``<select>``
options so the UI never offers a value the server will reject.

Anti-self / anti-admin-template are still server-side: a viewer never
sees a form on their own row or on an admin (T0) row, because both
``_can_change_rank`` and the helper fall through to ``(self)`` /
``(permanent)`` placeholders. The actor-level ``can_change_rank``
flag hides the form entirely for plain ``user`` (T4) actors.

The ``POST /users/<id>/rank`` write path stays rank-gated at
``TEAM_LEADER``, so a plain user reaching ``/users/<id>`` still cannot
promote / demote anyone (server returns 403 on POST).

A non-existent ``user_id`` returns 404, not 403, so the existence of an id
is leaked only to viewers who could already enumerate the user list.

The viewer-rank tag is one of ``"self"`` (viewing your own row), ``"admin"``,
``"manager"``, ``"project_leader"``, ``"team_leader"`` (viewing as a
privileged role), or the viewer's own rank (e.g. ``"user"``) for
plain users that have read access but no write authority.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, abort, current_app, g, render_template, request

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_role import (
    ADMIN, MANAGER, PROJECT_LEADER, TEAM_LEADER,
    is_admin, is_manager, is_project_leader, is_team_leader,
)
from ..rbac.feature_require_auth import require_auth
from .feature_storage import ProjectStorage
from .feature_user_role import _available_new_ranks

logger = logging.getLogger(__name__)

bp = Blueprint("user_view", __name__)


def _user_storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _project_storage() -> ProjectStorage:
    cfg = current_app.config.get("PB_CONFIG")
    if cfg is None or "DB_PATH" not in cfg:
        raise RuntimeError("PB_CONFIG / DB_PATH not configured on Flask app")
    return ProjectStorage(cfg["DB_PATH"])


def _viewer_rank_label(viewer, target) -> str:
    """One-line tag for the "you are viewing as ..." sentence.

    Order matters: ``self`` first (a user viewing their own row), then
    ``admin`` / ``manager`` / ``project_leader`` / ``team_leader``
    based on the viewer's rank. The label is purely informational —
    RBAC has already passed in the decorator.

    v0.9.2 sub-task 3 — rank-based, reads ``viewer.rank`` instead of
    the deprecated ``viewer.role``.
    """
    if viewer.id == target.id:
        return "self"
    if is_admin(viewer):
        return "admin"
    if is_manager(viewer):
        return "manager"
    if is_project_leader(viewer):
        return "project_leader"
    if is_team_leader(viewer):
        return "team_leader"
    return "user"


def _owner_username_lookup(user_ids: set[int]) -> dict[int, str]:
    """Return ``{user_id: username}`` for the given ids (empty string for missing).

    Mirrors the helper in :mod:`project_board.projects.feature_me` so the
    owned / member lists on this page look identical to the /me equivalent.
    """
    lookup: dict[int, str] = {}
    storage = _user_storage()
    for uid in user_ids:
        row = storage.find_by_id(uid)
        lookup[int(uid)] = row.username if row is not None else ""
    return lookup


def _preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


_DESCRIPTION_PREVIEW_CHARS: int = 100


@bp.get("/users/<int:user_id>")
@require_auth
def show_user(user_id: int):
    viewer = g.current_user
    target = _user_storage().find_by_id(user_id)
    if target is None:
        logger.info(
            "user view 404 viewer_id=%s target_id=%s", viewer.id, user_id,
        )
        abort(404)

    project_storage = _project_storage()
    owned_rows = project_storage.list_owned_by(target.id)
    member_rows = project_storage.list_member_of(target.id)

    owner_ids = {r.owner_id for r in owned_rows} | {r.owner_id for r in member_rows}
    owner_names = _owner_username_lookup(owner_ids)

    def _to_item(row):
        return {
            "id": row.id,
            "name": row.name,
            "description_preview": _preview(row.description, _DESCRIPTION_PREVIEW_CHARS),
            "owner_username": owner_names.get(row.owner_id) or "",
            "created_at": row.created_at,
        }

    # actor-level flag for the template. Plain ``user`` (T4) actors
    # have an empty ``available_new_ranks`` so the form is hidden and
    # a ``(read-only)`` placeholder is rendered. Mirrors the same flag
    # in :mod:`project_board.projects.feature_users_list`.
    #

    # v0.9.2 sub-task 3 — rank-based. The actor's rank is what drives
    # the matrix; ``user.role`` is no longer consulted.
    actor_available = list(_available_new_ranks(viewer))
    can_change_rank = bool(actor_available)
    target_is_admin = int(target.rank) == 0  # T0 = admin

    ctx: dict[str, Any] = {
        "target_user": target,
        "owned_projects": [_to_item(r) for r in owned_rows],
        "member_projects": [_to_item(r) for r in member_rows],
        "viewer_rank_label": _viewer_rank_label(viewer, target),
        "actor_id": int(viewer.id),
        "actor_rank": int(viewer.rank),
        "is_self": viewer.id == target.id,
        "is_admin_target": target_is_admin,
        # actor-level flag — True iff the viewer has at least one rank
        # they could assign. Drives the actor-level block in the
        # template: when False the form is hidden entirely and a
        # ``(read-only)`` placeholder is rendered.
        "can_change_rank": can_change_rank,
        # Whitelist of ranks the viewer can assign *this* target to.
        # Empty when the row is the viewer themselves, an admin (T0),
        # or the viewer is a plain user (no form to render). Mirrors
        # the server-side ``_can_change_rank`` so the form's
        # <select> is always a subset of what the route will accept.
        "available_new_ranks": list(
            actor_available if not (
                viewer.id == target.id or target_is_admin
            ) else (),
        ),
        "notice": str(request.args.get("notice", "") or ""),
    }
    logger.info(
        "user view served viewer_id=%s viewer_rank=%s target_id=%s "
        "target_username=%s owned=%d member=%d can_change_rank=%s",
        viewer.id, int(viewer.rank), target.id, target.username,
        len(owned_rows), len(member_rows), can_change_rank,
    )
    return render_template("projects/user_view.html", **ctx)


__all__ = ["bp"]
