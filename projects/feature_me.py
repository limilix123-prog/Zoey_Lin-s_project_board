"""Consolidated /me page.

GET ``/me`` renders :mod:`project_board.app.templates.me` with four
self-contained blocks (no card / border / shadow chrome — UI principle
"页面要 self-contained",层级靠 ``<h2>`` + ``padding-left``):

1. **Account** — username / role / member since
2. **Change password** — POSTs to ``/profile/password`` (handled by
   :mod:`project_board.profile.feature_change_password`, retained as a
   stable URL by user demand)
3. **My projects** — every project the current user owns
4. **Projects I'm a member of** — every project the current user is a
   member of, *excluding* projects they own (server-side enforced in
   :meth:`ProjectStorage.list_member_of`)

The /me handler re-fetches the User row from storage so a password
change or role promotion that landed between the cookie check and the
render is reflected on the page. The "changed=1" query parameter is
read from ``request.args`` so the password-update flow can redirect to
``/me?changed=1`` and surface a one-line confirmation without a flash
queue in ``base.html``.

The owner-username lookup and project-item builder are exposed as
module-level helpers (:func:`owner_username_lookup`,
:func:`build_project_items`) so :mod:`project_board.profile.feature_change_password`
can re-render ``me.html`` on the validation-failure path with the same
context shape — single source of truth for the me-page block format.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import Blueprint, current_app, g, render_template, request

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_require_auth import require_auth
from .feature_storage import ProjectStorage, ProjectRow

logger = logging.getLogger(__name__)

bp = Blueprint("me", __name__)

_DESCRIPTION_PREVIEW_CHARS: int = 100
_CHANGE_PASSWORD_PATH: str = "/profile/password"
_LOGOUT_PATH: str = "/logout"
_NEW_PROJECT_PATH: str = "/projects/new"
_CHANGED_QUERY: str = "changed"
_CHANGED_VALUE: str = "1"
_OK_NOTICE: str = "Password updated."


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


def owner_username_lookup(user_ids: set[int]) -> dict[int, Optional[str]]:
    """Return ``{user_id: username or None}`` for every id in ``user_ids``.

    Public so :mod:`project_board.profile.feature_change_password` can
    reuse the exact same lookup when it re-renders ``me.html`` on the
    password-validation failure path.
    """
    lookup: dict[int, Optional[str]] = {}
    storage = _user_storage()
    for uid in user_ids:
        row = storage.find_by_id(uid)
        lookup[uid] = row.username if row is not None else None
    return lookup


def _preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_project_items(
    rows: list[ProjectRow],
    owner_names: dict[int, Optional[str]],
) -> list[dict[str, Any]]:
    """Project rows → dicts ready for the me.html list blocks.

    Public so :mod:`project_board.profile.feature_change_password` can
    rebuild the same context on the password-validation failure path
    without duplicating the projection logic.
    """
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "description_preview": _preview(
                    row.description, _DESCRIPTION_PREVIEW_CHARS
                ),
                "owner_username": owner_names.get(row.owner_id) or "",
                "created_at": row.created_at,
            }
        )
    return items


def _me_context(
    user,
    project_storage: ProjectStorage,
    notice: Optional[str],
    error: Optional[str],
) -> dict[str, Any]:
    """Build the full template context for ``me.html``.

    Used by both the GET handler and the change-password failure path;
    keeps the projection in one place so the two callers cannot drift.
    """
    owned_rows = project_storage.list_owned_by(user.id)
    member_rows = project_storage.list_member_of(user.id)
    all_owner_ids = {r.owner_id for r in owned_rows} | {r.owner_id for r in member_rows}
    owner_names = owner_username_lookup(all_owner_ids)
    return {
        "user": user,
        "notice": notice,
        "error": error,
        "owned_projects": build_project_items(owned_rows, owner_names),
        "member_projects": build_project_items(member_rows, owner_names),
        "change_password_url": _CHANGE_PASSWORD_PATH,
        "logout_url": _LOGOUT_PATH,
        "new_project_url": _NEW_PROJECT_PATH,
    }


@bp.get("/me")
@require_auth
def show_me():
    user = g.current_user
    notice: Optional[str] = None
    if request.args.get(_CHANGED_QUERY) == _CHANGED_VALUE:
        notice = _OK_NOTICE
    project_storage = _project_storage()
    ctx = _me_context(user, project_storage, notice=notice, error=None)
    logger.info(
        "me page served user_id=%s role=%s owned=%d member=%d",
        user.id,
        user.role,
        len(ctx["owned_projects"]),
        len(ctx["member_projects"]),
    )
    return render_template("projects/me.html", **ctx)


__all__ = ["bp", "build_project_items", "owner_username_lookup"]
