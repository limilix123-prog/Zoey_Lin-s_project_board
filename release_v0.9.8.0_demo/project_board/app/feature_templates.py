"""Jinja2 template loader and base layout for the app.

The app factory calls :func:`init_templates` to point Jinja at the
``app/templates/`` directory and to register a few globals (current year,
site name, current user / auth state) used by ``base.html``.

The loader is a ``ChoiceLoader`` covering the shared layout dir + every
module's own ``templates/`` subdir (auth/ projects/).
A module that ships templates just needs a ``templates/`` folder next to
its source — it gets picked up automatically. The ``profile`` module is
not in this list; its template is the consolidated ``me.html`` from
:mod:`projects.feature_me`.

The auth-state globals are **functions** (lazy lookups), not values, so
they read ``flask.g.current_user`` at template-render time, inside the
request context. Registering a snapshot value at startup would capture
``None`` because ``g`` is request-scoped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from flask import Flask, g
from jinja2 import ChoiceLoader, Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_SUBDIR = "templates"

# Module names whose ``templates/`` subdir gets auto-registered.
# ``profile`` / ``kanban`` are intentionally absent (profile shares
# the consolidated me.html; kanban renders via the seeded system
# project). ``team`` was removed in v0.9.7 (GET /team retired 302).
# ``home`` + ``rbac`` removed in v0.9.7p1 cleanup.
_MODULES_WITH_TEMPLATES: tuple[str, ...] = (
    "auth",
    "projects",
)


def templates_dir(app_root: Path) -> Path:
    """Return the absolute path to the templates directory."""
    return (app_root / _TEMPLATES_SUBDIR).resolve()


def init_templates(app: Flask, app_root: Path) -> None:
    """Wire Jinja to ``app_root/templates/`` + every module's templates/.

    Loader order (first match wins):
      1. ``app/templates/`` — the shared base.html and other cross-module views
      2. Each module's ``<project_root>/<module>/templates/`` — owns its own views
      3. Any pre-existing loader (Flask default) so blueprints keep working.
    """
    project_root = app_root.parent  # project_root/app → project_root/
    primary = FileSystemLoader(str(templates_dir(app_root)))
    module_loaders: list[FileSystemLoader] = []
    for mod_name in _MODULES_WITH_TEMPLATES:
        mod_tpl = project_root / mod_name / _TEMPLATES_SUBDIR
        if mod_tpl.is_dir():
            module_loaders.append(FileSystemLoader(str(mod_tpl.resolve())))

    env: Environment = app.jinja_env
    chain: list[Any] = [primary, *module_loaders]
    if env.loader is not None:
        chain.append(env.loader)
    env.loader = ChoiceLoader(chain)
    env.globals.setdefault("site_name", "project_board")
    env.globals.setdefault("current_year", _current_year)
    env.globals.setdefault("current_user_is_authenticated", _is_authenticated)
    env.globals.setdefault("current_username", _current_username)
    # v0.9.5 P0-3 — rank-to-human label helper. The same
    # format_rank_label function is callable from any template
    # (e.g. {{ format_rank_label(u.rank) }}) so /me, /users, and
    # /projects/<id> all render the same string for the same rank.
    env.globals.setdefault("format_rank_label", _format_rank_label)
    # v0.9.5.2 P1-15 — human-readable time filter. Convert the
    # nanosecond-precision ISO string in users.created_at / project
    # rows into a short "YYYY-MM-DD HH:MM" form. Registered as a
    # Jinja *filter* per the 7/17 UI discipline (call site is
    # `{{ ts | format_time }}`).
    env.filters.setdefault("format_time", _format_time)
    logger.info(
        "templates initialised dir=%s module_loaders=%s",
        templates_dir(app_root),
        [str(ml.searchpath[0]) for ml in module_loaders],
    )


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def _current_user():
    """Return the request-scoped user (set by ``@require_auth``), or None.

    Imported lazily via ``g`` lookup; safe to call outside a request
    context (returns None) so a misconfigured template path does not
    raise at import time.
    """
    try:
        return getattr(g, "current_user", None)
    except RuntimeError:
        # Outside Flask request context — e.g. the ``__main__`` smoke path.
        return None


def _is_authenticated() -> bool:
    """True iff a ``require_auth``-decorated view has set ``g.current_user``."""
    return _current_user() is not None


def _current_username() -> str:
    """The signed-in user's username, or empty string for anonymous visitors."""
    user = _current_user()
    if user is None:
        return ""
    raw = getattr(user, "username", "")
    return str(raw) if raw is not None else ""


def _format_rank_label(rank: int) -> str:
    """Jinja-global wrapper around :func:`projects.feature_storage_rbac.format_rank_label`.

    v0.9.5 P0-3 — single source of truth for the user-facing
    T-scale label. Templates call ``{{ format_rank_label(u.rank) }}``
    so /me, /users, and /projects/<id> all render the same string
    for the same rank. The wrapper is a thin pass-through; the
    canonical implementation lives in ``feature_storage_rbac`` so
    tests + Python callers reach the same function without an
    import cycle through the templates module.
    """
    from ..projects.feature_storage_rbac import format_rank_label
    return format_rank_label(rank)


def _format_time(iso_str: object) -> str:
    """Jinja filter — render a nanosecond ISO timestamp as ``YYYY-MM-DD HH:MM``.

    v0.9.5.2 P1-15 — the project's SQLite rows store ``created_at`` /
    ``updated_at`` as ``datetime('now')`` strings. For some
    timestamp sources these include sub-second nanoseconds and a
    trailing ``Z`` (e.g. ``"2026-08-14T06:41:30.699687600Z"``) which
    a Chinese first-time visitor cannot parse at a glance. The
    filter returns a short, human-readable form and falls back to
    the raw string when the value is not a parseable ISO timestamp
    so a malformed DB row does not break the page render.

    Implementation notes (8/4 守门 — implementation details, not
    user-visible behaviour):
    - Python 3.12 ``datetime.fromisoformat`` does not accept the
      ``Z`` suffix; strip it before parsing and treat the value
      as UTC.
    - ``errors="replace"`` is not needed here because we never
      re-encode the value; we just slice the formatted output.
    """
    if iso_str is None:
        return ""
    raw = str(iso_str).strip()
    if not raw:
        return ""
    # Normalise the trailing "Z" (UTC) so fromisoformat accepts it.
    normalised = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(normalised)
    except (TypeError, ValueError):
        return raw
    return parsed.strftime("%Y-%m-%d %H:%M")


__all__ = [
    "init_templates",
    "templates_dir",
    "_MODULES_WITH_TEMPLATES",
    "_is_authenticated",
    "_current_username",
    "_format_rank_label",
    "_format_time",
]
