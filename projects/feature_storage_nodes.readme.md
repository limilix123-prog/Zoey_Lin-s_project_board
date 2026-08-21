# projects / feature_storage_nodes

`ProjectStorage` node 方法 split-out(v0.9.2 引入,目的是让 `feature_storage.py` 控制在 1000 行 cleancode 阈值内)。

## 9 个 methods(挂到 `ProjectStorage`)

`install_node_methods()` 在 import 时自动挂载(也由 `feature_storage.py` 底部 defensive 调一次,idempotent):

| Method | 作用 | Server-side chokepoint 验证 |
|---|---|---|
| `create_node(project_id, parent_id, level, name, description, status="backlog")` | INSERT 一行 | 6-level 范围 + parent 同 project + parent.level+1 == level + status whitelist + name 非空 |
| `find_node_by_id(node_id)` | SELECT 返 dict 或 None | — (read-only) |
| `list_children(project_id, parent_id)` | SELECT 直系 children,按 (position, created_at) 排序 | — |
| `list_tree(project_id)` | SELECT 全树 flat,按 (parent_id, position, created_at) 排序 | — |
| `get_tree(project_id)` | 从 list_tree 构造 parent→children 嵌套,top-level 节点返回 | — |
| `update_node(node_id, name, description, status)` | UPDATE 三字段(name + description + status) | name 非空 + status whitelist |
| `move_node(node_id, new_parent_id, new_position)` | 重新 parent + 同步 subtree level | cycle check + subtree cap + 6-level invariant |
| `delete_node(node_id)` | DELETE 单行(FK CASCADE 删 subtree) | — |
| `delete_subtree(node_id)` | BFS 收集 subtree → 一次性 DELETE | — (v0.9.1 sub-task 11 真删) |

所有 write 走 `self._lock` + `self._connect()` 包住,read 同。`find_node_by_id` 返 plain dict(不返 dataclass,v0.9.2 最小可行 surface)。

## 6-level invariant

`MAX_NODE_LEVEL: int = 6`。`level` 必须在 `[1, 6]`(`create_node` server-side `ValueError`):

- `parent_id` 必须属同一 `project_id`(否则 `ValueError`,FK 也兜底)
- 新 node `parent.level + 1 == level`(`chain consistency`)
- `move_node` 也要验 — 把 level-2 节点移到 level-5 subtree 会让 descendant 超 6

`level` 只能 create / move 时改,`update_node` 不接受 `level` / `parent_id` 参数(防 hand-crafted POST 改 depth)。

## Status whitelist

```python
_NODE_STATUSES = frozenset({"backlog", "in_progress", "done", "archived"})
```

跟 legacy `project_features` 表同 4 字面量 — hybrid board 渲染(rows 来自两表)用同一列逻辑。SQL CHECK 约束 + `_clean_status` helper 双层守。Hand-crafted POST 传 `status="unknown"` 抛 `ValueError`(route 映射 400)。

## FK chain

DDL(`feature_storage_ddl_v092._V092_DDL`)装的:
- `project_nodes.project_id → projects.id ON DELETE CASCADE`
- `project_nodes.parent_id → project_nodes.id ON DELETE CASCADE`
- `project_custom_role_permissions.custom_role_id → project_custom_roles.id ON DELETE CASCADE` (v0.9.2 sub-task 7)
- `project_custom_role_permissions.node_id → project_nodes.id ON DELETE CASCADE` (v0.9.2 sub-task 7)

(v0.9.3) — the user-level `project_node_permissions` table that
v0.9.2 had installed is **gone** together with its two FK
chains (`user_id → users.id` and `node_id → project_nodes.id`).
The role-grant path (above) is the only node-scoped write
surface. The cascade contract on `project_custom_role_permissions`
is what the role-grant path relies on: deleting a role removes
every per-(role, node) grant; deleting a node removes every
per-(role, node) grant that referenced it.

## v0.9.1 sub-task 11 真删

`delete_subtree(node_id)`:BFS Python 收集 descendants → 单条 `DELETE ... WHERE id IN (...)`,**物理删除**。user 8/12 17:45 拍板"撤回 soft delete, 真删"。理由:soft delete (status='archived') 只让表变胖;UI 渲染 5+ 节点 archived 行污染 sidebar / board。

7/22 RBAC 业务 lock 仍在(actor 鉴权 + chokepoint + 二次确认 + 不可逆)— lock 管"谁能调",不管"行是否该存活"。hand-crafted POST 一样被 actor 鉴权 + 二次确认拦。

Returns:被删行数(root + descendants)。root 不存在 → 0。

## cycle / 6-level cap 验证

`move_node`:
1. 读 moved node
2. 解析 new_parent level(None → 0)
3. `new_level = new_parent_level + 1` → 必须在 `[1, 6]`
4. BFS 收集 descendants set
5. **cycle check**:new_parent_id 不能在 descendants set
6. **subtree cap check**:`max_descendant_level + level_delta ≤ MAX_NODE_LEVEL`
7. UPDATE moved node(parent_id + level + position)
8. UPDATE descendants set:`level = level + delta`

任一 fail 抛 `ValueError`,`changed = False`,route 映射 400。

## 跟 `feature_storage` 的关系

`feature_storage.py` 仍然持有 `ProjectStorage` class + 大部分方法(add_member / remove_member / update / update_owner / find_by_id / list_* / user_can_see_project 等)。9 个 node 方法 + 3 个 node permission 方法独立成 `_do_*` 函数,通过 `install_node_methods()` + `install_node_permission_methods()` 挂到 class。Public API(`storage.create_node(...)` 等)不变,route 层 import 路径不变。

## 上游 / 下游

- 上游:`feature_board` (board 端点) / `feature_view` (sidebar) / `feature_members_page` (per-(user, node) 渲染)
- 下游:无(`ProjectStorage` 是 leaf module)

## cycle import 处理

`feature_storage_nodes` import 走 `feature_storage` class(在 module body 之前不存在)。解决:`install_node_methods()` 内函数体 import `from .feature_storage import ProjectStorage`;`create_node` / `update_node` / `move_node` 内函数体 import `from .feature_storage import _now_iso`。`install_node_methods()` 在 module 底部调一次。
