# projects / feature_settings

项目 settings 端点(v0.9.1 sub-task 2 引入,sub-task 4 Issue 3 收窄到 name + description)。

**端点**:
- `GET  /projects/<int:project_id>/settings` — 渲染 settings 页面
- `POST /projects/<int:project_id>/settings` — 提交 name + description

**保护**:`@require_auth` + server-side `user_can_see_project` (read) + 3-bucket `_resolve_role` gate (write)。未登录 → 302 → /login;不可见 → 404;非 manage bucket → 403(POST) / 200 表单隐藏(GET)。

**v0.9.1 sub-task 4 — Issue 3**:
原 settings 页面含 change-owner 表单。Issue 3 把 change-owner **移到了** `/projects/<id>/members`(members 页面是单一 self-contained 入口管理 members + owner)。当前 settings **只剩** name + description,是 `ProjectStorage.update` 的薄包装(7/22 chokepoint)。

**legacy `/owner` 端点保留**:
`POST /projects/<id>/owner`(`feature_project_owner.py`)未删 — sub-task 3 砍了 nav 链接但 endpoint 留 v0.7.4 smoke `v054` 兼容。v0.9.1 默认走 `/members/change-owner`。

**3-bucket gate**:
`_resolve_role(storage, user, project)` 返回 `auto_own` / `owner` / `per_node_grant` / `None`。本端点接受 `auto_own` / `owner` 两种(`bucket in (_BUCKET_AUTO_OWN, _BUCKET_OWNER)`);`per_node_grant` 是 node-scoped 写授权,project-level 改名不需要,reject。

**7/17 self-contained UI**:
- 单一页面,所有字段(input text + textarea)在同一 URL
- 无 JSON textarea、无 card / pill / badge 原语、无 client-side state machine
- project_leader 落在页面可读 / 改 / 提交,不需要跨页跳

**Form contract**:
- `name` — 必填,trim 后空 → 302 + `?error=name is required`
- `description` — 选填,空字符串 = 清空 description
- 重复 name → 302 + `?error=<exc[:120]>`(sqlite3.IntegrityError)

**7/22 业务 lock**:
handler **只** 传 `name` / `description` 给 `ProjectStorage.update`,`owner_id` / `project_type` 在 storage 参数列表里都没有,hand-crafted POST 静默丢弃。

**流程**:
1. 拿 `user` + `ProjectStorage.find_by_id(project_id)`
2. `user_can_see_project` → 404 if 不可见
3. 拿 `owner_username`(从 `UserStorage.find_by_id`)
4. `_build_settings_context(user, project)` → `{can_edit_meta, bucket}`
5. 渲染 `projects/settings.html` + ctx
6. POST:`bucket in (_BUCKET_AUTO_OWN, _BUCKET_OWNER)` → 调 `storage.update()`
7. 成功 → 302 + `?notice=Settings saved`;失败 → 302 + `?error=...`

**字段常量**(`_FIELD_NAME` / `_FIELD_DESCRIPTION` / `_NOTICE_SAVED`):
跟 `settings.html` 同步。

**上游**:`app/feature_routes.register_routes` 注册 `project_settings_bp`(v0.9.1 sub-task 1)。
**下游**:`ProjectStorage.update`(7/22 chokepoint);`UserStorage.find_by_id`;`projects/settings.html`;`feature_role_v121._resolve_role`。
