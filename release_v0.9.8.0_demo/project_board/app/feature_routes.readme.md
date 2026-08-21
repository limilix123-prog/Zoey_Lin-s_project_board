# app / feature_routes

把各模块的 routes 挂到 Flask app 的注册入口。

- `register_routes(app)` 给 app 加 blueprint
- stage 1 已挂:`/healthz`(JSON `{"status":"ok"}`,smoke 用)
- stage 2 接 `auth/` `rbac/` 的 routes,加 `/` 的 session-aware redirect
- 注册的 blueprints: `auth_bp`, `rbac_bp`, `me_bp`, `project_members_bp`, `project_owner_bp`, `feature_board_bp`, `team_bp`;`team_bp` 含 `GET /team` 退役 302 handler (v0.9.7 退役,302 → /projects) + `POST /team/_internal/report` (copy-editor shared-secret write);`/profile` 302 → `/me`;`/healthz` JSON;`/` session-aware redirect
- **Feature Board**:
  - 注册 `feature_board_bp` (per-project kanban,4 列状态,can_manage_members gate)
- 本特性不写业务 view,只做"挂载";view 写在各自模块

**v0.9.7p1 cleanup**:
- `home_bp` 删除 (整 `home/` 模块物理删, `/home` 端点 404) — 7/17 self-contained 不再要求 /home alias (用户在 8/18 拍板选 B 路径)
- `register_routes` 末尾 logger `routes registered: count=%d` 替掉原 hardcoded 22-endpoint 列表 (v0.9.2 末 22 → 现 49 routes, 列维护成本高)

上游:`app/feature_app_factory.create_app` 调。
下游:`auth/` `projects/` `profile/` 各自的 routes 模块。
