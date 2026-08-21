# team

Team module — 仅 `POST /team/_internal/report` 写端点(copy-editor 上报 agent 状态,shared secret 认证);`GET /team` 已在 v0.9.7 退役(302 → /projects)。

## 2 个 feature

| feature | 端点 | 用途 |
|---|---|---|
| `feature_team` | `POST /team/_internal/report` | copy-editor 推一批 agent row 进 `agent_team_status` |
| `feature_team_storage` | (无端点,storage) | `apply_team_report` (UPSERT) + `validate_team_entry` (per-entry 校验) + `TEAM_STATUSES` (whitelist) |

`GET /team` handler 在 `feature_team.show_team` 仍保留 — 命中后 302 → /projects(为了 7/17 self-contained:不留 404 dead-end)。

## 数据流

```
agent (周期性)
  POST /team/_internal/report (X-Copy-Editor-Secret header)
  → feature_team.submit_team_report
  → feature_team_storage.apply_team_report (UPSERT)
  → agent_team_status 表

user (浏览器)
  GET /team
  → feature_team.show_team (auth + redirect)
  → 302 → /projects
```

`agent_team_status` 表 DDL 在 `feature_storage._SCHEMA_SQL`(单点建表),`feature_team_storage` 守 1000 行 cleancode 阈值。

## RBAC

- `GET /team` — `require_auth` + 302 → /projects(v0.9.7 退役)
- `POST /team/_internal/report` — shared secret 在 header 校验,不走 session(agent 不登录)

## 上游 / 下游

- 上游:`app/feature_routes.register_routes` 注册 `team_bp`
- 下游:`projects/feature_storage` 单点建表
