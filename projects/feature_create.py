"""Project create endpoint.

GET  /projects/new          — render the form (T0/T1/T2 only)
POST /projects/new          — validate + ProjectStorage.create() + redirect

The :func:`require_role` decorator puts the current user on ``g.current_user``
or rejects the request with a 403. Project name is unique across the table
(UNIQUE constraint in ``projects`` schema) — duplicate inserts raise
``sqlite3.IntegrityError`` which the handler maps back to the form with an
error string.

v0.7.2a revert RBAC (8/7 user 拍板)
-------------------------------
v0.7.2a briefly relaxed the gate to ``@require_role(PROJECT_LEADER)``
(T0/T1/T2 could create), but the owner-based matrix only authorises
admin / manager to create. The endpoint is now gated by
``@require_role(MANAGER)`` (rank 4 on the v0.7.0 5-role scale), so
the gate accepts admin / manager (T0 / T1 in the v0.7.1 T-scale) and
rejects project_leader / team_leader / user (T2 / T3 / T4) with a
403 from the decorator before any handler logic runs. This restores
the v0.7.0 behaviour and matches the smoke_v055 expectation that
only admin and manager may create projects. The form additionally
carries an ``owner_id`` field so
the actor can pick the project's owner. The field defaults to the
actor's own id when the form is submitted blank but the field is
always rendered so the actor can hand the project to a different
user in the same submission. The server validates that ``owner_id``
resolves to an existing user row; a missing or non-integer value is
surfaced as a 200-rendered error so the form re-renders with the
existing inputs preserved. No role restriction is applied to the
owner — any role (T0..T4) can own a project, matching the rest of
the storage layer.

The project_type radio is gone. Only two types exist — ``system``
(the platform self-status project, seeded at boot and non-creatable)
and ``common`` (every new project). The form no longer renders a
type field; the handler hardcodes ``"common"`` so a form that never
sends the field creates a common project. As a defence-in-depth
business lock (7/22), a hand-crafted POST that explicitly sends
``project_type=system`` is rejected with a **400** — system rows
are reserved for the app-factory seed in :func:`create_app` and
must not be creatable via the user-facing API. Any other
``project_type`` value (``user``, ``admin``, garbage) is silently
ignored and the row is written as ``"common"``, matching the form's
"there's only one type" promise.
"""

from __future__ import annotations

import logging
import sqlite3

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
from ..rbac.feature_require_auth import require_role
from ..rbac.feature_role import MANAGER
from .feature_storage import ProjectStorage

logger = logging.getLogger(__name__)

bp = Blueprint("project_create", __name__)

_NAME_FIELD: str = "name"
_DESCRIPTION_FIELD: str = "description"
_OWNER_ID_FIELD: str = "owner_id"
_TYPE_FIELD: str = "project_type"  # only read for the system-reject guard

_NAME_MAX: int = 200
_DESCRIPTION_MAX: int = 4000

_TYPE_COMMON: str = "common"
_TYPE_SYSTEM: str = "system"

_ERR_NAME_REQUIRED: str = "project name is required"
_ERR_NAME_TAKEN: str = "project name taken"
_ERR_NAME_TOO_LONG: str = f"project name must be at most {_NAME_MAX} characters"
_ERR_DESC_TOO_LONG: str = f"description must be at most {_DESCRIPTION_MAX} characters"
_ERR_SYSTEM_NOT_CREATABLE: str = "system project cannot be created via API"
_ERR_OWNER_INVALID: str = "owner_id must be an integer"
_ERR_OWNER_NOT_FOUND: str = "owner user not found"


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


def _form_data() -> dict[str, str]:
    """Pull the form fields the handler re-echoes on validation failure.

    ``project_type`` is no longer a form input. The field is still read
    from the form so a hand-crafted POST that tries to smuggle
    ``project_type=system`` can be rejected with 400 in
    :func:`submit_new_project` (defence in depth, 7/22 business lock).
    The string is preserved as-typed so the error path can log the
    bad value verbatim.
    """
    name = str(request.form.get(_NAME_FIELD, "") or "").strip()
    description = str(request.form.get(_DESCRIPTION_FIELD, "") or "").strip()
    raw_type = str(request.form.get(_TYPE_FIELD, "") or "").strip().lower()
    # owner_id is optional in the form (blank = default to the actor).
    # The string is preserved here so the template can echo the bad
    # input on a validation failure; the POST handler parses it.
    owner_id_raw = str(request.form.get(_OWNER_ID_FIELD, "") or "").strip()
    return {
        _NAME_FIELD: name,
        _DESCRIPTION_FIELD: description,
        _TYPE_FIELD: raw_type,
        _OWNER_ID_FIELD: owner_id_raw,
    }


