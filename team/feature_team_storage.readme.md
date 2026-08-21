# team / feature_team_storage

`/team/_internal/report` storage primitives — `agent_team_status` UPSERT + per-entry 校验。v0.9.7 删 dead read helpers (见下)。

## 数据 (agent_team_status 表)

| 字段 | 用途 |
|---|---|
| `agent_name` | PK, agent 名 |
| `description` | agent 描述 (自由字符串) |
| `status` | `idle` / `busy` / `blocked` / `offline` (whitelist) |
| `task_count` | 任务数 (非负 int) |
| `reported_at` | 最近一次上报时间 (ISO string, 纳秒精度) |
| `reported_by` | 上报者 (硬编码 `copy-editor` 在 route 层) |

`agent_team_status` 表 DDL 留 `feature_storage._SCHEMA_SQL`,`ProjectStorage.init_schema` 单点建表。本 module 守 1000 行 cleancode 阈值。

## 3 个核心

| Symbol | 作用 |
|---|---|
| `TEAM_STATUSES` | frozenset whitelist (`{idle, busy, blocked, offline}`) |
| `validate_team_entry(entry)` | per-entry 字段校验, raise `ValueError` 整批 reject |
| `apply_team_report(storage, report, reported_by, now_iso=None)` | UPSERT per `agent_name` (ON CONFLICT DO UPDATE) |

## v0.9.7p1 cleanup 删 (dead read helpers, 8/18 user 拍板)

物理删的项 — 本 module **不再提供**, 全文 grep 0 hit:

- `AgentTeamStatusRow` frozen dataclass — 唯一 caller 是 retired `GET /team` handler
- `TEAM_STATUS_DEFAULT` 常量 — 唯一 caller 是 `AgentTeamStatusRow.from_row` default value
- `list_team_status_rows(storage)` — 唯一 caller 是 retired `GET /team` handler
- `__all__` 里以上三项 (从 export 列表清)

写侧 (UPSERT + validation + TEAM_STATUSES) 全保留,copy-editor shared-secret write 端点不受影响。读侧需求由 `team_cleanup_v097p1_20260818.md` 报告里 archive 走历史查询,不重建 read API。

## 上游 / 下游

- 上游:`team/feature_team.submit_team_report` 调 `apply_team_report` (shared-secret auth 后)
- 下游:`projects/feature_storage` 单点建表
