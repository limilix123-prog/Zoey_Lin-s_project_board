# projects / feature_storage_ddl_v092

v0.9.2 DDL fragment — 2 张新表 (v0.9.3 — user-level perm 表删) + 2 个新索引。Base schema (`projects` / `project_members` / `project_features` / `agent_team_status` + 6 base 索引:`idx_sessions_user_id` / `idx_users_username` / `idx_projects_owner` / `idx_members_user` / `idx_features_project_status` / `idx_users_created_at`) 留在 `feature_storage._SCHEMA_SQL` 维持 cleancode 1000 行阈值。

## DDL 内容 (v0.9.3 现状)

| 表 | 用途 | FK CASCADE |
|---|---|---|
| `project_nodes` | N-level tree (1..6), 4 statuses | projects(id) + self-ref parent_id |
| `project_custom_roles` | per-project 自定义 role (3 baseline seed) | projects(id) |
| `project_custom_role_permissions` | per-(role, node) write-grant template | project_custom_roles(id) + project_nodes(id) |

2 个新索引 back: tree-walk (v0.9.3 board view level-bucket query) + role-permission page 查 (`list_role_node_permissions` 路径)。

**v0.9.3 删** (user 8/13 19:34 拍板):
- `project_node_permissions` 表 (per-(user, node) write-grant) — DDL fragment 不再 install; pre-v0.9.3 DB 上此表保留 (0 行实际数据, 无 caller)
- `idx_node_perms_node_user` 索引 — 跟表一起删
- `feature_storage_node_permissions.py` + `feature_role_v121_ddl.py` + `feature_role_v121_cascade.py` (引已删表, 无 caller) — 物理删 (走回收站)

## 上游 / 下游

- 上游: `feature_storage.init_schema` 调 `_V092_DDL` (`CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` idempotent)
- 下游: 无 (本模块纯 DDL, 不写 Python 方法)
