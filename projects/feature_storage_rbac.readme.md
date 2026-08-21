# projects / feature_storage_rbac

v0.7.1 RBAC helpers split-out。Auto-own check + membership cache + rank label formatting 在这里,让 `feature_storage.py` 守 1000 行阈值。

## 4 类 helpers

- **auto-own check** — T0/T1 是否 auto-own 该 project(看 rank 而非 role)
- **membership cache** — `_is_member_via_storage` + `_is_member_cached` + `_invalidate_member_cache` 配合 `ProjectStorage.add_member` / `remove_member` 写后失效
- **db path** — `get_db_path()` 读 Flask `current_app.config` / env / fallback 三段
- **rank label** — `format_rank_label(rank)` Jinja-friendly T-scale 标签 (T0 系统管理员 / T1 平台管理员 / T2 项目负责人 / T3 团队负责人 / T4 普通用户)

所有 helper 是 pure-Python,不碰 SQLite write path。`feature_storage.py` re-export 公开名,callers 可继续 `import feature_storage._is_auto_own` 等,无需 import-site rewrite。

**v0.9.7p1 cleanup 删**:
- `_get_project_role` 整函数(53 行, 0 caller; 函数体 L176 还调了 `storage.get_project_role` 但 `ProjectStorage` 上从未定义该方法, 即使被调会 `AttributeError`)
- `install_role_in_project_check` 整函数(48 行, soft-dead no-op; L519 被调但 body 啥都不做, 纯 INFO 日志噪音)
- 同步 `feature_storage.py:519` `_install_role_in_project_check(conn)` 调用 + 3 个 re-export alias 行 (`_get_project_role` / `_is_member_via_storage` / `get_db_path`)

## Imports

局部 import(在每个需要 `ProjectStorage` 的函数内) — 保留 v0.7.0 用 `ProjectStorage(db_path)` 绕开的 import-time cycle。

## 上游 / 下游

- 上游:`feature_storage` import + re-export
- 下游:`feature_role_v121._resolve_role` + `feature_view` (`format_rank_label`)
