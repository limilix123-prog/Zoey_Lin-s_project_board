"""Sign-in endpoint.

GET renders the form. POST looks the user up by username, verifies the
password via :mod:`project_board.accounts.feature_password` (constant-time
compare inside), mints a server-side session via
:mod:`project_board.auth.feature_session`, and sets the ``pb_sid`` cookie
on the response. On success the user is redirected to ``/projects``.

The same response is returned for "unknown username" and "wrong password"
to avoid leaking which usernames exist; the log records the real reason
for operators.
"""

from __future__ import annotations

import logging

from flask import (
    Blueprint,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from ..accounts.feature_password import verify_password
from ..accounts.feature_storage import UserStorage
from .feature_session import SESSION_COOKIE_NAME, create_session

logger = logging.getLogger(__name__)

bp = Blueprint("auth_login", __name__)

_USERNAME_FIELD: str = "username"
_PASSWORD_FIELD: str = "password"
_LOGIN_NEXT_MAX: int = 256


def _storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _cookie_lifetime_seconds() -> int:
    hours = int(current_app.config["PB_CONFIG"]["SESSION_LIFETIME_HOURS"])
    return int(hours) * 3600


def _cookie_secure() -> bool:
    return bool(current_app.config["PB_CONFIG"]["SESSION_COOKIE_SECURE"])


def _safe_next(raw: str) -> str:
    """Return ``raw`` only if it is a same-site path starting with '/'.

    Prevents open-redirect via crafted ``?next=//evil.example/...``.
    """
    if not isinstance(raw, str) or len(raw) > _LOGIN_NEXT_MAX:
        return ""
    if not raw.startswith("/") or raw.startswith("//"):
        return ""
    return raw


@bp.get("/login")
def show_login_form():
    return render_template("login.html", form={"username": "", "password": ""})


@bp.post("/login")
def submit_login():
    username = str(request.form.get(_USERNAME_FIELD, "") or "").strip()
    password = str(request.form.get(_PASSWORD_FIELD, "") or "")
    next_url = _safe_next(str(request.form.get("next", "") or ""))

    storage = _storage()
    user = storage.find_by_username(username) if username else None
    password_ok = bool(user) and verify_password(password, user.password_hash)
    if user is None or not password_ok:
        logger.info(
            "login rejected username=%s user_found=%s password_ok=%s",
            username,
            user is not None,
            password_ok,
        )
        return render_template(
            "login.html",
            form={"username": username, "password": ""},
            error="invalid username or password",
        ), 401

    sid = create_session(user.id)
    target = next_url or url_for("projects_list.show_projects")
    response = make_response(redirect(target))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sid,
        max_age=_cookie_lifetime_seconds(),
        httponly=True,
        secure=_cookie_secure(),
        samesite="Lax",
        path="/",
    )
    logger.info("login ok user_id=%s username=%s", user.id, user.username)
    return response


__all__ = ["bp"]
