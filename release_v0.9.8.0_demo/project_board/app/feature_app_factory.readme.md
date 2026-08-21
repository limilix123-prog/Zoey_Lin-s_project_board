# app / feature_app_factory

Flask app 工厂,所有 wire-up 走这里。

- `create_app(config_path=None, *, run_seed=True) -> Flask`
- 启动顺序:加载 config → 初始化 Flask → `UserStorage.init_schema` → 注册 storage 到 `app.config['PB_STORAGE']` → `init_templates` → 跑 `ensure_admin_exists` 首次 seed → `register_routes` 挂路由
- session 配置:`pb_sid` cookie(从 `auth.feature_session.SESSION_COOKIE_NAME` 拉常量, v0.9.7p1 单一 source of truth)+ `HttpOnly` + (生产) `Secure` + `SameSite=Lax`,server-side `sessions` 表做唯一权威
- `run_seed=False` 给测试用,跳过 admin 写库副作用
- 启动异常(配缺失、DB 写不了)立即抛,不静默

**v0.9.7p1 cleanup 删**:
- `utcnow_iso()` (v0.9.5 P0-1/2 留的"暴露给 auth"承诺, 实际 auth 走 `datetime.now(timezone.utc)` in-place, 0 caller) + `__all__` 同步条目
- `from datetime import datetime, timezone` 多余 import 缩到 `from datetime import timedelta`

上游:WSGI 服务器(后续 `python -m project_board` 或 `flask --app ... run`)调。
下游:`accounts/` `rbac/` 各 feature,以及 `feature_routes` / `feature_config` / `feature_templates` / `auth/feature_session` (`SESSION_COOKIE_NAME` import 拉常量)。
