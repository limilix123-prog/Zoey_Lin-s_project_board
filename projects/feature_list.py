"""Project list endpoint.

GET ``/projects`` renders ``projects/templates/projects/list.html`` with
the projects the current user is allowed to see:

* admin / manager → every project (including the seeded system
  self-status row). The manager role joins the "sees all" set so the
  admin-nominated manager can audit every project the same way the
  bootstrap admin can.
* other users → projects they own or are a member of

The list is sourced from
:func:`project_board.projects.feature_storage.ProjectStorage.list_visible_to`,
which encodes the visibility rule server-side so the route handler is a
thin renderer.

Project rows do not carry the owner username — the dataclass mirrors the
``projects`` table. We collect the unique owner ids from the result and
look each one up through
:func:`project_board.accounts.feature_storage.UserStorage.find_by_id`,
which is the single read-side entry point for the users table.

Each item carries the ``is_system`` flag so the template can render
the ``(system)`` muted label and skip the Delete button for system
rows. The flag is read from the row's ``project_type`` column via the
:attr:`ProjectRow.is_system` accessor.

The ``is_admin_or_manager`` boolean passed to ``list_visible_to`` is
derived from ``_role_at_least(user, MANAGER)`` (rank-based, v0.9.1).
Earlier (pre-v0.9.2) the boolean came from ``user.role in (ADMIN,
MANAGER)``; that broke once ``User.role`` was deprecated to a
read-only field — ``user.role`` is now ``None`` for v0.9.2+ rows so
the comparison silently downgraded admin / manager to "sees only own"
which is wrong. The boolean is also reused for the template
``is_admin`` flag (drives the "Delete" link); manager is treated the
same as admin for template rendering.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import Blueprint, current_app, g, render_template

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_role import MANAGER, _role_at_least
from ..rbac.feature_require_auth import require_auth
from .feature_storage import ProjectStorage

logger = logging.getLogger(__name__)

bp = Blueprint("projects_list", __name__)

_DESCRIPTION_PREVIEW_CHARS: int = 100
_NEW_PROJECT_PATH: str = "/projects/new"


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


def _owner_username_lookup(user_ids: set[int]) -> dict[int, Optional[str]]:
    """Return ``{user_id: username or None}`` for every id in ``user_ids``.

    v0.9.2 sub-task 8 (perf 9 ops) -- N+1 to 1 query. The previous shape
    was one ``find_by_id`` per owner; the batch
    :meth:`UserStorage.find_usernames_by_ids` returns the
    same mapping in a single SELECT.
    """
    return _user_storage().find_usernames_by_ids(list(user_ids))


def _preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


@bp.get("/projects")
@require_auth
def show_projects():
    user = g.current_user
    # manager joins admin in the "sees every project" set. The boolean
    # is reused for the template ``is_admin`` flag so the "Delete" link
    # renders for manager too. Driven by ``_role_at_least`` (rank-based)
    # so v0.9.2+ rows (where ``user.role`` is None) still hit the
    # admin / manager branch correctly.
    is_admin_or_manager = bool(_role_at_least(user, MANAGER))

    project_storage = _project_storage()
    rows = project_storage.list_visible_to(user, is_admin=is_admin_or_manager)

    owner_ids = {r.owner_id for r in rows}
    owner_names = _owner_username_lookup(owner_ids)

    items: list[dict[str, Any]] = []
    has_system = False
    for row in rows:
        viewer_role = "owner" if row.owner_id == user.id else "member"
        if row.is_system:
            has_system = True
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "description_preview": _preview(
                    row.description, _DESCRIPTION_PREVIEW_CHARS
                ),
                "owner_username": owner_names.get(row.owner_id) or "",
                "created_at": row.created_at,
                "viewer_role": viewer_role,
                "is_system": bool(row.is_system),
            }
        )

    logger.info(
        "projects list served user_id=%s rank=%s is_admin_or_manager=%s "
        "count=%s has_system=%s",
        user.id,
        user.rank,
        is_admin_or_manager,
        len(items),
        has_system,
    )
    return render_template(
        "projects/list.html",
        items=items,
        new_project_url=_NEW_PROJECT_PATH,
        is_admin=is_admin_or_manager,
        has_system=has_system,
    )


__all__ = ["bp"]
