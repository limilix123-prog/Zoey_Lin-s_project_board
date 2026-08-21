# projects / feature_board

Unified board endpoint,4 列 kanban + 6 层 tree 共存(v0.9.3 整合;v0.9.3 简化 per-(user, node) grant 改 role-grant 路径)。

## 9 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects/<int:id>/board` | 渲染统一页(self-contained:info + 4 列 + 6 层树) |
| POST | `/projects/<int:id>/nodes` | 6 层 tree create node(level cap + status whitelist) |
| POST | `/projects/<int:id>/nodes/<int:nid>/edit` | 改 name + description + status |
| POST | `/projects/<int:id>/nodes/<int:nid>/status` | quick-change status |
| POST | `/projects/<int:id>/nodes/<int:nid>/delete` | 物理删 node + subtree(BFS DELETE,v0.9.1 sub-task 11 真删) |
| GET | `/projects/<int:id>/features` | 跳 /board(redirect) |
| POST | `/projects/<int:id>/features` | legacy feature add(保留) |
| POST | `/projects/<int:id>/features/<int:fid>/move` | legacy feature move(保留) |
| DELETE | `/projects/<int:id>/features/<int:fid>` | legacy feature delete(保留) |

## UI 设计

7/17 self-contained:单页含全部信息,无 cards / pop-ups / tab。缩进表达层级(`padding-left: depth*20px`),`<details>` 渐进展开 OK。

## 权限模型 (v0.9.3)

- Read:`user_can_see_project`(owner / member / T0/T1 auto-own)
- Write (项目级):`_can_write_board`(T0/T1 auto-own OR project owner;2-class gate)
- Write (node-scoped, read-only viewer 的 "write access to" label 渲染):`_collect_user_role_node_perms` 一次性 JOIN `project_custom_role_permissions` + `project_members` (1 query, 替 v0.9.2 的 per-(user, node) N+1)
- v0.9.3 删 `_list_grants_for_node` (per-(user, node) N+1 走单 subtree 路径) + `_collect_user_node_perms` (per-(user, node) batch SELECT), 改 role 路径

## anti-cross-project

所有 POST/DELETE 走 `_get_node_or_404` 校验 `node.project_id == project_id`;storage 层 FK + `AND project_id = ?` 第二道守门。Hand-crafted POST 跨 project 返 404。

## 上游 / 下游

- 上游:`app/feature_routes.register_routes` 注册 `feature_board_bp`
- 下游:`feature_storage` (项目 CRUD / members) + `feature_storage_nodes` (6-level tree CRUD) + `ProjectStorage.set_role_node_permission` (role-grant 读 — v0.9.3 role 路径)
