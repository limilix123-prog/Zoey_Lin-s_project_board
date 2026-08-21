"""Change-password endpoint.

POST ``/profile/password`` reads ``old_password`` / ``new_password`` /
``confirm_password`` from the form, validates them, hashes the new
password via :mod:`project_board.accounts.feature_password`, and writes
the new hash through :meth:`project_board.accounts.feature_storage.UserStorage.update_password`.

Failure modes all re-render the consolidated ``me.html``
(:mod:`project_board.projects.feature_me`) with a single error string.
The messages are deliberately coarse so the response never reveals
"user does not exist" vs "old password wrong" (the two are collapsed to
one user-facing string). The shape of the error space:

* ``old_password`` wrong OR current user row vanished → "wrong old password"
* ``new_password`` empty → "new password must not be empty"
* ``new_password`` and ``confirm_password`` disagree → "new passwords do not match"

On success, redirects to ``/me?changed=1`` (the consolidated profile
page reads the query string and shows a one-line confirmation in its
``notice`` block — no flash queue needed in ``base.html``).

The endpoint URL (``/profile/password``) is preserved so external
bookmarks and tests stay green; the form on the new ``/me`` page
already POSTs to it. The full me.html context (owned / member project
lists, owner usernames) is rebuilt in the failure path via the helper
in :mod:`project_board.projects.feature_me` so the rendered page is
shape-identical to a fresh GET on ``/me`` with the same ``error``
string in place of the absent ``notice``.
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for

from ..accounts.feature_password import hash_password, verify_password
from ..accounts.feature_storage import UserStorage
from ..projects.feature_me import (
    build_project_items,
    owner_username_lookup,
)
from ..rbac.feature_require_auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("profile_change_password", __name__)

_OLD_FIELD: str = "old_password"
_NEW_FIELD: str = "new_password"
_CONFIRM_FIELD: str = "confirm_password"
_PASSWORD_MAX: int = 1024

_ERR_OLD: str = "wrong old password"
_ERR_EMPTY: str = "new password must not be empty"
_ERR_MISMATCH: str = "new passwords do not match"


def _storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _project_storage():
    cfg = current_app.config.get("PB_CONFIG")
    if cfg is None or "DB_PATH" not in cfg:
        raise RuntimeError("PB_CONFIG / DB_PATH not configured on Flask app")
    # Local import to keep the project's storage layer un-imported at
    # module import time (mirrors the pattern in feature_create / feature_view).
    from ..projects.feature_storage import ProjectStorage

    return ProjectStorage(cfg["DB_PATH"])


def _form_data() -> dict[str, str]:
    return {
        _OLD_FIELD: str(request.form.get(_OLD_FIELD, "") or ""),
        _NEW_FIELD: str(request.form.get(_NEW_FIELD, "") or ""),
        _CONFIRM_FIELD: str(request.form.get(_CONFIRM_FIELD, "") or ""),
    }


def _too_long(value: str) -> bool:
    return len(value) > _PASSWORD_MAX


@bp.post("/profile/password")
@require_auth
def submit_change_password():
    data = _form_data()
    old_password = data[_OLD_FIELD]
    new_password = data[_NEW_FIELD]
    confirm_password = data[_CONFIRM_FIELD]

    cached = g.current_user
    fresh = _storage().find_by_id(cached.id)

    # Re-render helper — keeps the form open and surfaces the error inline.
    # Rebuilds the full me.html context so the failure path renders a
    # shape-identical page to a fresh /me GET (account info, change-password
    # form, owned projects, member projects).
    def _fail(error: str):
        logger.info(
            "change_password rejected user_id=%s error=%s",
            cached.id,
            error,
        )
        user_for_render = fresh if fresh is not None else cached
        project_storage = _project_storage()
        owned_rows = project_storage.list_owned_by(user_for_render.id)
        member_rows = project_storage.list_member_of(user_for_render.id)
        all_owner_ids = {r.owner_id for r in owned_rows} | {r.owner_id for r in member_rows}
        owner_names = owner_username_lookup(all_owner_ids)
        return render_template(
            "projects/me.html",
            user=user_for_render,
            notice=None,
            error=error,
            owned_projects=build_project_items(owned_rows, owner_names),
            member_projects=build_project_items(member_rows, owner_names),
            change_password_url="/profile/password",
            logout_url="/logout",
            new_project_url="/projects/new",
        ), 400

    if fresh is None or not verify_password(old_password, fresh.password_hash):
        return _fail(_ERR_OLD)

    if new_password == "":
        return _fail(_ERR_EMPTY)

    if new_password != confirm_password:
        return _fail(_ERR_MISMATCH)

    if _too_long(new_password):
        return _fail(_ERR_EMPTY)

    new_hash = hash_password(new_password)
    _storage().update_password(fresh.id, new_hash)
    logger.info("change_password ok user_id=%s", fresh.id)
    return redirect(url_for("me.show_me") + "?changed=1")


__all__ = ["bp"]
