"""v0.9.1 — Project-level name + description edit endpoints.

GET  /projects/<int:project_id>/edit   — render the form
POST /projects/<int:project_id>/edit   — validate + ProjectStorage.update() + redirect

7/22 RBAC business-lock principle
---------------------------------
The :func:`require_role` decorator and the
:func:`can_manage_members` helper together form the write gate.
The actual UPDATE is **never** issued by the route handler directly
— the handler always goes through :meth:`ProjectStorage.update`,
the single chokepoint for the two user-facing columns. A
hand-crafted POST that smuggles ``owner_id`` or ``project_type``
is silently dropped because the storage method's parameter list
does not include those columns (the route layer never reads them
from the form either).

The v0.9.1 endpoint is gated by :func:`can_manage_members` (admin /
manager auto-own every project, otherwise the actor must be the
project owner). ``team_leader`` and plain ``user`` (members) are
read-only — they cannot reach the form (404) and a hand-crafted
POST gets 403.

Form contract
-------------
``name`` (required, ≤ 200 chars) + ``description`` (optional, ≤
4000 chars). Project name is unique across the table (UNIQUE
constraint in ``projects`` schema) — duplicate updates raise
``sqlite3.IntegrityError`` which the handler maps back to the
form with an error string. No role restriction is applied to the
fields; any project name the actor types is accepted as long as it
is non-empty and unique.
"""

from __future__ import annotations

import logging
import sqlite3

from flask import (
    Blueprint,
    current_app,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from ..rbac.feature_require_auth import require_auth
from .feature_storage import ProjectStorage, can_manage_members

logger = logging.getLogger(__name__)

bp = Blueprint("project_edit", __name__)

_NAME_FIELD: str = "name"
_DESCRIPTION_FIELD: str = "description"

_NAME_MAX: int = 200
_DESCRIPTION_MAX: int = 4000

_ERR_NAME_REQUIRED: str = "project name is required"
_ERR_NAME_TAKEN: str = "project name taken"
_ERR_NAME_TOO_LONG: str = f"project name must be at most {_NAME_MAX} characters"
_ERR_DESC_TOO_LONG: str = (
    f"description must be at most {_DESCRIPTION_MAX} characters"
)
_ERR_FORBIDDEN: str = "you cannot edit this project"


def _project_storage() -> ProjectStorage:
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


def _form_data() -> dict[str, str]:
    """Pull the form fields the handler re-echoes on validation failure.

    The values are trimmed so a stray space does not become a
    "duplicate name" surprise (storage layer still re-validates).
    """
    name = str(request.form.get(_NAME_FIELD, "") or "").strip()
    description = str(request.form.get(_DESCRIPTION_FIELD, "") or "").strip()
    return {
        _NAME_FIELD: name,
        _DESCRIPTION_FIELD: description,
    }


def _render_form(
    project,
    *,
    error: str | None,
    form: dict[str, str],
) -> str:
    """Render ``projects/edit.html`` with the standard GET/POST context."""
    return render_template(
        "projects/edit.html",
        project=project,
        error=error,
        form=form,
    )


def _check_can_edit(user, project) -> None:
    """Owner-based gate; abort 403 if the actor cannot edit the project.

    Shares the :func:`can_manage_members` rule (admin / manager
    auto-own every project; otherwise the actor must be the project
    owner). System projects (the platform self-status project) are
    permanent — even an admin cannot rename them. That guard is
    enforced here because the storage layer's ``update()`` is
    intentionally policy-agnostic.
    """
    if project.is_system:
        logger.warning(
            "project edit denied system project actor_id=%s project_id=%s "
            "(403 — system projects are permanent)",
            user.id, project.id,
        )
        from flask import abort
        abort(403, "system project is permanent")
    if can_manage_members(user, project):
        return
    logger.warning(
        "project edit denied actor_id=%s project_id=%s role=%s owner_id=%s "
        "(403 — not admin/manager and not owner)",
        user.id, project.id, user.role, project.owner_id,
    )
    from flask import abort
    abort(403, _ERR_FORBIDDEN)


@bp.get("/projects/<int:project_id>/edit")
@require_auth
def show_edit_project(project_id: int):
    """Render the edit form for ``project_id``.

    The route is gated by :func:`can_manage_members` so a non-owner
    gets 403, never 404, so the existence of the project is
    acknowledged (matches the member-management endpoints' UX).
    """
    from flask import abort

    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "project edit 404 actor_id=%s project_id=%s",
            user.id, project_id,
        )
        abort(404)
    _check_can_edit(user, project)
    logger.info(
        "project edit form project_id=%s actor_id=%s",
        project.id, user.id,
    )
    return _render_form(
        project,
        error=None,
        form={
            _NAME_FIELD: str(project.name),
            _DESCRIPTION_FIELD: str(project.description or ""),
        },
    )


@bp.post("/projects/<int:project_id>/edit")
@require_auth
def submit_edit_project(project_id: int):
    """Validate + ProjectStorage.update() + redirect back to the project view.

    The route is gated by :func:`can_manage_members` and the
    system-permanent rule (above). The handler **only** passes
    ``name`` and ``description`` to the storage layer so a
    hand-crafted POST cannot smuggle ``owner_id`` or
    ``project_type`` (7/22 business-lock principle).
    """
    from flask import abort

    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "project edit submit 404 actor_id=%s project_id=%s",
            user.id, project_id,
        )
        abort(404)
    _check_can_edit(user, project)

    data = _form_data()
    name = data[_NAME_FIELD]
    description = data[_DESCRIPTION_FIELD]

    if not name:
        return _render_form(project, error=_ERR_NAME_REQUIRED, form=data)
    if len(name) > _NAME_MAX:
        return _render_form(project, error=_ERR_NAME_TOO_LONG, form=data)
    if len(description) > _DESCRIPTION_MAX:
        return _render_form(project, error=_ERR_DESC_TOO_LONG, form=data)

    try:
        changed = storage.update(
            project_id=project_id,
            name=name,
            description=description,
        )
    except sqlite3.IntegrityError:
        logger.info(
            "project edit rejected dup name=%s project_id=%s by user_id=%s",
            name, project.id, user.id,
        )
        return _render_form(project, error=_ERR_NAME_TAKEN, form=data)

    logger.info(
        "project edit project_id=%s actor_id=%s changed=%s",
        project.id, user.id, changed,
    )
    return redirect(url_for("project_view.show_project", project_id=project.id))


__all__ = ["bp"]
