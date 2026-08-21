"""Rank-change endpoint (v0.9.1 — 8/13 mavis).

POST ``/users/<int:user_id>/rank`` — change another user's T-scale rank.

The endpoint is the *only* runtime path that may change a user's rank
(apart from the config-seed bootstrap, which creates the initial admin
/ manager / project_leader / team_leader rows). All five-rank RBAC
decisions live in the server-side ``_can_change_rank`` helper below —
the templates do not implement policy, they only render the form
options the helper whitelists.

RBAC matrix (``_can_change_rank``)
----------------------------------
+-----------------+--------------------------------------+----------------------+
| Actor           | May set target to                    | Forbidden            |
+=================+======================================+======================+
| admin (T0)      | T1, T2, T3, T4                       | T0, self             |
| manager (T1)    | T1, T2, T3, T4                       | T0, self             |
| project_leader  | T3, T4                               | T0, T1, T2, self     |
| (T2)            |                                      |                      |
| team_leader     | T4                                   | T0, T1, T2, T3, self |
| (T3)            |                                      |                      |
| user (T4)       | (nothing)                            | (always)             |
+-----------------+--------------------------------------+----------------------+

Hard rules enforced server-side (independent of the actor's rank):
  * **T0 permanent** — the admin rank (T0) cannot be assigned via this
    endpoint. ``set_rank_by_id`` is a direct write, but the route
    rejects T0 in ``_can_change_rank``. The only path that may grant
    T0 is the bootstrap seed (``ensure_admin_exists``).
  * **anti-self** — an actor cannot change their own rank; the route
    returns 400 ``cannot change own rank`` to surface the policy in the
    response and in the log.
  * **admin target permanent** — if the target is already T0, the
    route returns 400 ``admin rank is permanent`` even when the actor
    is admin / manager (this is the rule "no one, not even the admin,
    can demote an admin via this endpoint").

Audit log
---------
Every successful rank change emits a single ``logger.info`` line
including actor id + rank, target id, old rank, and new rank so the
audit trail is grep-able in the captured log output.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, abort, current_app, g, redirect, request, url_for

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_role import (
    PROJECT_LEADER,
    TEAM_LEADER,
    USER,
    is_admin,
    role_for_rank,
)
from ..rbac.feature_require_auth import require_role as require_rank

logger = logging.getLogger(__name__)

bp = Blueprint("user_role", __name__)

# Ranks the form may submit. T0 (admin) is intentionally absent — see
# the "T0 permanent" rule in the module docstring. The keys are the
# rank ints; the values are the labels shown in the form's <select>.
_ASSIGNABLE_RANKS: tuple[int, ...] = (1, 2, 3, 4)

# Map rank → form option label. Keeps the wire format (rank int) and
# the user-facing label (T-level + role name) in one place.
_RANK_LABEL: dict[int, str] = {
    0: "T0 (admin)",
    1: "T1 (manager)",
    2: "T2 (project_leader)",
    3: "T3 (team_leader)",
    4: "T4 (user)",
}

# Field name on the form (kept short to match the project convention).
_NEW_RANK_FIELD: str = "new_rank"


def _user_storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _can_change_rank(actor, target, new_rank: int) -> bool:
    """Return True iff ``actor`` is allowed to set ``target`` to ``new_rank``.

    Encodes the RBAC matrix. ``actor`` and ``target`` are ``User``
    dataclass instances; ``new_rank`` is one of the int values in
    ``_ASSIGNABLE_RANKS``. The helper also serves as the single source
    of truth for the form's selectable options — templates derive
    their ``<select>`` entries from the same tuple the helper accepts.

    Three short-circuit checks run first, before any actor-rank logic,
    so the matrix has a single clear "no" path:

      1. Anti-self — an actor cannot change their own rank.
      2. Admin target — a target already at T0 cannot be demoted via
         this endpoint; the row is permanent.
      3. Unknown new rank — reject (defensive; should not happen
         because the form only renders the whitelisted set).
    """
    if actor is None or target is None:
        return False
    if actor.id == target.id:
        return False
    if is_admin(target):
        return False
    if new_rank not in _ASSIGNABLE_RANKS:
        return False
    actor_rank = int(actor.rank)
    # admin (T0) and manager (T1) can set any of T1..T4.
    if actor_rank <= 1:
        return True
    if actor_rank == 2:  # project_leader
        return new_rank in (3, 4)
    if actor_rank == 3:  # team_leader
        return new_rank == 4
    return False


def _available_new_ranks(actor) -> tuple[int, ...]:
    """Rank options the ``actor`` may pick in the form.

    The whitelist mirrors ``_can_change_rank``: admin / manager see the
    full ``(1, 2, 3, 4)`` set; project_leader sees ``(3, 4)``;
    team_leader sees ``(4,)``; everyone else gets an empty tuple (no
    form rendered). Used by the templates to drive the ``<select>``
    element so the UI never offers a choice the server will reject.
    """
    if actor is None:
        return ()
    actor_rank = int(actor.rank)
    if actor_rank <= 1:
        return _ASSIGNABLE_RANKS
    if actor_rank == 2:
        return (3, 4)
    if actor_rank == 3:
        return (4,)
    return ()


@bp.post("/users/<int:user_id>/role")
@require_rank(TEAM_LEADER)
def submit_user_rank(user_id: int):
    """POST handler — change a user's rank per the RBAC matrix."""
    actor = g.current_user
    storage = _user_storage()
    target = storage.find_by_id(user_id)
    if target is None:
        logger.info(
            "rank change 404 actor_id=%s actor_rank=%s target_id=%s",
            actor.id, actor.rank, user_id,
        )
        abort(404)

    new_rank_raw = request.form.get(_NEW_RANK_FIELD, "")
    if new_rank_raw == "":
        # Backward compat (v0.7.x) — legacy form used ``new_role`` with
        # a role string. Map it to a rank int so the rank-based matrix
        # can decide. The 5-role map (admin/manager/project_leader/
        # team_leader/user) is reused; ``ADMIN`` is rejected per the
        # "T0 permanent" rule.
        legacy = str(request.form.get("new_role", "") or "").strip()
        if legacy in (PROJECT_LEADER, TEAM_LEADER, USER):
            from ..rbac.feature_role import rank_for_role
            new_rank = int(rank_for_role(legacy))
        else:
            logger.warning(
                "rank change denied actor_id=%s actor_rank=%s target_id=%s "
                "new_role=%s reason=missing-new-rank",
                actor.id, actor.rank, target.id, legacy,
            )
            abort(400, "missing new_rank (or new_role in {project_leader,team_leader,user})")
    else:
        try:
            new_rank = int(str(new_rank_raw).strip())
        except (TypeError, ValueError):
            logger.warning(
                "rank change denied non-int actor_id=%s actor_rank=%s target_id=%s "
                "new_rank=%s reason=invalid-format",
                actor.id, actor.rank, target.id, new_rank_raw,
            )
            abort(400, "new_rank must be an integer 1..4")

    if not _can_change_rank(actor, target, new_rank):
        reason = _reject_reason(actor, target, new_rank)
        logger.warning(
            "rank change denied actor_id=%s actor_rank=%s target_id=%s "
            "target_rank=%s new_rank=%s reason=%s",
            actor.id, actor.rank, target.id, target.rank, new_rank, reason,
        )
        if reason in ("self", "admin-target", "unknown-rank", "invalid-format", "missing-new-rank"):
            abort(400, reason)
        abort(403, reason)

    old_rank = int(target.rank)
    try:
        storage.set_rank_by_id(target.id, new_rank)
    except ValueError as exc:
        # set_rank_by_id validates 0..4; surface as 400.
        logger.error(
            "rank change rejected by storage actor_id=%s target_id=%s "
            "new_rank=%s err=%s",
            actor.id, target.id, new_rank, exc,
        )
        abort(400, str(exc))

    logger.info(
        "user rank change actor_id=%s actor_rank=%s target_user_id=%s "
        "old_rank=%s new_rank=%s",
        actor.id, actor.rank, target.id, old_rank, new_rank,
    )
    # Flash-style message is the URL query string; the user_view template
    # reads ``notice`` from the URL the same way ``/me`` does.
    label = _RANK_LABEL.get(new_rank, f"T{new_rank}")
    notice = f"Rank updated to {label}"
    target_view = url_for("user_view.show_user", user_id=int(target.id))
    return redirect(f"{target_view}?notice={notice}")


def _reject_reason(actor, target, new_rank: int) -> str:
    """Return the most specific policy reason for a denied change.

    The order of checks matches ``_can_change_rank`` so a single
    short-circuit picks one reason at a time. The string is both
    embedded in the abort message and logged for grep-ability.
    """
    if actor is None or target is None:
        return "unknown"
    if actor.id == target.id:
        return "self"
    if is_admin(target):
        return "admin-target"
    if new_rank not in _ASSIGNABLE_RANKS:
        return "unknown-rank"
    if int(actor.rank) <= 1:
        return "matrix-deny"  # unreachable; defensive
    if int(actor.rank) == 2 and new_rank not in (3, 4):
        return "matrix-deny"
    if int(actor.rank) == 3 and new_rank != 4:
        return "matrix-deny"
    return "forbidden"


__all__ = ["bp", "_can_change_rank", "_available_new_ranks"]
