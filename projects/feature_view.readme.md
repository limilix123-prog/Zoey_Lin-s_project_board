# projects / feature_view

项目详情端点。GET `/projects/<int:project_id>`。

**保护**:`@require_auth` + server-side `user_can_see_project` (7/22 业务级 lock)。未登录 → 302 → /login;不可见 → 404(不泄露存在性)。

**v0.7.2a auto-own 短路**:`user_can_see_project` 第一行就是 `_is_auto_own(user)` — T0/T1 (admin/manager) 无条件可见任何 project。`is_admin` 局部变量也改为 `_is_auto_own(user)`,所以 `viewer_role` label 对 T0/T1 都显示 "admin"。

**流程**:
1. 拿 `g.current_user` + `ProjectStorage.find_by_id(project_id)`
2. 拿 `is_admin = _is_auto_own(user)` (v0.7.2a, 旧 `user.role == "admin"`)
3. `user_can_see_project(user, project, is_admin)` → 404 if 不可见
4. branch on `project.is_system`:
   - system project → `system_view.html` + scan `_scan_project(project_root)` + `members` (T0/T1 过滤后) + `_build_member_context`
   - user project → `view.html` + `owner_username` (从 UserStorage 拿) + `viewer_role` + `can_delete` + `can_manage_members` flag
5. 算 `can_delete` (T0/T1 → True, 其他 → False; v0.7.2a 改 `_is_auto_own(user)`)
6. 算 `viewer_role` (T0/T1 → "admin", owner → "owner", 其他 → "member")
7. 渲染对应模板,带所有上下文

**v0.7.2a members 过滤 (system project only)**:
SQL `list_members` 返回的原始 list 经过 `_filter_auto_own_members()` 过滤掉 T0/T1 (auto-own) 行,再传给 system_view 模板 + `_build_member_context`。这样 v0.7.0 留下的 T0/T1 旧 row 不会在 UI 显示(对应决策 "list members: 过滤 T0/T1")。`addable_users` 同样过滤 T0/T1(add 端点会 400 拒绝它们,dropdown 不能给)。**user project 路径不再渲染 members 段**,因为 members 已经收编到 `/members` 端点。

**v0.9.1 sub-task 4 — Issue 2/3/4: view 端点收尾**:
- Issue 2: 6 层节点树从 view 移到 board (board 已有 writable 树;view 的只读副本是重复)。
- Issue 3: 成员列表 + change owner 段从 view 移到 `/members` 端点。view 只剩 project info + manage links。
- Issue 4: view 设置 `project` context var,nav 自动出 Members 链接。
- danger zone (Delete project) 留在 view,project-scoped action。
- `_build_owner_context` 和 `_max_node_level` 退役;未用的 `ADMIN` / `MANAGER` / `PROJECT_LEADER` import 移除。

**Manage 段 (v0.9.1 sub-task 4 末)**:
view 端点模板加 "Manage" 段,把 sub-task 2 新加的 3 个子页 (Settings / Members / Board edit) 链成一组,对 `can_manage_members` 的 actor 全部可见。Read-only viewer (T3 / T4 非 owner) 只看到 Board (read-only) 链接 + 提示文字。

**v0.9.7p1 cleanup**:
- `_scan_project_cache_clear()` 死函数删(0 caller — `@lru_cache(maxsize=1)` 进程级 cache 的 refresh 走 process restart, 文档化在 `_scan_project` docstring)
- `viewer_rank_label` ctx 字段删(view.html 改用 `format_rank_label(viewer_user_rank)` 单一 source of truth, 跟 /me /users 渲染同一字符串; `viewer_user_rank` 保留)
- `format_rank_label` 局部 import 删(只在 view.html 模板里调,Python 端不需 import)

**可见性规则**(在 `feature_storage.user_can_see_project`):
- T0/T1 (auto-own) → always
- owner → always
- member (T2/T3/T4 row in project_members) → always
- 其他 → False
