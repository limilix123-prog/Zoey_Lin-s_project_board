"""Project delete endpoint.

POST /projects/<int:project_id>/delete

The endpoint is gated by ``@require_role(MANAGER)`` so only admin
(rank 5) and manager (rank 4) may delete a project. A project owner
(project_leader or any other role) cannot delete their own project
through this endpoint; admin / manager must do it. The RBAC
business-lock principle keeps the rank check in the decorator
(server-side, not template-side) so a hand-crafted POST that skips
the UI still hits the gate.

The :func:`require_role` decorator short-circuits to a 403 for
project_leader / team_leader / plain user before any handler logic
runs; the system project guard runs **after** the decorator but
**before** the storage write so the seeded system row stays
permanent for every actor (including admin / manager). ``ON DELETE
CASCADE`` in the schema removes ``project_members`` rows when a
user project is actually deleted.
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, current_app, g, redirect, url_for

from ..rbac.feature_require_auth import require_role
from ..rbac.feature_role import MANAGER
from .feature_storage import ProjectStorage

logger = logging.getLogger(__name__)

bp = Blueprint("project_delete", __name__)

_ERR_SYSTEM_PERMANENT: str = "system projects cannot be deleted"


def _project_storage() -> ProjectStorage:
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


@bp.post("/projects/<int:project_id>/delete")
@require_role(MANAGER)
def submit_delete_project(project_id: int):
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)

    # system project guard runs first so a request that targets a
    # system row fails the same way for every actor. The @require_role
    # decorator already lets admin / manager through, so the only
    # actors that reach this branch are admin and manager — both
    # blocked, by design.
    if project.is_system:
        logger.warning(
            "project delete rejected system project_id=%s user_id=%s role=%s",
            project_id, user.id, user.role,
        )
        abort(403, _ERR_SYSTEM_PERMANENT)

    removed = storage.delete(project_id)
    if removed:
        logger.info("project deleted id=%s by user_id=%s", project_id, user.id)
    return redirect(url_for("projects_list.show_projects"))


__all__ = ["bp"]