def _owner_dropdown(actor_id: int) -> list[dict[str, object]]:
    """Return ``[{"id", "username", "rank", "role", "is_self"}]`` sorted.

    Used by both the GET (render empty form) and POST (re-render with
    error) handlers. ``is_self`` is True for the actor's own row so the
    template can mark the default selection without re-deriving the
    comparison. The dropdown lists every user — including admin and
    manager rows — because the RBAC matrix does not restrict which
    role a project owner may hold.

    v0.9.2 sub-task 3 — rank added; ``role`` retained for any legacy
    reader. The template renders the T-level (``T{{ u.rank }}``) per
    the v0.9.1 rank-based RBAC migration.
    """
    rows = _user_storage().list_all_users()
    out: list[dict[str, object]] = []
    for u in rows:
        out.append(
            {
                "id": int(u.id),
                "username": str(u.username),
                "rank": int(u.rank),
                "role": str(u.role),
                "is_self": int(u.id) == int(actor_id),
            }
        )
    out.sort(key=lambda r: (str(r["username"]).lower(), int(r["id"])))
    return out


def _render_form(
    user,
    *,
    error: str | None,
    form: dict[str, str],
) -> str:
    """Render ``projects/new.html`` with the standard GET/POST context.

    ``can_create_system`` is gone — the template no longer branches on
    the actor's role to decide whether to render the system radio,
    because there is no radio to render. The owner dropdown is rebuilt
    on every call so the POST error re-render shows the same user list
    as the GET empty form.
    """
    return render_template(
        "projects/new.html",
        error=error,
        form=form,
        all_users=_owner_dropdown(int(user.id)),
        default_owner_id=int(user.id),
        actor_username=str(user.username),
    )


@bp.get("/projects/new")
@require_role(MANAGER)
def show_new_project():
    user = g.current_user
    return _render_form(user, error=None, form={})


@bp.post("/projects/new")
@require_role(MANAGER)
def submit_new_project():
    user = g.current_user
    data = _form_data()
    name = data[_NAME_FIELD]
    description = data[_DESCRIPTION_FIELD]
    raw_type = data[_TYPE_FIELD]
    owner_id_raw = data[_OWNER_ID_FIELD]

    # system rows are reserved for the app-factory seed. A
    # hand-crafted POST that sends project_type=system is rejected
    # with a 400 (not a 200-rendered form) because the request is
    # structurally invalid — system is not a creatable type, so
    # there is no form state worth re-rendering.

    # Any other type value is ignored; the row lands as "common".
    if raw_type == _TYPE_SYSTEM:
        logger.info(
            "project create rejected system attempt user_id=%s role=%s",
            user.id, user.role,
        )
        abort(400, description=_ERR_SYSTEM_NOT_CREATABLE)

    if not name:
        return _render_form(user, error=_ERR_NAME_REQUIRED, form=data)
    if len(name) > _NAME_MAX:
        return _render_form(user, error=_ERR_NAME_TOO_LONG, form=data)
    if len(description) > _DESCRIPTION_MAX:
        return _render_form(user, error=_ERR_DESC_TOO_LONG, form=data)

    # owner_id parsing + validation. A blank value falls back to the
    # actor's own id. A non-blank value must be a valid integer
    # pointing at an existing user row. A missing user is surfaced as
    # a 200-rendered error so the form re-renders with the actor's
    # input preserved.
    if not owner_id_raw:
        owner_id = int(user.id)
    else:
        try:
            owner_id = int(owner_id_raw)
        except ValueError:
            logger.info(
                "project create rejected bad owner_id user_id=%s raw=%r",
                user.id, owner_id_raw,
            )
            return _render_form(user, error=_ERR_OWNER_INVALID, form=data)
        target = _user_storage().find_by_id(owner_id)
        if target is None:
            logger.info(
                "project create rejected missing owner user_id=%s owner_id=%s",
                user.id, owner_id,
            )
            return _render_form(user, error=_ERR_OWNER_NOT_FOUND, form=data)

    storage = _project_storage()
    try:
        new_id = storage.create(
            name=name,
            description=description,
            owner_id=owner_id,
            project_type=_TYPE_COMMON,
        )
    except sqlite3.IntegrityError:
        logger.info("project create rejected dup name=%s by user_id=%s", name, user.id)
        return _render_form(user, error=_ERR_NAME_TAKEN, form=data)

    logger.info(
        "project create id=%s name=%s actor_id=%s owner_id=%s",
        new_id, name, user.id, owner_id,
    )
    return redirect(url_for("project_view.show_project", project_id=new_id))


__all__ = ["bp"]
