"""Help / glossary endpoint.

v0.9.5 P0-4 — single source of truth for the T0..T4 rank scale
plus the project / node / role-grant terms that the v0.9.x
modules introduced. The page is reachable from the top nav's
"帮助" link so a first-time visitor can land on a glossary
without first having to ask.

The page is static content; the route lives in a tiny
single-blueprint module so adding more help pages later (e.g.
a "How do I create a project?" walkthrough) is just another
``@bp.get`` line in this file. The template lives under
``app/templates/help/`` so it is reachable from the same
Jinja loader as the rest of the cross-module views.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, render_template, request

from ..auth.feature_session import SESSION_COOKIE_NAME, get_session
from ..accounts.feature_storage import UserStorage
from flask import current_app

logger = logging.getLogger(__name__)

bp = Blueprint("help", __name__)


def _resolve_current_user() -> None:
    """Set ``g.current_user`` if a valid session cookie is present.

    v0.9.5 P0-4 — the glossary page is public (no ``@require_auth``)
    so ``g.current_user`` is normally not set on a ``/help/glossary``
    request. Without this helper the ``base.html`` nav renders the
    anonymous branch ("Log in" / "Register" / "帮助") even when
    the visitor is signed in — confusing for a logged-in user
    who clicks "帮助" and sees the nav switch to anonymous.

    The helper runs in a ``before_request`` filter on the
    ``help`` blueprint so it only affects help routes (other
    public routes like ``/login`` and ``/register`` keep their
    own auth behaviour). The lookup mirrors the cookie-→-user
    resolution in ``rbac.feature_require_auth`` so the nav
    reflects the same auth state across all pages.
    """
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        return
    user_id = get_session(sid)
    if user_id is None:
        return
    storage = current_app.config.get("PB_STORAGE")
    if not isinstance(storage, UserStorage):
        return
    row = storage.find_by_id(user_id)
    if row is not None:
        g.current_user = row


@bp.before_request
def _before_request() -> None:
    _resolve_current_user()


@bp.get("/help/glossary")
def show_glossary():
    """Render the T0..T4 + RBAC + 6-level tree + role-grant glossary.

    The page is public (no ``@require_auth``) so a first-time
    visitor who hit a 404 / 403 can still reach the glossary
    from the error page's "帮助" link. The content is static;
    a future revision can fetch counts (e.g. "currently N
    active projects") from storage without breaking the URL.
    """
    # v0.9.5 P0-4 — ``g.current_user`` is set by the
    # before-request hook when a valid session cookie is present.
    # The attribute may not exist on ``g`` for anonymous visitors
    # (Flask raises ``AttributeError`` on ``g.<missing>``), so
    # ``getattr(..., None)`` keeps the log line safe.
    user = getattr(g, "current_user", None)
    user_id = getattr(user, "id", None) if user is not None else None
    logger.info("help glossary served user_id=%s", user_id)
    return render_template("help/glossary.html")
