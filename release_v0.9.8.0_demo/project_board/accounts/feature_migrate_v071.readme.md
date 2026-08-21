# accounts / feature_migrate_v071

v0.7.1 data model migration。Auto-run on app start,idempotent。

## 4 步

| 步 | 动作 | idempotent 守门 |
|---|---|---|
| 1 | `users.rank` 列加(若缺) | DDL `IF NOT EXISTS` 模式 + `UserStorage.init_schema` 同样跑一遍(已加的 no-op) |
| 2 | `users.rank` 从 legacy `role` 列 backfill | 只 backfill 仍为 DEFAULT 4 sentinel 的行 + role 在 5 个 v0.7.0 names 之内 |
| 3 | `users.role` 从 `users.rank` 同步 | 同 step 2 的 "only if stale" 守门 |
| 4 | `project_members.role_in_project = 'member'` → `'user'`(T4) | v0.7.0 'member' literal 在 v0.7.1 模型里无对应,改 user(T4) |

migration 不删行 — T0/T1 即使出现在 `project_members`(v0.7.0 允许 admin/manager 是普通 member)也不动,v0.7.2 endpoint rewrite 才是清理点。

每个 step 一行 INFO log,`project_board.*` logger tail-grep 即可确认。

## 上游 / 下游

- 上游:`feature_app_factory.init_storage`(首启自动调)
- 下游:无(独立 migration pass)
