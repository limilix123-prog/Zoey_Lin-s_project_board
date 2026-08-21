"""Bootstrap seeders for the five-role matrix.

On every app start, the credentials in config.yaml are used to keep the
bootstrap admin / manager / project_leader / team_leader rows in sync.
Idempotent — safe to call repeatedly.

All four seeders are config-authoritative for *their* bootstrap row: the
same config-driven sync semantics apply (re-hash password, ensure role,
optional rename from a fallback username). For the manager /
project_leader / team_leader seeders there is one extra rule: an existing
user with a *higher* rank (admin for the rest) is never demoted by the
seeder — admin is the platform super admin and stays where it is.

The admin row, in turn, is promoted via the dedicated ``set_role_admin``
chokepoint (not the public ``update_role`` path, which rejects ``admin``)
so the bootstrap is the only legitimate way to create / restore the admin
role.

The seeder for manager / project_leader falls through to a fallback
username (``leader`` / ``mavis`` respectively) when the new name is
absent. If a row with the older username is found it is renamed to the
new name via :meth:`UserStorage.set_username` and the password is
re-hashed from config. This is the only path that mutates a row's
username — the role-change route never touches it.
"""

from __future__ import annotations

import logging

from ..accounts.feature_password import hash_password
from ..accounts.feature_storage import UserStorage
from .feature_role import (
    ADMIN,
    MANAGER,
    PROJECT_LEADER,
    TEAM_LEADER,
    USER,
    rank_for_role,
    is_admin,
)

logger = logging.getLogger(__name__)


def ensure_admin_exists(
    storage: UserStorage,
    admin_username: str,
    admin_password: str,
) -> int:
    """Sync the bootstrap admin from config.

    Behaviour (config is authoritative for the bootstrap admin):
      1. If a user with ``admin_username`` already exists (any role), re-hash
         ``admin_password`` into their row and ensure their role is ``admin``.
         This is the "config changed, sync" path. The role restore uses the
         dedicated ``set_role_admin`` chokepoint — the public ``update_role``
         rejects ``admin`` (RBAC matrix rule).
      2. Else, if other admins already exist with a different username, log a
         warning and do nothing — config cannot silently replace them.
      3. Else, create a new admin with ``admin_username`` and ``admin_password``.

    Returns the admin count after the call.
    """
    if not admin_username or not admin_password:
        raise ValueError("admin_username and admin_password must be non-empty")

    existing_user = storage.find_by_username(admin_username)
    if existing_user is not None:
        # Path 1 — config username already present; sync password + ensure role.
        if not is_admin(existing_user):
            storage.set_role_admin(existing_user.id)
            logger.warning(
                "admin seed promoted existing user %s (rank was %s) to admin "
                "via set_role_admin",
                admin_username, existing_user.rank,
            )
        new_hash = hash_password(admin_password)
        storage.update_password(existing_user.id, new_hash)
        logger.info("admin seed synced password for %s", admin_username)
        return storage.count_admins()

    if storage.count_admins() > 0:
        # Path 2 — admins exist but config username does not match any of them.
        existing = storage.count_admins()
        logger.warning(
            "admin seed skipped — %s admin(s) already exist but config username "
            "%s is new; use /admin/promote to grant admin manually",
            existing, admin_username,
        )
        return existing

    # Path 3 — fresh create.
    password_hash = hash_password(admin_password)
    new_id = storage.create_user(
        username=admin_username,
        password_hash=password_hash,
        rank=0,  # T0 = admin (v0.9.1 rank-based, role field deprecated)
    )
    logger.info(
        "admin seed created user id=%s username=%s rank=T0", new_id, admin_username,
    )
    return storage.count_admins()


