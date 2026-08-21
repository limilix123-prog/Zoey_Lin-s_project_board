"""Self-service registration endpoint.

GET renders the empty form. POST validates the username (non-empty, unique)
and the password (non-empty — strength policy is out of scope for the
current scope), hashes the password via
:mod:`project_board.accounts.feature_password`, and calls
:meth:`project_board.accounts.feature_storage.UserStorage.create_user`
with ``role='user'``. On success the user is redirected to ``/login`` with
a ``?registered=1`` query string so the login template can show a one-line
"account created" notice without needing a flash queue in ``base.html``.
"""

from __future__ import annotations

import logging
import sqlite3

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from ..accounts.feature_password import hash_password
from ..accounts.feature_storage import UserStorage
from ..rbac.feature_role import USER

logger = logging.getLogger(__name__)

bp = Blueprint("auth_register", __name__)

_USERNAME_FIELD: str = "username"
_PASSWORD_FIELD: str = "password"
_USERNAME_MIN: int = 1
_USERNAME_MAX: int = 64
_PASSWORD_MIN: int = 1
_PASSWORD_MAX: int = 1024
_REGISTERED_QUERY: str = "registered"
_REGISTERED_VALUE: str = "1"


def _storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _normalise_username(raw: str) -> str:
    return raw.strip()


def _form_data() -> dict[str, str]:
    return {
        _USERNAME_FIELD: _normalise_username(
            str(request.form.get(_USERNAME_FIELD, "") or "")
        ),
        _PASSWORD_FIELD: str(request.form.get(_PASSWORD_FIELD, "") or ""),
    }


def _validate(data: dict[str, str]) -> str | None:
    username = data[_USERNAME_FIELD]
    password = data[_PASSWORD_FIELD]
    if len(username) < _USERNAME_MIN or len(username) > _USERNAME_MAX:
        return "username must be 1-64 characters"
    if len(password) < _PASSWORD_MIN or len(password) > _PASSWORD_MAX:
        return "password must be 1-1024 characters"
    return None


@bp.get("/register")
def show_register_form():
    return render_template("register.html", form={"username": "", "password": ""}, notice=None)


@bp.post("/register")
def submit_register():
    data = _form_data()
    error = _validate(data)
    if error is not None:
        logger.info("register rejected validation: %s", error)
        return render_template(
            "register.html",
            form={"username": data[_USERNAME_FIELD], "password": ""},
            notice=None,
            error=error,
        ), 400

    username = data[_USERNAME_FIELD]
    password_hash = hash_password(data[_PASSWORD_FIELD])
    storage = _storage()
    try:
        new_id = storage.create_user(
            username=username,
            password_hash=password_hash,
            rank=4,  # T4 = user; v0.9.1 rank-based, role field deprecated
        )
    except sqlite3.IntegrityError:
        logger.info("register rejected duplicate username=%s", username)
        return render_template(
            "register.html",
            form={"username": username, "password": ""},
            notice=None,
            error="username already taken",
        ), 409

    logger.info("register ok user_id=%s username=%s rank=T4", new_id, username)
    return redirect(url_for("auth_login.show_login_form") + f"?{_REGISTERED_QUERY}={_REGISTERED_VALUE}")


__all__ = ["bp"]
