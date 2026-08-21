"""v0.9.7 — /team endpoint retirement + internal reporter chokepoint.

v0.6.2 — /team endpoints
  GET  /team                    — render the team roster (any signed-in user)
  POST /team/_internal/report   — copy-editor pushes a batch of agent rows
                                  via shared-secret auth; UPSERTs into
                                  ``agent_team_status``

v0.9.7 — GET /team retired (302 → /projects)
--------------------------------------------
The team roster was useful in the v0.6 cycle (when the mavis → user
chatter passed through it) but the v0.9 surface does not surface the
roster anywhere — the only consumer is the copy-editor agent, which
writes via ``POST /team/_internal/report``. Retiring ``GET /team``
removes the per-user surface; the copy-editor write path stays
un-touched (its auth + UPSERT contract is documented in
:mod:`project_board.team.feature_team_storage` and verified by
``smoke_v062_mavis``).

The retirement is a 302 redirect to ``/projects`` rather than a
hard 404 so a stale bookmark or a chat-pasted link still lands on a
useful page; the project list is the de-facto landing for any
signed-in user (7/17 self-contained principle: no 404 dead-ends in
the human flow).

The ``POST`` chokepoint's auth + UPSERT helpers
(``apply_team_report`` / ``validate_team_entry``) stay in
:mod:`feature_team_storage` so the write contract is preserved
verbatim across the read-side retirement.

Write-side auth
---------------
``POST /team/_internal/report`` is NOT gated by ``@require_auth`` — the
writer is a machine (the copy-editor agent) and a session cookie would
be a footgun. Instead the route reads ``X-Copy-Editor-Secret`` and
compares it byte-for-byte to the ``COPY_EDITOR_SHARED_SECRET`` env var.
A missing or mismatching secret returns 401; a missing / malformed
payload returns 400; a successful write returns 200 with a count.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Blueprint, current_app, g, jsonify, redirect, request, url_for

from ..projects.feature_storage import ProjectStorage
from .feature_team_storage import (
    TEAM_STATUSES,
    apply_team_report,
    validate_team_entry,
)
from ..rbac.feature_require_auth import require_auth

logger = logging.getLogger(__name__)

bp = Blueprint("team", __name__)

# Public-safe error strings. Surfaced to the internal caller as JSON
# (the only caller is the copy-editor script).
_ERR_BAD_PAYLOAD: str = "payload must be a JSON array of agent rows"
_ERR_PAYLOAD_VALIDATION: str = "payload validation failed"
_ERR_MISSING_SECRET_ENV: str = "server is missing COPY_EDITOR_SHARED_SECRET"
_REPORTED_BY: str = "copy-editor"
_SECRET_HEADER: str = "X-Copy-Editor-Secret"
_SECRET_ENV: str = "COPY_EDITOR_SHARED_SECRET"


def _project_storage() -> ProjectStorage:
    """Return the active Flask app's ProjectStorage.

    Mirrors the helper used by the rest of the projects module so
    the team blueprint reads the same DB file ``init_schema`` wired
    up.
    """
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


@bp.get("/team")
@require_auth
def show_team():
    """v0.9.7 — retired; 302 → /projects.

    The team roster page is no longer a per-user surface (the
    copy-editor is the only consumer and it writes via
    ``POST /team/_internal/report``). The handler keeps the
    ``@require_auth`` decorator so the redirect still respects
    the session — an anonymous visitor is sent to /login, a
    signed-in visitor is sent to /projects. A stale bookmark or
    a chat-pasted link therefore lands on a useful page rather
    than a hard 404.
    """
    logger.info(
        "team view retired -> /projects user_id=%s role=%s",
        g.current_user.id, g.current_user.role,
    )
    return redirect(url_for("projects_list.show_projects"))


@bp.post("/team/_internal/report")
def submit_team_report():
    """Internal endpoint for the copy-editor agent to push status.

    Auth: request header ``X-Copy-Editor-Secret`` must equal the
    ``COPY_EDITOR_SHARED_SECRET`` env var. A missing / mismatching
    secret returns 401.

    Body: JSON array of ``{agent_name, description, status, task_count}``
    objects. A non-array body returns 400; any entry that fails
    field-level validation (missing ``agent_name``, unknown ``status``,
    negative / non-int ``task_count``) returns 400 and the entire
    batch is rejected (the UPSERT is transactional within the storage
    layer's connection).
    """
    provided = str(request.headers.get(_SECRET_HEADER, "") or "")
    expected = str(os.environ.get(_SECRET_ENV, "") or "")
    if not expected:
        logger.warning("team report rejected reason=server-missing-secret-env")
        return jsonify({"error": _ERR_MISSING_SECRET_ENV}), 401
    if not provided or provided != expected:
        logger.warning("team report rejected reason=bad-or-missing-secret")
        return jsonify({"error": "unauthorized"}), 401

    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, list):
        logger.info("team report rejected reason=non-array payload")
        return jsonify({"error": _ERR_BAD_PAYLOAD}), 400

    storage = _project_storage()
    try:
        written = apply_team_report(
            storage, report=payload, reported_by=_REPORTED_BY,
        )
    except ValueError as exc:
        logger.info(
            "team report rejected reason=validation payload=%r", payload,
        )
        return jsonify({"error": _ERR_PAYLOAD_VALIDATION, "detail": str(exc)}), 400

    logger.info("team report applied entries=%d reported_by=%s", written, _REPORTED_BY)
    return jsonify({"ok": True, "count": written}), 200


__all__ = ["bp", "TEAM_STATUSES", "validate_team_entry"]
