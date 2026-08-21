# app / feature_templates

Jinja2 template 加载器 + 公共 layout,放 `app/templates/`。

- `init_templates(app, app_root)` 注册 `FileSystemLoader(app_root/templates)` 到 Jinja 环境
- 用 `ChoiceLoader` 包装,各模块(`auth/` `projects/`)的 `templates/` 子目录自动接入
- 注册的 Jinja globals:
  - `site_name`(`'project_board'`)— 站点名
  - `current_year()`(UTC 当年)— footer 版权年份
  - **`current_user_is_authenticated()`** — base.html 用来分支已登录 / 未登录 nav
  - **`current_username()`** — base.html 显示当前用户名
  - **`format_rank_label(rank)`** — T-scale 标签 (T0 系统管理员 / T1 平台管理员 / T2 项目负责人 / T3 团队负责人 / T4 普通用户); 来自 `feature_storage_rbac`, `format_rank_label` 透传
  - **`format_time` filter** — ISO 8601 → `YYYY-MM-DD HH:MM` 短形
- 所有 auth-state globals 是**函数对象**(lazy lookup),在模板渲染时读
  `flask.g.current_user`,避免在 startup 阶段请求上下文外求值得到 `None`
- `templates_dir(app_root)` 暴露路径,给各模块参考

**v0.9.7p1 cleanup 删**:6 个 Jinja globals + 内部 import + 函数体
(`current_user_is_admin` / `current_user_is_manager` / `current_user_is_project_leader` /
`current_user_is_team_leader` / `current_user_role` / `current_user_rank_label`)
+ `__all__` 同步条目。
- 全模板 grep 0 hit — 实际模板从来没用这些 wrapper,直接读 `user.rank` 拼字符串
  或用 `format_rank_label` helper
- 配套:`_MODULES_WITH_TEMPLATES` 从 `("auth", "home", "projects", "rbac")` 缩到
  `("auth", "projects")` — `home` / `rbac` 目录不存在 / `team` v0.9.7 已退役
- `me.html` / `users_list.html` / `user_view.html` 从 `app/templates/` 迁到
  `projects/templates/projects/` (callers 改 `render_template("projects/me.html")` 等)
  — 6 原则 1 模板按模块分

**当前 `app/templates/` 内容**:`base.html`(共享 nav + 公共样式 + content
block)、`login.html`、`register.html`、errors/ 目录 (403/404/405 中文模板)、
help/glossary.html。

**当前 `projects/templates/projects/` 内容**:`board.html` / `custom_role.html` /
`custom_roles.html` / `edit.html` / `list.html` / `me.html` (v0.9.7p1 迁入) /
`members.html` / `new.html` / `settings.html` / `system_view.html` / `user_view.html`
(v0.9.7p1 迁入) / `users_list.html` (v0.9.7p1 迁入) / `view.html`。
(`node_permissions.html` v0.9.7p1 物理删,user-level grant surface 早 v0.9.3 已退役)

上游:`app/feature_app_factory.create_app` 调。
下游:各 feature 渲染模板时用 `site_name` / `current_year` / `current_user_is_authenticated` /
`current_username` / `format_rank_label` / `format_time` / block 继承。
