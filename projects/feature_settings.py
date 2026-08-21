"""v0.9.1 — Project settings endpoint (name + description only).

v0.9.1 sub-task 2 (完整权限设计) added the **project settings
page** that combined the existing name / description edit and
the owner-change form into a single self-contained view.

v0.9.1 sub-task 4 — Issue 3: the owner-change form was
relocated to ``/projects/<int:project_id>/members`` (the
members page is now the single self-contained place to
manage members + owner). Settings is now **name + description
only** — a thin wrapper around
:meth:`ProjectStorage.update` (7/22 business-lock chokepoint).
The legacy ``POST /projects/<int:project_id>/owner`` endpoint
in :mod:`feature_project_owner` stays untouched (smoke v054
contract).

Endpoints
---------
``GET  /projects/<int:project_id>/settings``
    Render the settings page. Owner-based gate (auto-own /
    project owner); the form is hidden for everyone else
    (the route still 403s on a hand-crafted POST).

``POST /projects/<int:project_id>/settings``
    Submit the settings form. Two fields:

    * **name** — ``name`` (input text, required).
    * **description** — ``description`` (textarea, optional).

    Calls :meth:`ProjectStorage.update` (7/22 business-lock
    chokepoint). The chokepoint never accepts ``owner_id`` or
    ``project_type`` so a hand-crafted POST cannot mutate them.

HTML form contract (7/17 self-contained)
----------------------------------------
The settings page is **one self-contained view** — name +
description live on the same page, no cross-page jumps. The
form uses **HTML form fields** (input / textarea) — no JSON
textarea, no nested card / pill / badge primitives, no
client-side state machine. The 7/17 self-contained守门
principle applies: a project_leader that lands on the page
can read every field, edit every field, and submit without
clicking through to another URL.

The form is **idempotent** — re-submitting the same values
is a no-op at the storage layer (the name uniqueness check
fires only on a different name).
"""

from __future__ import annotations

import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_require_auth import require_auth
from .feature_role_v121 import (
    _BUCKET_AUTO_OWN,
    _BUCKET_OWNER,
    _resolve_role,
)
from .feature_storage import ProjectStorage, user_can_see_project
from .feature_storage_rbac import _is_auto_own

logger = logging.getLogger(__name__)

bp = Blueprint("project_settings", __name__)

# Form field names. Kept in sync with the ``settings.html``
# template — a future grep for ``_FIELD_NAME`` finds every
# site that reads / writes a form field.
_FIELD_NAME: str = "name"
_FIELD_DESCRIPTION: str = "description"

_NOTICE_SAVED: str = "Settings saved"


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


def _build_settings_context(user, project) -> dict:
    """Compute the settings page context.

    v0.9.1 sub-task 4 — Issue 3: the change-owner context was
    removed (the form is now on the members page). Settings is
    name + description only.

    Returns a dict the template can splat into ``render_template``.
    The context covers:

    * ``can_edit_meta`` — name + description are editable by
      the owner (auto-own / project owner). Mirrors the
      v0.7.2a ``can_manage_members`` gate so the rule is
      consistent across the project surface.
    * ``bucket`` — the actor's resolved RBAC bucket
      (informational; the form's "Save" button uses
      ``can_edit_meta`` to decide whether to render).
    """
    storage = _project_storage()
    bucket = _resolve_role(storage, user, project)
    can_edit_meta = bucket in (_BUCKET_AUTO_OWN, _BUCKET_OWNER)
    return {
        "can_edit_meta": bool(can_edit_meta),
        "bucket": bucket or "",
    }


@bp.get("/projects/<int:project_id>/settings")
@require_auth
def show_settings(project_id: int):
    """Render the project settings page.

    Read-side gate via :func:`user_can_see_project` — any
    signed-in user that can see the project can land on the
    page (the form is hidden for non-editors). A user that
    cannot see the project gets a 404 (never leak existence).
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    owner_row = _user_storage().find_by_id(int(project.owner_id))
    owner_username = (
        str(owner_row.username) if owner_row is not None else ""
    )
    ctx = _build_settings_context(user, project)
    return render_template(
        "projects/settings.html",
        project=project,
        owner_username=owner_username,
        notice=request.args.get("notice", ""),
        error=request.args.get("error", ""),
        **ctx,
    )


@bp.post("/projects/<int:project_id>/settings")
@require_auth
def submit_settings(project_id: int):
    """Submit the settings form.

    v0.9.1 sub-task 4 — Issue 3: the owner-change field was
    removed (the form lives on the members page now). The
    2-field form contract is:

    * ``name`` (input text, required) — the project's new
      name. Empty / whitespace triggers a 400.
    * ``description`` (textarea, optional) — the project's
      new description. Empty string is allowed (it clears
      the description).

    The route delegates to :meth:`ProjectStorage.update` —
    the 7/22 business-lock chokepoint. The write is wrapped
    in a try / except so a name uniqueness conflict surfaces
    as a 200-rendered page with a flash-style error
    (matching the rest of the project surface).
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    bucket = _resolve_role(storage, user, project)
    if bucket not in (_BUCKET_AUTO_OWN, _BUCKET_OWNER):
        logger.warning(
            "v0.9.1 settings submit denied actor_id=%s project_id=%s "
            "reason=not-in-edit-bucket",
            int(user.id), int(project_id),
        )
        abort(403, "you cannot edit this project's settings")

    raw_name = str(
        request.form.get(_FIELD_NAME, project.name) or ""
    ).strip()
    raw_description = str(
        request.form.get(_FIELD_DESCRIPTION, project.description) or ""
    )
    if not raw_name:
        return redirect(
            url_for(
                "project_settings.show_settings",
                project_id=project_id,
            )
            + "?error=name is required"
        )

    try:
        storage.update(
            project_id=int(project_id),
            name=raw_name,
            description=raw_description,
        )
    except Exception as exc:  # sqlite3.IntegrityError on duplicate name
        logger.info(
            "v0.9.1 settings update failed actor_id=%s project_id=%s "
            "error=%s",
            int(user.id), int(project_id), exc,
        )
        return redirect(
            url_for(
                "project_settings.show_settings",
                project_id=project_id,
            )
            + f"?error={str(exc)[:120]}"
        )

    notice = _NOTICE_SAVED
    return redirect(
        url_for(
            "project_settings.show_settings",
            project_id=project_id,
        )
        + f"?notice={notice}"
    )


__all__ = ["bp"]
