"""Project owner reassignment endpoint.

POST ``/projects/<int:project_id>/owner`` — change a project's owner.

v0.7.2b — T-scale gate
-----------------------
The endpoint is gated by ``@require_auth`` plus an explicit
``_is_auto_own(actor)`` check so the actor must be T0 (admin) or T1
(manager). This is the v0.7.1 T-scale equivalent of the v0.5.4
``@require_role(MANAGER)`` decorator; the accept set is the same
(T0/T1) but the gate is now expressed in the new T-scale native
helper, matching the v0.7.2a ``feature_project_members`` and
``feature_create`` endpoints. T2 (project_leader) and below are
rejected with a 403 from :func:`_check_actor_is_auto_own` before
any handler logic runs.

The new owner (target) must be T2 (project_leader, rank 2). T0/T1
(auto-own ranks) and T3 / T4 (non-leader ranks) are rejected with
400. The dropdown in ``feature_view._build_owner_context`` already
filters candidates to ``role == project_leader`` so the normal user
flow never offers a T0/T1/T3/T4 target; a hand-crafted POST that
bypasses the UI still hits the rank check here.

Server-side policy (7/22 RBAC business-lock principle)
-------------------------------------------------------
The handler enforces the following invariants:

* **system project is permanent** — a row with ``project_type='system'``
  cannot have its owner reassigned by anyone, including admin. The
  system project's owner stays the bootstrap admin forever; this is
  the same rule that already blocks the delete endpoint.
* **target must be T2** — the new owner must hold rank 2
  (``project_leader``). T0/T1 (auto-own) and T3 / T4 (non-leader)
  are rejected with 400 because the project's ownership model
  assumes the owner is the project's day-to-day lead, which is a
  project_leader by RBAC design.
* **target must exist** — a missing user id is a 404 (not a 400) so
  the route matches the rest of the project's surface.
* **idempotent** — ``new_owner_id`` equal to the current
  ``projects.owner_id`` is accepted as a 302 no-op (see below).
* **actor must be T0/T1** — enforced by :func:`_check_actor_is_auto_own`
  before any of the above.

Idempotent / self target
------------------------
A change request where ``new_owner_id`` equals the current
``projects.owner_id`` is accepted as a 302 no-op. The redirect lands
on the project view with a ``notice=Owner unchanged`` query string
so the UX matches a successful reassignment. This covers two
operational cases:

* a T0 / T1 actor that hand-crafts a POST setting target=actor when
  the actor happens to be the current owner (e.g. the v0.7.1
  migration left the system project's owner as the bootstrap admin)
  gets a clean 302 instead of a 400 from the target-rank check.
* a T0 / T1 actor that picks the current T2 owner from the dropdown
  gets the same redirect as a successful reassignment.

The original v0.5.4 anti-self guard (``actor.id == new_owner_id``)
is removed. The new target-rank check makes it unreachable: T0/T1
actor + T0/T1 target is rejected at the target-rank check (T0/T1
target rule) before any anti-self check would have run. T2 / T3 / T4
actor are blocked at the actor gate, so the only actors that could
pass the rank check for themselves are the T0/T1 ones, and they
are blocked by the target-rank check.

The storage layer (see :meth:`ProjectStorage.update_owner`) is
policy-agnostic — it only writes the column.

Audit log
---------
Every successful reassignment emits a single ``project owner change
actor_id=... actor_role=... project_id=... old_owner_id=...
new_owner_id=...`` line. The handler computes the old owner id from
the project row before the storage write so the audit line is
self-contained.
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, current_app, g, redirect, request, url_for

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_require_auth import require_auth
from .feature_storage import ProjectStorage
from .feature_storage_rbac import _is_auto_own

logger = logging.getLogger(__name__)

bp = Blueprint("project_owner", __name__)

_NEW_OWNER_FIELD: str = "new_owner_id"
_TARGET_RANK_LEADER: int = 2

# v0.7.2b — five error strings, unified in the
# ``feature_create._ERR_*`` style.
_ERR_ACTOR_NOT_AUTO_OWN: str = "only T0/T1 (admin/manager) can change project owner"
_ERR_TARGET_AUTO_OWN: str = "T0/T1 已 auto-own, 不能是 owner target"
_ERR_TARGET_T3: str = "T3 (team_leader) cannot be project owner"
_ERR_TARGET_T4: str = "T4 (user) cannot be project owner"
_ERR_SYSTEM_PERMANENT: str = "system project owner is permanent"

# Unchanged from v0.5.4 — kept as constants for symmetry.
_ERR_USER_NOT_FOUND: str = "user not found"
_ERR_NEW_OWNER_REQUIRED: str = "new_owner_id is required"
_ERR_NEW_OWNER_INVALID: str = "new_owner_id must be an integer"

_IDEMPOTENT_NOTICE: str = "Owner unchanged"


def _project_storage() -> ProjectStorage:
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


def _user_storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _check_actor_is_auto_own(actor) -> None:
    """Reject non-T0/T1 actors with 403.

    The ``@require_auth`` decorator already puts the actor on
    ``g.current_user``; this helper enforces the v0.7.2b T0/T1-only
    gate. The check is delegated to the project's
    :func:`_is_auto_own` helper so the T-scale is the single source
    of truth (admin / manager = T0 / T1, everything else is
    rejected). The 403 fires before any handler logic so a T2
    actor that hand-crafts a POST never reaches the target-rank
    check.
    """
    if not _is_auto_own(actor):
        logger.warning(
            "project owner change denied actor_id=%s actor_role=%s "
            "actor_rank=%s reason=not-auto-own",
            getattr(actor, "id", "?"),
            getattr(actor, "role", "?"),
            getattr(actor, "rank", "?"),
        )
        abort(403, _ERR_ACTOR_NOT_AUTO_OWN)


@bp.post("/projects/<int:project_id>/owner")
@require_auth
def submit_project_owner(project_id: int):
    """POST handler — reassign a project's owner.

    Form contract: a single ``new_owner_id`` field. The endpoint runs
    after ``@require_auth`` so the actor gate
    (:func:`_check_actor_is_auto_own`) is enforced here; this
    handler enforces the system-permanent, target-rank, and
    idempotent (``new_owner_id == projects.owner_id``) rules in
    order. The pre-storage checks mirror the rest of the project's
    write surface (404 for missing project / user, 400 for bad
    form, 403 for system / actor).
    """
    actor = g.current_user
    _check_actor_is_auto_own(actor)

    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "project owner change 404 actor_id=%s project_id=%s",
            actor.id, project_id,
        )
        abort(404)

    # system project is permanent — T0/T1 / everyone gets 403.
    if project.is_system:
        logger.warning(
            "project owner change denied actor_id=%s actor_role=%s "
            "project_id=%s reason=system-project",
            actor.id, actor.role, project.id,
        )
        abort(403, _ERR_SYSTEM_PERMANENT)

    raw = str(request.form.get(_NEW_OWNER_FIELD, "") or "").strip()
    if not raw:
        logger.info(
            "project owner change rejected actor_id=%s project_id=%s "
            "reason=missing-new-owner-id",
            actor.id, project_id,
        )
        abort(400, _ERR_NEW_OWNER_REQUIRED)
    try:
        new_owner_id = int(raw)
    except ValueError:
        logger.info(
            "project owner change rejected actor_id=%s project_id=%s "
            "raw=%r reason=bad-new-owner-id",
            actor.id, project_id, raw,
        )
        abort(400, _ERR_NEW_OWNER_INVALID)

    # Idempotent: target equals the current owner. The redirect is
    # the same shape as a successful reassignment so the UI treats
    # the no-op as a benign outcome (matches the v0.5.4 behaviour:
    # the row was never changed but the request returned 302).

    # The check fires before the rank / lookup checks so a T0/T1
    # owner (e.g. the system project) and a T2 owner are both
    # accepted when the target is the current owner.
    if new_owner_id == int(project.owner_id):
        target_url = url_for("project_view.show_project", project_id=project.id)
        return redirect(f"{target_url}?notice={_IDEMPOTENT_NOTICE}")

    target = _user_storage().find_by_id(new_owner_id)
    if target is None:
        logger.info(
            "project owner change 404 actor_id=%s project_id=%s "
            "new_owner_id=%s",
            actor.id, project_id, new_owner_id,
        )
        abort(404, _ERR_USER_NOT_FOUND)

    # v0.7.2b — T-scale rank check. T0/T1 (auto-own) and T3 / T4
    # (non-leader ranks) are rejected. Only T2 (project_leader, rank
    # 2) is accepted. The check is enforced server-side so a
    # hand-crafted POST that bypasses the project_view dropdown
    # still gets a clean 400 with a descriptive message.
    if _is_auto_own(target):
        logger.warning(
            "project owner change rejected actor_id=%s project_id=%s "
            "target_id=%s target_role=%s target_rank=%s reason=target-auto-own",
            actor.id, project_id, target.id, target.role, target.rank,
        )
        abort(400, _ERR_TARGET_AUTO_OWN)
    if int(target.rank) == 3:
        logger.warning(
            "project owner change rejected actor_id=%s project_id=%s "
            "target_id=%s target_role=%s target_rank=%s reason=target-team-leader",
            actor.id, project_id, target.id, target.role, target.rank,
        )
        abort(400, _ERR_TARGET_T3)
    if int(target.rank) == 4:
        logger.warning(
            "project owner change rejected actor_id=%s project_id=%s "
            "target_id=%s target_role=%s target_rank=%s reason=target-user",
            actor.id, project_id, target.id, target.role, target.rank,
        )
        abort(400, _ERR_TARGET_T4)
    # A row with rank == 2 (T2) is the only valid target. Any other
    # rank (corrupt row, future T5+, etc.) is rejected with the
    # T4-equivalent error so a defensive caller that forgot to
    # check rank is not silently bypassed.
    if int(target.rank) != _TARGET_RANK_LEADER:
        logger.warning(
            "project owner change rejected actor_id=%s project_id=%s "
            "target_id=%s target_role=%s target_rank=%s reason=target-unknown-rank",
            actor.id, project_id, target.id, target.role, target.rank,
        )
        abort(400, _ERR_TARGET_T4)

    old_owner_id = int(project.owner_id)
    changed = storage.update_owner(project_id=project_id, new_owner_id=new_owner_id)
    if not changed:
        # update_owner returns False when the row id no longer exists.
        # Surface as 404 so the operator chasing a stale URL gets the
        # same answer the project view would give.
        logger.info(
            "project owner change 404 actor_id=%s project_id=%s "
            "new_owner_id=%s reason=row-disappeared",
            actor.id, project_id, new_owner_id,
        )
        abort(404)

    logger.info(
        "project owner change actor_id=%s actor_role=%s project_id=%s "
        "old_owner_id=%s new_owner_id=%s",
        actor.id, actor.role, project.id, old_owner_id, new_owner_id,
    )
    notice = f"Owner updated to {target.username}"
    target_url = url_for("project_view.show_project", project_id=project.id)
    return redirect(f"{target_url}?notice={notice}")


__all__ = ["bp"]
