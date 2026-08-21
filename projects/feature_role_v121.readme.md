# projects / feature_role_v121

v0.9.1 RBAC 矩阵 + v0.9.3 简化 (user-level grant 删, 改 role-grant 路径)

## 3-bucket 矩阵 (OR 合并, v0.9.3 现状)

| Bucket | 范围 | 判定 |
|---|---|---|
| `auto_own` (T0/T1) | 项目级全局 | `user.rank in (0, 1)` — 平台级 admin/manager 无条件可读 / 写任何 project |
| `owner` (T2) | 项目级全局 | `user.rank == 2` ∧ `user.id == project.owner_id` — 拥有 project 的 T2 才有此 bucket |
| `role_grant` (任意 rank) | node-scoped 写 | user 是 project member + 有 `custom_role_id` + 该 role 在 `project_custom_role_permissions` 该 `node_id` 上有 `can_write = 1` |

`_resolve_role(storage, user, project, node=None)` 返回最高匹配的 bucket 字符串或 `None`。order: `auto_own` > `owner` > `role_grant`。

`role_grant` 只在调用方传入 `node` 参数时检查 — 没传 `node` 就不查 SQL, 避免意外触发 SELECT。

**v0.9.3 变化**: 删 `per_node_grant` bucket (`project_node_permissions` 表 + 对应 helper + 对应 chokepoint)。role-grant 是新的 node-scoped 路径 (走 `project_custom_role_permissions`)。user-level per-(user, node) grant 在 v0.9.2 实际是 0 行数据 + 路由层从未真正调用 chokepoint 的混合态, user 8/13 19:34 拍板删整套。

## 3 server-side chokepoints (v0.9.3 — 从 4 砍 1)

每个 chokepoint 接收 `storage` + 业务参数 + `actor`, 做 actor 鉴权 + target 校验 + 调 policy-free storage 方法 + 写 log:

| Chokepoint | 端点 | 鉴权 | 业务规则 |
|---|---|---|---|
| `add_member_action` | `POST /projects/<id>/members` | auto_own / owner | target 非 T0/T1 (已 auto-own) |
| `remove_member_action` | `POST /projects/<id>/members/<uid>/remove` | auto_own / owner | anti-self |
| `change_owner_action` | `POST /projects/<id>/members/change-owner` | **T0/T1 only** | 非 system project + target rank 2 |

7/22 业务 lock 全部命中 — chokepoint **绝不** 信任 client 状态, hand-crafted POST 在 chokepoint 被拒, 不会到 storage 层。

**v0.9.7p1 cleanup 删**: `_project_storage` 死 helper (0 caller — 3 chokepoint 都从入参接 `storage`, 从不调本 helper 拉 Flask `current_app.config["PB_CONFIG"]["DB_PATH"]`)。

**v0.9.3 砍掉**:
- `grant_node_action` (v0.9.1 4th chokepoint) — 整个 per-(user, node) grant 端点 (`POST /projects/<id>/members/<uid>/permissions`) 删。Role-grant 路径走 `submit_role_node_permission` (在 `feature_members_page.py`), 那是 thin wrapper 调 `ProjectStorage.set_role_node_permission`, RBAC 在 route 层做 (因为 chokepoint 集 3→3 不再 +1)。

## chokepoint 错误映射

| Chokepoint 异常 | Route 映射 |
|---|---|
| `PermissionError` | 403 (或 302 + `?error=...` 在 members page 路径) |
| `ValueError` | 400 (或 302 + `?error=...`) |
| `sqlite3.IntegrityError` | re-raise 给 caller 处理 (典型: composite PK 重复 → 200 + "already a member") |

## 跟 v0.7.x 规则的关系

| v0.7.x 规则 | v0.9.1 替换 |
|---|---|
| `can_manage_members(user, project)` (T0/T1 / project owner) | `_check_can_manage_project(user, project)` — 同义, 代码层用新名 |
| `_is_auto_own(user)` | 不变 (沿用 v0.7.2a) |
| `require_role(MANAGER)` 装饰器 | 不变 (沿用 v0.7.2a, `feature_create` 仍用) |

`_is_owner(user, project)` 是 v0.9.1 新增, 显式区分 "T2 owner" 和 "T0/T1 auto-own" (T0/T1 即使 `user.id == project.owner_id` 也走 auto_own bucket)。

## 3 chokepoint 共同点

- **薄**: policy 在 `_resolve_role` + chokepoint 里, storage 方法不读 actor
- **不可信 client**: 所有 actor 鉴权 server-side 跑一次, 无论 UI 怎么过滤
- **可测**: 每 chokepoint 是独立函数, smoke 测 "actor X, target Y, 期望 Z" 三件套

## 3-bucket 跟 v1.2.1 read/write/admin 的区别

v1.2.1 是 3 列 (read/write/admin) × 多 role 矩阵; v0.9.3 是 **3 bucket 通过 OR 合并**, 简化到最小可行 (minimum viable)。理由: T2 通过在 role 上 grant node-scoped 写权 (role members 自动继承), 不需要 r/w/a 三列全展开, 也不需要 user-level override。

## 上游 / 下游

- 上游: `feature_settings` + `feature_members_page` + `feature_edit` (写鉴权)
- 下游: `ProjectStorage` policy-free writers (`add_member` / `remove_member` / `update_owner` / `set_role_node_permission` / `clear_role_node_permission`)

## v0.9.1 → v0.9.3 grant 写入路径变化

| | v0.9.1 | v0.9.3 |
|---|---|---|
| 写 user-level grant | `grant_node_action` (4th chokepoint) → `ProjectStorage.grant_node_permission` | **删** |
| 写 role-level grant | `submit_role_node_permission` (route, RBAC 在 route) → `ProjectStorage.set_role_node_permission` | **保留** (route-only, 不进 chokepoint 集) |
| 读 user-level grant | `_has_node_grant` (bucket 3 检查) | **删** |
| 读 role-level grant | `_has_node_role_grant` (新增) → `project_custom_role_permissions` JOIN `project_members` | **新增** (替 user-level) |