def _ensure_bootstrap_exists(
    storage: UserStorage,
    *,
    new_username: str,
    new_password: str,
    target_role: str,
    fallback_username: str = "",
    seeder_label: str,
) -> int:
    """Shared rank-aware bootstrap logic for manager / project_leader / team_leader.

    Behaviour (config is authoritative for the bootstrap username, but the
    row's role is *not* always overwritten — an existing admin is left
    alone because admin outranks every other role):
      1. If a user with ``new_username`` already exists, reconcile their
         role against ``target_role`` per the rank-aware rules (lower →
         promote up, higher → leave alone, same → silent noop), then
         sync the password.
      2. Else, if a ``fallback_username`` row exists, rename it to
         ``new_username`` via :meth:`UserStorage.set_username`, then
         reconcile role + password (same rank-aware path).
      3. Else, if any ``target_role`` users already exist with a different
         username, log a warning and do nothing — config cannot silently
         replace them.
      4. Else, create a new user with ``new_username`` and ``new_password``.

    Returns the count of users with ``target_role`` after the call. Empty
    / missing config values short-circuit to a no-op (skip the seed),
    matching the admin seeder's "leave blank to skip" semantics.

    ``seeder_label`` is included in log lines so a tail-grep on the
    ``project_board.*`` logger output can tell the four seeders apart.
    """
    if not new_username or not new_password:
        logger.info(
            "%s seed skipped — empty username/password in config", seeder_label,
        )
        return storage.count_users_by_role(target_role)

    target_rank = rank_for_role(target_role)
    if target_rank > 4 or target_rank < 0:
        raise ValueError(f"unknown target_role: {target_role!r}")

    new_hash = hash_password(new_password)

    # Path 1 — config username already present.
    existing_user = storage.find_by_username(new_username)
    if existing_user is not None:
        current_rank = int(existing_user.rank)
        if current_rank > target_rank:
            # current_rank is HIGHER (smaller number) than target_rank
            # → existing user is at or above the target rank. We must
            # not demote (e.g. demote a T0 admin to T3 team_leader).
            # For equality (e.g. team_leader re-seed on a team_leader
            # row) the rank-write is a no-op so just re-hash the

            # password. This is the v0.9.1 rank-based replacement for
            # the old "lower promote, higher leave alone, same noop"
            # role-string logic.
            if current_rank != target_rank:
                storage.set_rank_by_id(existing_user.id, target_rank)
                logger.warning(
                    "%s seed promoted existing user %s (rank was %s) to %s (rank %s)",
                    seeder_label, new_username, current_rank, target_role, target_rank,
                )
        else:
            logger.info(
                "%s seed left higher-rank user %s as T%s (would-be rank %s)",
                seeder_label, new_username, current_rank, target_rank,
            )
        storage.update_password(existing_user.id, new_hash)
        logger.info("%s seed synced password for %s", seeder_label, new_username)
        return storage.count_users_by_role(target_role)

    # Path 2 — fallback username present; rename then reconcile.
    if fallback_username and fallback_username != new_username:
        fallback_user = storage.find_by_username(fallback_username)
        if fallback_user is not None:
            current_rank = int(fallback_user.rank)
            # Rename first; the unique constraint on `username` would
            # otherwise block the rename if a same-name row already
            # existed (Path 1 already filtered that case out above).
            storage.set_username(fallback_user.id, new_username)
            logger.info(
                "%s seed renamed fallback user %s -> %s (id=%s)",
                seeder_label, fallback_username, new_username, fallback_user.id,
            )
            if current_rank > target_rank:
                storage.set_rank_by_id(fallback_user.id, target_rank)
                logger.warning(
                    "%s seed promoted renamed user %s (rank was %s) to %s (rank %s)",
                    seeder_label, new_username, current_rank, target_role, target_rank,
                )
            elif current_rank < target_rank:
                logger.info(
                    "%s seed left higher-rank renamed user %s as T%s "
                    "(would-be rank %s)",
                    seeder_label, new_username, current_rank, target_rank,
                )
            storage.update_password(fallback_user.id, new_hash)
            logger.info(
                "%s seed synced password for renamed %s", seeder_label, new_username,
            )
            return storage.count_users_by_role(target_role)

    if storage.count_users_by_role(target_role) > 0:
        # Path 3 — target_role users exist but config username (and any
        # fallback row) does not match any of them.
        existing = storage.count_users_by_role(target_role)
        logger.warning(
            "%s seed skipped — %s %s user(s) already exist but config "
            "username %s is new; promote manually if needed",
            existing, seeder_label, target_role, new_username,
        )
        return existing

    # Path 4 — fresh create.
    new_id = storage.create_user(
        username=new_username,
        password_hash=new_hash,
        rank=target_rank,
    )
    logger.info(
        "%s seed created user id=%s username=%s rank=T%s (role=%s)",
        seeder_label, new_id, new_username, target_rank, target_role,
    )
    return storage.count_users_by_role(target_role)


def ensure_manager_exists(
    storage: UserStorage,
    manager_username: str,
    manager_password: str,
) -> int:
    """Sync the bootstrap manager from config.

    Same rank-aware semantics as the other bootstrap seeders, plus a
    migration: when no row with the new ``manager_username`` exists,
    fall through to the ``leader`` username and rename it via
    :meth:`UserStorage.set_username`.
    """
    return _ensure_bootstrap_exists(
        storage,
        new_username=manager_username,
        new_password=manager_password,
        target_role=MANAGER,
        fallback_username="leader",
        seeder_label="manager",
    )


def ensure_project_leader_exists(
    storage: UserStorage,
    project_leader_username: str,
    project_leader_password: str,
) -> int:
    """Sync the bootstrap project_leader from config.

    Same rank-aware semantics as the other bootstrap seeders, plus a
    migration: when no row with the new ``project_leader_username``
    exists, fall through to the ``mavis`` username and rename it via
    :meth:`UserStorage.set_username`.
    """
    return _ensure_bootstrap_exists(
        storage,
        new_username=project_leader_username,
        new_password=project_leader_password,
        target_role=PROJECT_LEADER,
        fallback_username="mavis",
        seeder_label="project_leader",
    )


def ensure_team_leader_exists(
    storage: UserStorage,
    team_leader_username: str,
    team_leader_password: str,
) -> int:
    """Sync the bootstrap team_leader from config.

    No fallback row — the role did not exist before, so there is no
    row to rename. Same rank-aware semantics as the other bootstrap
    seeders.
    """
    return _ensure_bootstrap_exists(
        storage,
        new_username=team_leader_username,
        new_password=team_leader_password,
        target_role=TEAM_LEADER,
        fallback_username="",
        seeder_label="team_leader",
    )


def user_role_or_default(storage: UserStorage, username: str) -> str:
    """Return the role for ``username``; defaults to 'user' if not found.

    v0.9.2 sub-task 3 — read path: rank is the source of truth; we
    reverse-map the rank to the legacy role string via
    :func:`rbac.feature_role.role_for_rank` so callers that still
    expect a string get the same value they used to.
    """
    from .feature_role import role_for_rank
    row = storage.find_by_username(username)
    return role_for_rank(int(row.rank)) if row is not None else USER


__all__ = [
    "ensure_admin_exists",
    "ensure_manager_exists",
    "ensure_project_leader_exists",
    "ensure_team_leader_exists",
    "user_role_or_default",
]
