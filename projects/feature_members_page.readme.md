# projects / feature_members_page

项目成员管理 + per-(role, node) 权限 UI (v0.9.1 + v0.9.3 简化).

**端点**:
- `GET  /projects/<int:project_id>/members` — 渲染 members 管理页 (member list + add form + change-owner form + role-grant 说明)
- `POST /projects/<int:project_id>/members/change-owner` — 改 owner (sub-task 4 Issue 3 移过来)
- `POST /projects/<int:project_id>/roles` / `GET /roles` — custom role create / list
- `GET  /projects/<int:project_id>/roles/<int:role_id>` — 渲染 per-(role, node) 权限页 (the v0.9.3 grant UI)
- `POST /projects/<int:project_id>/roles/<int:role_id>/permissions` — 改 per-(role, node) grant
- `POST /projects/<int:project_id>/roles/<int:role_id>/delete` — 删 custom role
- `POST /projects/<int:project_id>/members/<int:user_id>/role` — 改 member 的 custom_role

**保护**: `@require_auth` + server-side `user_can_see_project` (read) + 3-bucket `_resolve_role` gate (write).未登录 → 302; 不可见 → 404; 非 `auto_own` / `owner` bucket → 403。

**v0.9.3 简化** (user 8/13 19:34 拍板 — 删 per-(user, node) 整套):
- `GET  /projects/<id>/members/<uid>/permissions` (per-user grant UI) — **删 endpoint** (改 404 stub, stale bookmark 给信号)
- `POST /projects/<id>/members/<uid>/permissions` (per-user grant submit) — **删 endpoint** (改 404 stub, 7/22 RBAC 业务 lock 端点是唯一 server 鉴权口; endpoint 删 = storage 写端无 caller, 物理上 user-level table 不能再从 route 层被改)
- `_list_user_perm_rows` + `_list_all_user_perms_rows` (per-user SQL helpers) — **删**
- `per_user_permissions` context field (members page) — **删**
- `_list_grants_for_node` + `_collect_user_node_perms` (board view user-level grants) — **删, 改 role 路径**
- `feature_role_v121.grant_node_action` (4th chokepoint) — **删**
- `feature_role_v121._has_node_grant` (per-user node grant 查) — **删, 改 `_has_node_role_grant`**
- `_BUCKET_PER_NODE` (3rd bucket tag) — **改名为 `_BUCKET_ROLE_GRANT`**
- `project_node_permissions` 表 + `idx_node_perms_node_user` 索引 — **不创建 (v0.9.2 加的, v0.9.3 DDL 删)**
- `feature_storage_node_permissions.py` + `.readme.md` — **物理删 (走回收站)**
- `feature_role_v121_ddl.py` + `_cascade.py` + `.readme.md` — **物理删 (引已删表, 无 caller)**

**v0.9.1 整合** (sub-task 2 + 4):
- 旧 `POST /projects/<id>/members` + `POST /members/<uid>/remove` (`feature_project_members`) 留, **不** 改 — 新 form 的 "Add member" 按钮 POST 走原 endpoint URL
- change-owner 表单 **从 settings 移到 members** (sub-task 4 Issue 3) — 单一 self-contained 页面管 members + owner
- per-(role, node) grant/revoke 走 `/roles/<role_id>` 页面 (`custom_role.html` 模板) — v0.9.3 是 single per-role form flow

**3-bucket gate (write)**:
`_resolve_role` 返回 `auto_own` / `owner` / `role_grant` / `None`。Members page 的 change-owner form 只对 `auto_own` 可见 (`_is_auto_own(user)` + 非 system project), 不是 owner 也行 (因为 change-owner 是 T0/T1-only, 跟 owner-based manage 不同)。Per-role grant form 对 `auto_own` / `owner` 可见。

**3 server-side chokepoints** (v0.9.3 — 从 4 砍 1):
所有写操作走 `feature_role_v121` 的 3 个 chokepoint (`add_member_action` / `remove_member_action` / `change_owner_action`), 7/22 业务 lock。第 4 个 `grant_node_action` 在 v0.9.3 删 (per-user grant 删了)。Role-grant 写 (chokepoint 集外) 走 `submit_role_node_permission` thin wrapper, RBAC 在 route 层 (auto_own / owner bucket), 写 storage 的 `set_role_node_permission` 是 policy-free.

**Cross-project guard**:
- change-owner: target rank 2 + target exists (chokepoint 内)
- add/remove member: actor bucket + target exists (chokepoint 内)
- role-grant: JOIN `project_custom_roles` 在 `set_role_node_permission` 内隐式做 — cross-project / 不存在 role 返 no-op
- role create: `UNIQUE (project_id, name)` constraint + IntegrityError 抛错

**Form contract**:
- change-owner: `new_owner_id` (select, 仅 T2 users, system project 隐藏)
- role create: `name` (required, ≤ 64 chars) + `description` (optional)
- per-(role, node) grant: `node_id` + `can_write` (1=grant, 0=revoke)
- set member role: `custom_role_id` (select, 含 (no role) 选项)

**7/17 self-contained UI**:
- members 页面: **单一 URL** 包含 member list + add form + change-owner form + role-grant 说明
- per-(role, node) 权限页 (`custom_role.html`): role 信息 + member 列表 + node 列表 + 每行 checkbox + 单 submit
- 无 card / pill / badge 原语、无 JSON textarea、缩进表达层级

**Members 列表过滤**:
- T0/T1 (auto-own) 行被过滤, 不在 UI 显示 (7/22 业务 lock 一致)
- `is_self` flag 标自身行
- `addable_users`: 非 member / 非 owner / 非 self / 非 T0/T1, 按 username 排序

**字段常量** (`_FIELD_USER_ID` / `_FIELD_NODE_ID` / `_FIELD_CAN_WRITE` / `_FIELD_NEW_OWNER` / `_NOTICE_GRANTED` / `_NOTICE_REVOKED` / `_NOTICE_NOOP` / `_NOTICE_OWNER_CHANGED` / `_NOTICE_OWNER_UNCHANGED`):
跟 `members.html` / `custom_role.html` 同步。

**上游**: `app/feature_routes.register_routes` 注册 `project_members_page_bp` (v0.9.1 sub-task 1)。
**下游**: `ProjectStorage` (list_members / find_node_by_id / list_tree / set_role_node_permission / clear_role_node_permission / is_member / list_roles / create_role / delete_role / set_member_role); `UserStorage` (find_by_id / list_all_users); `feature_role_v121` 的 3 chokepoints; `projects/members.html` + `projects/custom_role.html` + `projects/custom_roles.html`。
