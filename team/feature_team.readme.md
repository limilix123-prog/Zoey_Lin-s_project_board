# team / feature_team

Team 端点 — v0.9.7 退役 `GET /team` (302 → /projects),保留 `POST /team/_internal/report` 供 copy-editor 推 agent 状态。shared secret 认证。

**端点**:

- `GET /team` — v0.9.7 退役(302 → /projects)。`@require_auth` 保留,anonymous 走 /login,signed-in user 走 /projects(7/17 self-contained 守门 — 不留 404 dead-end)。
- `POST /team/_internal/report` — copy-editor 推一批 agent row,shared secret 认证。

**保护**:

- `GET /team` — `@require_auth` + 302 redirect handler
- `POST /team/_internal/report` — shared secret (env var `COPY_EDITOR_SHARED_SECRET` 配 `X-Copy-Editor-Secret` header), 不用 `@require_auth` (机器写入, 不用 session cookie)

**流程 (GET, retired)**:

1. `@require_auth` 注入 `g.current_user` (anonymous 走 /login)
2. log 一行 `team view retired -> /projects user_id=X role=Y`
3. `redirect(url_for("projects_list.show_projects"))` → 302

**流程 (POST report)**:

1. 读 `X-Copy-Editor-Secret` header 跟 `COPY_EDITOR_SHARED_SECRET` env var 比对 → 不匹配 / 缺 → 401
2. env var 缺 → 401 (服务器未配)
3. 读 JSON body, 必须是 list → 不是 → 400
4. `apply_team_report(report, reported_by="copy-editor")` UPSERT (走 `feature_team_storage`)
5. 任何 entry 字段验证失败 (缺 `agent_name` / status 不在 whitelist / `task_count` 负数或非 int) → 400 (整批拒绝)
6. 成功 → 200 `{ok: true, count: N}`

**RBAC**:

- 读: `@require_auth` (任何登录用户, retired handler 仍守 decorator)
- 写: shared secret (7/22 business-lock 原则 — 端点验证 secret, storage 不感知)

**状态白名单**: `TEAM_STATUSES = {idle, busy, blocked, offline}`。任何其他值 → 400。

**数据表**:

- `agent_team_status(agent_name PK, description, status, task_count, reported_at, reported_by)`
- 写者:copy-editor (硬编码在 route 层 `_REPORTED_BY`)

**存储**:`ProjectStorage` 通过 `feature_team_storage.apply_team_report(storage, ...)` 调 (UPSERT per agent_name)。

**Audit log**:

- 每次 GET (302 触发):`team view retired -> /projects user_id=X role=Y`
- 每次 POST 401:`team report rejected reason=...`
- 每次 POST 200:`team report applied entries=N reported_by=copy-editor`

**集成**:

- `app/feature_app_factory` 启动 → `ProjectStorage.init_schema()` 自动建表 (DDL idempotent, `agent_team_status` 在 base schema)
- `app/feature_routes.register_routes` 调 `app.register_blueprint(team_bp)` (在 `feature_board_bp` 之后)
