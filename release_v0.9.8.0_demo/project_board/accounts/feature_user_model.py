"""User data model.

Pure data container — no IO, no hashing, no storage calls.
Storage layer in feature_storage.py converts sqlite rows into User instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class User:
    """Immutable user record.

    Fields mirror the `users` table columns in feature_storage.py.
    `frozen=True` so a User cannot be mutated by callers; updates go through
    storage.update_role and produce new row reads.

    The ``rank`` field is the new v0.7.1 T-scale (0=admin/T0, 1=manager/T1,
    2=project_leader/T2, 3=team_leader/T3, 4=user/T4). ``role`` is preserved
    for backward compatibility (deprecated, kept in sync with ``rank`` by
    the storage layer's writes). The ``is_admin`` helper below uses
    ``rank`` so callers that have switched to the T-scale get the right
    answer; routes that still read ``user.role`` keep working because the
    string literals are unchanged.
    """

    id: int
    username: str
    password_hash: str
    role: str
    rank: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "password_hash": self.password_hash,
            "role": self.role,
            "rank": self.rank,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "User":
        """Build a User from a sqlite3 row (mapping access)."""
        # ``rank`` is a NOT NULL DEFAULT 4 column added in v0.7.1; rows
        # written by older code paths (or by a pre-migration dump re-loaded
        # into a fresh DB) may be missing the key. Fall back to the legacy
        # ``role`` → rank mapping so the in-memory User is always usable.
        raw_rank = row["rank"] if "rank" in row.keys() else None
        if raw_rank is None:
            rank = _legacy_role_to_rank(str(row["role"]))
        else:
            rank = int(raw_rank)
        return cls(
            id=int(row["id"]),
            username=str(row["username"]),
            password_hash=str(row["password_hash"]),
            role=str(row["role"]),
            rank=rank,
            created_at=str(row["created_at"]),
        )

    def is_admin(self) -> bool:
        return self.role == "admin" or self.rank == 0


def _legacy_role_to_rank(role: str) -> int:
    """Translate a v0.7.0 role string into the v0.7.1 T-scale rank.

    Used only by :meth:`User.from_row` when a row is read that pre-dates
    the v0.7.1 ``rank`` column. Mirrors the migration mapping in
    :mod:`project_board.accounts.feature_migrate_v071`. Unknown roles
    default to T4 (user) so the loader fails open at the lowest rank
    rather than crashing.
    """
    mapping: dict[str, int] = {
        "admin": 0,
        "manager": 1,
        "project_leader": 2,
        "team_leader": 3,
        "user": 4,
    }
    return int(mapping.get(str(role), 4))
