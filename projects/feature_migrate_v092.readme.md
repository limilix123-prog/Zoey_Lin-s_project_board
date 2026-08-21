# projects / feature_migrate_v092

v0.9.2 data model migration — 加 `project_nodes` (+ role 表) (v0.9.3 — user-level perm 表 install step 删)。Auto-run on app start, idempotent。

## 新表 (v0.9.3 现状)

| 表 | 字段 | FK CASCADE | 备注 |
|---|---|---|---|
| `project_nodes` | id, project_id, parent_id, level, name, description, status, position, created_at, updated_at | projects(id) + self-ref parent_id | 6-level cap, 4 statuses |
| `project_custom_roles` | id, project_id, name, description, created_at | projects(id) | UNIQUE (project_id, name), 3 baseline seed |
| `project_custom_role_permissions` | (custom_role_id, node_id) composite PK, can_write, granted_at | project_custom_roles(id) + project_nodes(id) | per-(role, node) write-grant template |

`parent_id IS NULL` 表示 top-level, depth 由 `feature_storage_nodes` helper server-side 强制。

**v0.9.3 砍** (user 8/13 19:34 拍板):
- Step 2 (`project_node_permissions` install) — 整段移除。Pre-v0.9.3 DB 上表保留 (0 行实际数据, 无 caller, 7/22 业务级 lock 禁 silent DELETE)

Migration 不删行 — 保留 `project_features` legacy 表 (read-only), 7/22 业务级 lock + 历史回溯要求。

## 上游 / 下游

- 上游: `feature_app_factory.create_app` (首启自动调)
- 下游: 无
