"""v0.9.7p1 — :class:`ProjectStorage` system-project bootstrap split-out.

The two project-bootstrap helpers — :meth:`_seed_baseline_roles_for_project`
and :meth:`create_system_project_if_missing` — live here rather than in
:mod:`project_board.projects.feature_storage` so the latter stays under
the 1000-line cleancode cap. Both methods are installed onto
:class:`ProjectStorage` at import time via
:func:`install_bootstrap_methods` below so the public call sites
(``storage._seed_baseline_roles_for_project(...)`` from
:meth:`ProjectStorage.create`, and
``storage.create_system_project_if_missing(...)`` from
:mod:`project_board.app.feature_app_factory`) are unchanged.

Why a dedicated module
----------------------
v0.9.7p1 (挂账 3) — the 1405-line :mod:`feature_storage` was split
into 3 surface modules (rbac / features / nodes / roles / ddl_v092)
plus this bootstrap module + the migration module. The bootstrap
helpers are the only place in the storage layer that owns the
"seed baseline roles for a new project" chokepoint + the
"ensure the system project exists" chokepoint; isolating them
here makes the runtime CRUD chokepoint (:mod:`feature_storage`)
trivially auditable and keeps the historical-shape data
(:mod:`feature_storage_migrations`) separate from the runtime
seed.

The two methods form a chokepoint pair
--------------------------------------
* :meth:`_seed_baseline_roles_for_project` is the per-project
  seed (called from :meth:`ProjectStorage.create` and
  :meth:`ProjectStorage.create_system_project_if_missing`).
  Idempotent: every INSERT is ``OR IGNORE`` against the
  ``(project_id, name)`` unique key + the ``(custom_role_id,
  node_id)`` composite PK.
* :meth:`create_system_project_if_missing` is the system-project
  bootstrap (idempotent; called once at app start). The
  lookup-then-insert pattern keeps the seed idempotent without
  a separate migration check; on a hit the method still calls
  :meth:`_seed_baseline_roles_for_project` so an older
  pre-v0.9.2 install that created the system project but did
  not seed the baseline roles gets the missing rows on the
  next start.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _do_seed_baseline_roles_for_project(
    self, conn, project_id: int,
) -> None:
    """Seed the 3 baseline roles + auto-grants for one project.

    v0.9.2 sub-task 7 -- per-project seed (called from
    :meth:`create`) and system-project bootstrap (idempotent).
    Single-tier project_custom_roles is the source of truth
    for roles. Called from
    :meth:`ProjectStorage.create` (per-project seed on creation)
    and :meth:`ProjectStorage.create_system_project_if_missing`
    (idempotent system-project bootstrap). The
    seed is idempotent because every INSERT is
    ``OR IGNORE`` against the
    ``(project_id, name)`` unique key + the
    ``(custom_role_id, node_id)`` composite PK.

    The baseline grants are:

    * ``project_leader`` — ``can_write=1`` on every
      node (manage = full write)
    * ``team_leader`` — ``can_write=1`` on every
      node (modify = write)
    * ``user`` — ``can_write=0`` on every node
      (read = no write)

    New nodes added after the seed are NOT
    auto-granted — the project_leader sets
    per-(role, node) grants manually on the
    per-role detail page.
    """
    baseline = (
        ("project_leader", 1),
        ("team_leader", 1),
        ("user", 0),
    )
    for r, can_write in baseline:
        conn.execute(
            "INSERT OR IGNORE INTO project_custom_roles "
            "(project_id, name, description, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (int(project_id), r, f"项目预置 {r} 角色"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO "
            "project_custom_role_permissions "
            "(custom_role_id, node_id, can_write, granted_at) "
            "SELECT cr.id, n.id, ?, datetime('now') "
            "FROM project_custom_roles cr "
            "JOIN project_nodes n ON n.project_id = cr.project_id "
            "WHERE cr.project_id = ? AND cr.name = ?",
            (int(can_write), int(project_id), r),
        )


def _do_create_system_project_if_missing(
    self, name: str, owner_id: int,
) -> int:
    """Idempotent bootstrap: create a system project if ``name`` is unused.

    Looks up a project by ``name`` first and returns its id if
    found, otherwise inserts a new row with ``project_type='system'``
    and the given ``owner_id``. Returns the existing or newly-created
    project id. Safe to call on every app start; the lookup-then-insert
    pattern keeps the seed idempotent without a separate migration
    check.

    v0.9.2 sub-task 7 -- a newly-created system
    project also gets the 3 baseline roles seeded
    (with the default per-node grants auto-applied)
    so a fresh install's system project is usable
    for the kanban / role-management UI without a
    separate migration step.
    """
    # Local import keeps the cycle soft: this module is imported
    # by feature_storage at module-body level, so a module-level
    # import of _SYSTEM_SEED_DESCRIPTION would resolve before
    # the constant exists. A function-body import resolves
    # lazily on the first call.
    from .feature_storage import (
        _SYSTEM_SEED_DESCRIPTION,
        _PROJECT_TYPE_SYSTEM,
        _now_iso,
    )

    now = _now_iso()
    with self._lock:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id FROM projects WHERE name = ?",
                (name,),
            ).fetchone()
            if row is not None:
                # Even if the project already exists,
                # ensure the baseline roles are seeded
                # (idempotent on a re-run of an older
                # install that pre-dates the seed).
                self._seed_baseline_roles_for_project(
                    conn, int(row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO projects "
                "(name, description, owner_id, project_type, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    name,
                    _SYSTEM_SEED_DESCRIPTION,
                    int(owner_id),
                    _PROJECT_TYPE_SYSTEM,
                    now,
                    now,
                ),
            )
            new_id = int(cur.lastrowid)
            # Seed baseline roles for the newly created
            # system project. Same chokepoint as
            # :meth:`create` — done in the same
            # connection so a failed seed cannot leave
            # the project without its baseline roles.
            self._seed_baseline_roles_for_project(
                conn, int(new_id),
            )
            logger.info(
                "system project seeded id=%s name=%s owner_id=%s",
                new_id,
                name,
                int(owner_id),
            )
            return new_id
        finally:
            conn.close()


def install_bootstrap_methods() -> None:
    """Attach the bootstrap helpers to :class:`ProjectStorage`.

    Called by :mod:`feature_storage` at the bottom of the module
    (after :class:`ProjectStorage` is fully defined). The
    function is a no-op for any method that is already installed
    (idempotent re-import). Public names mirror the original
    methods so the call sites in :mod:`feature_storage` and
    :mod:`feature_app_factory` are unchanged:

    * ``_seed_baseline_roles_for_project`` — per-project
      baseline-role seed
    * ``create_system_project_if_missing`` — system-project
      bootstrap (called from the app factory)
    """
    from .feature_storage import ProjectStorage

    _BOOTSTRAP_METHODS = {
        "_seed_baseline_roles_for_project": _do_seed_baseline_roles_for_project,
        "create_system_project_if_missing": _do_create_system_project_if_missing,
    }
    for _name, _method in _BOOTSTRAP_METHODS.items():
        if _name not in ProjectStorage.__dict__:
            setattr(ProjectStorage, _name, _method)


# Install on import. The bottom of feature_storage.py also calls
# this defensively; running it twice is a no-op.
install_bootstrap_methods()


__all__ = ["install_bootstrap_methods"]
