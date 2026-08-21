"""v0.9.2 DDL fragment — 2 new tables + 2 new indexes.

The base schema (projects / project_members / project_features /
agent_team_status + 6 base indexes:
``idx_sessions_user_id`` / ``idx_users_username`` /
``idx_projects_owner`` / ``idx_members_user`` /
``idx_features_project_status`` / ``idx_users_created_at``) lives
in :mod:`project_board.projects.feature_storage` as
:data:`_SCHEMA_SQL`. The v0.9.2 extension is kept in this file so
the base file stays under the 1000-line cleancode threshold.

DDL contents (v0.9.3 — user-level node permissions removed)
-----------------------------------------------------------
1. ``project_nodes`` — N-level tree (1..6), 4 statuses, FK to
   ``projects`` (cascade on delete) + self-FK on ``parent_id``
   (cascade on delete the subtree).
2. ``project_custom_roles`` — per-project custom role rows
   (3 baseline roles seeded by migration; user-created roles
   added at runtime).
3. ``project_custom_role_permissions`` — per-(custom_role, node)
   write-grant template. The user's effective write on a node
   is the role-grant path: ``user → project_members.custom_role_id
   → project_custom_role_permissions.can_write``. There is no
   user-level grant table any more (v0.9.3 dropped
   ``project_node_permissions``; user 8/13 19:34 拍板).

Two new indexes back the tree-walk + the role-permission page.
The v0.9.2 sub-task 8 perf indexes for the deleted user-level
table (``idx_node_perms_node_user``) are gone with the table.
"""

from __future__ import annotations


# The v0.9.2 DDL fragment. Concatenated to the base
# ``_SCHEMA_SQL`` at init_schema time so a single
# ``executescript`` call installs the whole schema in one
# transaction.
_V092_DDL: str = """
-- v0.9.2: N-level tree, 4 statuses. ``project_features`` is
-- kept (read-only) per the 7/22 业务级 lock + 历史回溯 rule.
CREATE TABLE IF NOT EXISTS project_nodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    parent_id   INTEGER,
    level       INTEGER NOT NULL CHECK (level BETWEEN 1 AND 6),
    name        TEXT    NOT NULL,
    description TEXT,
    status      TEXT    NOT NULL DEFAULT 'backlog'
        CHECK (status IN ('backlog', 'in_progress', 'done', 'archived')),
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id)  REFERENCES project_nodes(id) ON DELETE CASCADE
);
-- v0.9.3 — user-level per-(user, node) permission table removed.
-- The role-grant path (user → project_members.custom_role_id →
-- project_custom_role_permissions) is the only path; the user-level
-- grant table that v0.9.2 added was empty (0 rows) and never wired
-- to the route layer. Migration: the table is left in place on a
-- pre-v0.9.3 DB by the migration; the DDL fragment just no longer
-- re-creates it on a fresh install.
-- v0.9.2 sub-task 7 — custom project role definition.
-- A project_leader / T0 / T1 can create custom roles
-- (e.g. "Reviewer", "Developer", "Tester") within a
-- project. The role name is unique within the project
-- (the ``UNIQUE (project_id, name)`` constraint enforces
-- this at the SQL layer) and is rendered verbatim in the
-- members page dropdown.
--
-- v0.9.2 sub-task 7 — there is no longer a
-- ``project_role_permissions`` table for the 3 baseline
-- role_in_project values. The 3 baseline role names
-- (project_leader / team_leader / user) are stored in
-- this table just like any other custom role, with the
-- project seed inserting the baseline rows. The single
-- ``project_role_permissions`` table below handles the
-- per-(role, node) grant template for **all** roles.
CREATE TABLE IF NOT EXISTS project_custom_roles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    name          TEXT    NOT NULL,
    description   TEXT,
    created_at    TEXT    NOT NULL,
    UNIQUE (project_id, name),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
-- v0.9.2 sub-task 7 — per-(role, node) write grant. The
-- ``custom_role_id`` foreign key is the canonical
-- per-project role id; the 3 baseline role names live
-- alongside any project-defined custom role in the
-- ``project_custom_roles`` table.
CREATE TABLE IF NOT EXISTS project_custom_role_permissions (
    custom_role_id INTEGER NOT NULL,
    node_id        INTEGER NOT NULL,
    can_write      INTEGER NOT NULL DEFAULT 0,
    granted_at     TEXT    NOT NULL,
    PRIMARY KEY (custom_role_id, node_id),
    FOREIGN KEY (custom_role_id) REFERENCES project_custom_roles(id) ON DELETE CASCADE,
    FOREIGN KEY (node_id)        REFERENCES project_nodes(id)        ON DELETE CASCADE
);
-- v0.9.2 sub-task 7 — the ``custom_role_id`` column on
-- project_members is added in init_schema with a try/except
-- wrapper (sqlite's ALTER TABLE ADD COLUMN has no
-- ``IF NOT EXISTS``). Keeping it out of this DDL fragment
-- avoids a duplicate-column error on the second
-- executescript() call.
-- v0.9.2: two new indexes for the project_nodes tree.
CREATE INDEX IF NOT EXISTS idx_nodes_project_parent
    ON project_nodes(project_id, parent_id, position);
CREATE INDEX IF NOT EXISTS idx_nodes_project_level
    ON project_nodes(project_id, level);
-- v0.9.1: custom role lookup indexes. The per-role grant
-- page renders every node for a given custom role, so the
-- composite index supports both the (custom_role_id) and
-- (custom_role_id, node_id) lookups. The
-- ``idx_members_custom_role`` index on ``custom_role_id``
-- is added in init_schema AFTER the
-- ``ALTER TABLE project_members ADD COLUMN`` step (the
-- column does not exist when this fragment runs, so a
-- CREATE INDEX referencing it would fail).
CREATE INDEX IF NOT EXISTS idx_custom_role_perms_role
    ON project_custom_role_permissions(custom_role_id);
-- v0.9.2 sub-task 7 — covering index for ``list_role_node_permissions``
-- ORDER BY ``granted_at ASC``. With (custom_role_id, granted_at) the
-- engine returns rows in order directly. Idempotent.
CREATE INDEX IF NOT EXISTS idx_custom_role_perms_role_granted
    ON project_custom_role_permissions(custom_role_id, granted_at);
-- v0.9.2 sub-task 8 (perf 9 ops) — covering index for the ``list_tree`` ORDER BY
-- ``(level, parent_id, position, created_at)``. The composite
-- matches the WHERE (project_id=?) plus the full ORDER BY, so the
-- engine returns rows in order with NO temp btree. Column order
-- re-prioritised (level inserted between project_id and parent_id)
-- because the original spec column order missed ``level`` and the
-- verify's strict EXPLAIN check still showed TEMP B-TREE FOR RIGHT
-- PART OF ORDER BY. The original ``idx_nodes_project_level`` is
-- kept untouched for the level-only lookup path.
CREATE INDEX IF NOT EXISTS idx_nodes_project_parent_pos
    ON project_nodes(project_id, level, parent_id, position, created_at);
"""


__all__ = ["_V092_DDL"]
