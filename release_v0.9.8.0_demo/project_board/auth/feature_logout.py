"""Sign-out endpoint.

Only POST is accepted — GET /logout is rejected with 405 to neutralise the
classic "embed an <img src='/logout'> to log the user out" CSRF gadget.
The :func:`require_auth` decorator is intentionally NOT applied here so a
user with an expired / missing cookie can still "log out" (which is a
no-op) and end up at the landing page.
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, make_response, redirect, request, url_for

from .feature_session import SESSION_COOKIE_NAME, destroy_session

logger = logging.getLogger(__name__)

bp = Blueprint("auth_logout", __name__)


@bp.post("/logout")
def submit_logout():
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if sid:
        destroy_session(sid)
        logger.info("logout sid_destroyed=true")
    else:
        logger.info("logout sid_destroyed=false no_cookie")
    response = make_response(redirect(url_for("index")))
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response


@bp.get("/logout", endpoint="logout_get_blocked")
def reject_get_logout():
    """Block GET /logout to defang image-tag / link-prefetch CSRF gadgets.

    v0.9.7p1 — delegate to Flask's 405 error handler so the visitor
    sees the same Chinese "方法不允许" page other 405 responses
    surface, rather than the bare English string the old code
    returned directly.
    """
    abort(405)


__all__ = ["bp"]
