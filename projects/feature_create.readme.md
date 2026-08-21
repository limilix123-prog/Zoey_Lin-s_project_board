# projects / feature_create

新建项目端点。GET / POST 都走 `/projects/new`。

**v0.7.2a revert 保护 (8/7 user 拍板)**:`@require_role(MANAGER)` — v0.7.0 5-role 矩阵下 `manager` 的旧 rank 是 4, 所以 gate 只接受 T0/T1 (admin/manager, 旧 rank 5/4), 拒绝 T2/T3/T4 (project_leader/team_leader/user, 旧 rank 3/2/1) → 403。装饰器在 handler 逻辑前 short-circuit。未登录 → 302 → /login。v0.7.2a 期间曾临时改成 `PROJECT_LEADER` 让 T2 也能 create,与 owner-based 矩阵不一致,已被 revert 移除。

**流程 (POST)**:
1. 从 form 拿 `name` (trim) 和 `description` (trim)
2. 校验:name 必填、≤ 200 字;description ≤ 4000 字
3. 校验失败 → 重新渲染 `new.html` 带 `error` + `form`(保留用户输入)
4. 调 `ProjectStorage.create(name, description, owner_id=g.current_user.id)`
5. 重名 → 捕获 `sqlite3.IntegrityError` → 重新渲染带 "project name taken"
6. 成功 → 302 → `project_view.show_project(project_id=new_id)`

**错误字符串**:`project name is required` / `project name taken` / `project name must be at most 200 characters` / `description must be at most 4000 characters` / `system project cannot be created via API` / `owner_id must be an integer` / `owner user not found`(都暴露给用户,无内部细节)。

**模板**:projects/new.html 继承 base.html;GET 空 form 渲染;POST 失败时回显 `form.name` / `form.description`(已 `| e` 转义)。

**v0.7.2a owner 下拉**:`_owner_dropdown` 列全部 T0..T4 用户(包括 admin / manager),因为 owner 字段不限制 role — 任何 T 级都能拥有 project。
