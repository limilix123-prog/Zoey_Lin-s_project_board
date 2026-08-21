"""Server-side session abstraction.

Wraps the ``sessions`` table in :mod:`project_board.accounts.feature_storage`
so route handlers never touch SQL directly. A session is identified by an
opaque ``sid`` string sent to the browser as a cookie; the cookie's only
job is to carry that opaque token back to the server, which is the only
place that can resolve it to a user via the storage layer.

The session cookie name is the single source of truth for the
:data:`SESSION_COOKIE_NAME` constant — both the rbac reader
(``rbac.feature_require_auth``) and the Flask config
(``app.feature_app_factory._configure_app``) import it from here
so a rename in one place automatically propagates everywhere.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app

from ..accounts.feature_storage import UserStorage

logger = logging.getLogger(__name__)

# Public cookie name used by every view that sets / reads the session token.
# Single source of truth — see module docstring.
SESSION_COOKIE_NAME: str = "pb_sid"

# Sid payload: time_ns() prefix for chronological debuggability + 32 bytes
# of secrets.token_urlsafe() entropy. The two together give ~256 bits of
# unguessability plus nanosecond-scale uniqueness for collision-free inserts.
_SID_TIME_PREFIX_SEP: str = "."
_SID_RANDOM_BYTES: int = 32


def _storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _lifetime() -> timedelta:
    hours = int(current_app.config["PB_CONFIG"]["SESSION_LIFETIME_HOURS"])
    return timedelta(hours=hours)


def _expires_at_iso(now: datetime, lifetime: timedelta) -> str:
    expires = now + lifetime
    return expires.strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_sid() -> str:
    """Return a fresh opaque session id.

    The time prefix is not load-bearing for security — the secrets suffix
    carries all the entropy — it just makes the row order in the sessions
    table match insert order when reading the DB by hand.
    """
    return f"{time.time_ns()}{_SID_TIME_PREFIX_SEP}{secrets.token_urlsafe(_SID_RANDOM_BYTES)}"


def create_session(user_id: int) -> str:
    """Create a server-side session for ``user_id`` and return the new sid.

    The caller is responsible for setting the cookie on the response; this
    function only persists the row. Expiry is computed from the app config's
    ``SESSION_LIFETIME_HOURS``.
    """
    sid = _new_sid()
    now = datetime.now(timezone.utc)
    expires_at = _expires_at_iso(now, _lifetime())
    _storage().create_session(sid=sid, user_id=int(user_id), expires_at=expires_at)
    logger.info(
        "session issued user_id=%s expires_at=%s lifetime_hours=%s",
        int(user_id),
        expires_at,
        int(_lifetime().total_seconds() // 3600),
    )
    return sid


def get_session(sid: str) -> Optional[int]:
    """Return the user_id for a valid, unexpired ``sid``; else ``None``.

    Expired rows are purged lazily by the storage layer's ``get_session``.
    Unknown / malformed / empty sids return ``None`` rather than raising so
    the caller can treat "no session" and "bad session" identically.
    """
    if not isinstance(sid, str) or not sid:
        return None
    row = _storage().get_session(sid)
    if row is None:
        return None
    user_id, _expires_at = row
    return int(user_id)


def destroy_session(sid: str) -> None:
    """Delete the session row identified by ``sid``; idempotent on missing rows."""
    if not isinstance(sid, str) or not sid:
        return
    _storage().delete_session(sid)
    logger.info("session destroyed sid_present=%s", bool(sid))


__all__ = [
    "SESSION_COOKIE_NAME",
    "create_session",
    "get_session",
    "destroy_session",
]
