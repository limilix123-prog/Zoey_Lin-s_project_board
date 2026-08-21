# feature_session

Server-side session 抽象,sid 用 time.time_ns() + secrets.token_urlsafe 生成,
DB 写入与查询走 accounts/feature_storage 的 sessions 表。

**接口**:
- `create_session(user_id) -> sid` — 建会话,落 sessions 表,返回 sid
- `get_session(sid) -> user_id | None` — 查会话;过期 / 不存在 / 格式错一律返回 None
- `destroy_session(sid) -> None` — 删会话,幂等

**常量**:
- `SESSION_COOKIE_NAME = "pb_sid"` — 浏览器 cookie 名。**v0.9.7p1 single source of truth**:
  本模块是唯一 owner;`rbac/feature_require_auth` + `app/feature_app_factory` 都从
  这里 import 常量, 任何 rename 自动传播, 不再需要 3 处手改同步。

**不做**:User 模型(accounts/)+ 密码 hash(accounts/)+ 鉴权装饰器(rbac/)+ HTTP 视图(本模块不绑 route,视图函数自己读 / 写 cookie)。
