"""Auth decorators built on the server-side session table.

Both decorators read the current user from the request-scoped session cookie
(``sid``) and resolve it against the storage layer. They never trust client
state — the cookie value is opaque and only meaningful as a key into the
``sessions`` table owned by the storage layer.

The session cookie name is owned by :mod:`project_board.auth.feature_session`
so this module just imports the public constant instead of duplicating the
string literal.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from flask import abort, current_app, jsonify, redirect, request, url_for

from ..accounts.feature_storage import UserStorage
from ..auth.feature_session import SESSION_COOKIE_NAME as _SESSION_COOKIE_NAME
from .feature_role import is_known_role, _role_at_least

logger = logging.getLogger(__name__)

_LOGIN_ENDPOINT = "auth_login.show_login_form"


def _storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None:
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    if not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE is not a UserStorage instance")
    return storage


def _current_user():
    """Return User from the session cookie, or None if absent / expired."""
    sid = request.cookies.get(_SESSION_COOKIE_NAME)
    if not sid:
        return None
    row = _storage().get_session(sid)
    if row is None:
        return None
    user_id, _expires_at = row
    return _storage().find_by_id(user_id)


def require_auth(view: Callable[..., Any]) -> Callable[..., Any]:
    """Reject anonymous requests; otherwise inject ``g.current_user`` and call."""

    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        from flask import g

        user = _current_user()
        if user is None:
            if _wants_json():
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for(_LOGIN_ENDPOINT, next=request.path))
        g.current_user = user
        return view(*args, **kwargs)

    return wrapper


def require_role(required: str):
    """Reject if user is missing or does not have ``required`` role."""

    if not isinstance(required, str) or not is_known_role(required):
        raise ValueError(f"require_role: unknown role {required!r}")

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            from flask import g

            user = _current_user()
            if user is None:
                if _wants_json():
                    return jsonify({"error": "authentication required"}), 401
                return redirect(url_for(_LOGIN_ENDPOINT, next=request.path))
            # v0.9.5 P0-2 — set ``g.current_user`` BEFORE the
            # role check so the error handler (which renders
            # the localised 403 page) sees the user. Previous
            # code set ``g.current_user`` only on success;
            # deny branch now renders HTML, so set on both.
            g.current_user = user
            if not _role_at_least(user, required):
                logger.warning(
                    "rbac deny user_id=%s required=%s rank=%s path=%s",
                    user.id,
                    required,
                    user.rank,
                    request.path,
                )
                # v0.9.5 P0-2 — content-negotiated 403. JSON
                # clients keep the legacy body so the machine-
                # readable contract is unchanged. Browsers get
                # the localised HTML 403 via ``abort(403)``.
                # 7/22 RBAC business lock preserved.
                if _wants_json():
                    return jsonify({"error": "forbidden"}), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def _wants_json() -> bool:
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


__all__ = ["require_auth", "require_role"]
