"""Rank-based RBAC primitives (v0.9.1 rank migration, 8/13 mavis).

History:
- v0.7.0 introduced string roles (admin / manager / project_leader / team_leader / user)
  keyed by ``User.role``.
- v0.7.1 added ``User.rank`` (0..4) as the canonical T-scale and kept ``role``
  for backward compatibility. The two columns were kept in sync by the
  storage layer's writes.
- v0.9.1 (8/13) — user拍板 "以前鉴权鉴的是 role, 现在不是应该鉴 rank 吗".
  This module is the rank-based replacement. ``User.role`` is now a
  deprecated read-only field; all authority decisions go through
  ``User.rank`` (0=admin, 1=manager, 2=project_leader, 3=team_leader,
  4=user). Storage still writes ``role`` for legacy readers but never
  reads it for any decision.

Rank semantics
--------------
- 0 (admin) is the highest rank — opens every gate.
- 4 (user) is the lowest rank — opens only user-gated routes (none today).
- ``_role_at_least(user, required)`` answers "does ``user`` meet or exceed
  the authority of ``required``". Implementation:
  ``user.rank <= _RANK_FOR_ROLE[required]`` because lower rank == higher
  authority. Read it as "the user's rank is at most the required rank".

Two layers
----------
- ``_role_at_least`` — pure function on ``User`` / rank ints, no IO.
  Used by routes and tests; the single source of truth for any
  authority decision.
- ``is_admin`` / ``is_manager`` / ``is_project_leader`` / ``is_team_leader``
  — strict-rank equality checks (each matches exactly one T-level).
  Use ``_role_at_least`` for "at least this rank" semantics.
"""

from __future__ import annotations

from typing import Final, Iterable, Optional

from ..accounts.feature_user_model import User

USER: Final[str] = "user"
TEAM_LEADER: Final[str] = "team_leader"
PROJECT_LEADER: Final[str] = "project_leader"
MANAGER: Final[str] = "manager"
ADMIN: Final[str] = "admin"

# Set of every role this milestone recognises. The string constants
# remain in use as the form's ``new_rank`` option labels and as keys in
# the rank map below; they no longer drive any authority decision.
_KNOWN_ROLES: Final[frozenset[str]] = frozenset(
    {USER, TEAM_LEADER, PROJECT_LEADER, MANAGER, ADMIN}
)

# Rank per role — LOWER wins (0=admin/T0 .. 4=user/T4). Mirrors the
# 7/13 user拍板 "T 级别 via rank: 0=admin, 1=manager, 2=project_leader,
# 3=team_leader, 4=user".
_RANK_FOR_ROLE: Final[dict[str, int]] = {
    ADMIN: 0,
    MANAGER: 1,
    PROJECT_LEADER: 2,
    TEAM_LEADER: 3,
    USER: 4,
}


def is_known_role(role: str) -> bool:
    return role in _KNOWN_ROLES


def role_for_rank(rank: int) -> str:
    """Reverse direction — given a rank int, return the canonical role string.

    Used by the storage layer's writer to keep ``User.role`` in sync
    with ``User.rank`` for legacy readers; not used for any authority
    decision. Unknown ranks default to ``USER`` (rank 4 = lowest).
    """
    for role, r in _RANK_FOR_ROLE.items():
        if r == int(rank):
            return role
    return USER


def rank_for_role(role: str) -> int:
    """Return the rank int for a role string, or 4 (``USER``) for unknowns.

    Used by storage writers. Authority decisions should go through
    ``_role_at_least`` directly.
    """
    return _RANK_FOR_ROLE.get(str(role), 4)


def _role_at_least(user: Optional[User], required: str) -> bool:
    """True iff ``user`` is non-None and meets the authority of ``required``.

    "Meets the authority" means ``user.rank`` is at most the rank of
    ``required`` (since lower rank == higher authority). admin (rank 0)
    therefore satisfies every required; user (rank 4) satisfies only
    ``USER``. ``required`` must be a known role string.
    """
    if user is None:
        return False
    if not is_known_role(required):
        return False
    user_rank = int(user.rank)
    required_rank = _RANK_FOR_ROLE[required]
    return user_rank <= required_rank


def is_admin(user: Optional[User]) -> bool:
    """True iff ``user`` is a non-None user with admin rank (T0)."""
    return user is not None and int(user.rank) == _RANK_FOR_ROLE[ADMIN]


def is_manager(user: Optional[User]) -> bool:
    """True iff ``user`` is exactly T1 (manager specifically).

    Strict — does not match admin (T0). For "admin OR manager" use
    ``_role_at_least(user, MANAGER)``.
    """
    return user is not None and int(user.rank) == _RANK_FOR_ROLE[MANAGER]


def is_project_leader(user: Optional[User]) -> bool:
    """True iff ``user`` is exactly T2 (project_leader specifically).

    Strict — does not match admin (T0) or manager (T1). For
    "project_leader or above" use ``_role_at_least(user, PROJECT_LEADER)``.
    """
    return user is not None and int(user.rank) == _RANK_FOR_ROLE[PROJECT_LEADER]


def is_team_leader(user: Optional[User]) -> bool:
    """True iff ``user`` is exactly T3 (team_leader specifically).

    Strict — does not match admin / manager / project_leader. For
    "team_leader or above" use ``_role_at_least(user, TEAM_LEADER)``.
    """
    return user is not None and int(user.rank) == _RANK_FOR_ROLE[TEAM_LEADER]


__all__ = [
    "USER",
    "TEAM_LEADER",
    "PROJECT_LEADER",
    "MANAGER",
    "ADMIN",
    "is_admin",
    "is_manager",
    "is_project_leader",
    "is_team_leader",
    "is_known_role",
    "rank_for_role",
    "role_for_rank",
    "_role_at_least",
]
