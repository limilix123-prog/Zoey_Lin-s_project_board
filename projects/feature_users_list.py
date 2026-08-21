"""User directory endpoint.

GET ``/users`` — every authenticated user sees every account. Read
access is open to all signed-in users; only the "Change rank" form is
hidden for actors that cannot change any rank (plain ``user``) and for
rows the actor cannot target (self / admin target).

The page is the launchpad for the "view another user" flow. Each row
links to ``/users/<id>`` (the per-user detail page in
:mod:`project_board.projects.feature_user_view`) so a viewer can drill
into any account without going through the DB.

RBAC
----
The :func:`project_board.rbac.feature_require_auth.require_auth` gate
rejects only anonymous requests; every signed-in user (admin, manager,
project_leader, team_leader, plain user) reaches the page. The
"Change rank" form is gated *inside* the template by
``can_change_rank`` and ``available_new_ranks`` so plain ``user``
actors see a ``(read-only)`` placeholder where the form would render.

The ``POST /users/<id>/rank`` write path stays rank-gated at
``TEAM_LEADER`` (see :mod:`project_board.projects.feature_user_role`),
so a plain user reaching ``/users`` still cannot promote / demote
anyone.

Context shape
-------------
The template gets:

* ``users`` — list of ``user_row`` dicts (one per account) carrying the
  ``User`` plus ``owned_count`` / ``member_count`` / ``created_by``
  fields precomputed server-side. ``rank`` is the canonical T-scale
  (0=admin/T0 .. 4=user/T4); ``role`` is the deprecated legacy string,
  kept around only for the "Created by" label which mirrors the
  bootstrap vs. self-service distinction.
* ``actor_rank`` — the viewer's T-scale rank, so the "Change rank"
  form on each row picks the right ``<select>`` options.
* ``self_user_id`` — viewer id so the template can highlight the
  current user's own row and skip the "Change rank" form on that row.
* ``can_change_rank`` — bool; True iff the actor has at least one rank
  they could assign to some user (admin / manager / project_leader /
  team_leader all True, plain user False). Drives the actor-level
  ``{% if can_change_rank %}`` block in the template — the form is
  hidden entirely when the actor cannot change any rank.
* ``available_new_ranks`` — whitelist of rank ints the actor may
  assign; reused from :mod:`project_board.projects.feature_user_role`
  so the template's ``<select>`` never offers a value the server
  will reject.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, g, render_template

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_role import ADMIN, MANAGER, PROJECT_LEADER, TEAM_LEADER
from ..rbac.feature_require_auth import require_auth
from .feature_storage import ProjectStorage
from .feature_user_role import _available_new_ranks

logger = logging.getLogger(__name__)

bp = Blueprint("users_list", __name__)


def _user_storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _project_storage() -> ProjectStorage:
    cfg = current_app.config.get("PB_CONFIG")
    if cfg is None or "DB_PATH" not in cfg:
        raise RuntimeError("PB_CONFIG / DB_PATH not configured on Flask app")
    return ProjectStorage(cfg["DB_PATH"])


def _created_by_label(rank: int) -> str:
    """Best-effort label for the "created by" column.

    The users table has no ``created_by`` column. The bootstrap seeders
    create the admin / manager / project_leader / team_leader accounts
    (T0..T3); everyone else (T4) is a self-service registration. We
    surface that distinction with ``"seed"`` / ``"self"`` so the
    operator can tell bootstrap accounts from organic ones without
    joining on an external audit log that does not exist yet.

    v0.9.2 sub-task 3 — switched from role string to rank int so the
    label honours the v0.9.1 rank-based RBAC migration (the
    ``role`` column is deprecated).
    """
    if int(rank) in (0, 1, 2, 3):
        return "seed"
    return "self"


@bp.get("/users")
@require_auth
def show_users():
    user = g.current_user
    users = _user_storage().list_all_users()
    project_storage = _project_storage()

    # v0.9.2 sub-task 3 — N+1 → 2 queries. The previous shape
    # called ``list_owned_by`` + ``list_member_of`` once per user
    # (16 round-trips for an 8-user directory); the batch helper
    # returns the same two counts for every user in exactly 2
    # round-trips. Caller-side: the existing per-row dict shape

    # (``owned_count`` / ``member_count``) is preserved so the
    # template's column ordering is unchanged.
    counts_by_user: dict[int, dict[str, int]] = (
        project_storage.list_owned_and_member_counts(
            [int(u.id) for u in users],
        )
    )

    rows: list[dict[str, Any]] = []
    for u in users:
        counts = counts_by_user.get(
            int(u.id), {"owned": 0, "member": 0},
        )
        rows.append(
            {
                "id": int(u.id),
                "username": u.username,
                "rank": int(u.rank),
                # role kept as legacy read-only for any external reader;
                # not used by any rank-based decision in this module.
                "role": u.role,
                "created_at": u.created_at,
                "owned_count": int(counts["owned"]),
                "member_count": int(counts["member"]),
                "created_by": _created_by_label(int(u.rank)),
            }
        )

    # actor-level flag for the template. Plain ``user`` (T4) actors
    # have an empty ``available_new_ranks`` so the form is hidden and
    # a ``(read-only)`` placeholder is rendered. The four higher ranks
    # always have at least one rank they can assign, so the flag
    # mirrors ``_available_new_ranks``'s emptiness for the actor.
    available = list(_available_new_ranks(user))
    can_change_rank = bool(available)

    logger.info(
        "users list served user_id=%s rank=%s count=%s can_change_rank=%s",
        user.id, int(user.rank), len(rows), can_change_rank,
    )
    # Context intentionally does NOT shadow the rank-check globals
    # ``current_user_is_admin`` / ``current_user_is_project_leader`` —
    # those are functions registered on env.globals and the base.html
    # parent template calls them with parens, so we keep them as-is
    # and let the child template use the globals too.

    # Only ``self_user_id``, ``actor_rank``, ``can_change_rank`` and
    # ``available_new_ranks`` are route-specific.
    ctx: dict[str, Any] = {
        "users": rows,
        "self_user_id": int(user.id),
        "actor_rank": int(user.rank),
        "can_change_rank": can_change_rank,
        "available_new_ranks": available,
    }
    return render_template("projects/users_list.html", **ctx)


__all__ = ["bp"]
