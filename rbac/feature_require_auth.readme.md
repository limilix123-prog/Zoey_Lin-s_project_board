# rbac / feature_require_auth

鉴权装饰器,基于 server-side session cookie(`sid`)+ storage 查 user。

- `@require_auth` — 必须登录,未登录跳 `/login`(或 JSON 请求返 401)
- `@require_role('admin')` — 必须有指定 role,未登录跳 `/login`,权限不足 403
- 从 `request.cookies['sid']` 读 sid → `storage.get_session(sid)` → `storage.find_by_id(user_id)` 拿 user
- 注入 `flask.g.current_user` 给 view 用
- 装饰器会拒绝未知 role 的 `require_role(...)` 调用 → `ValueError`(开发期就崩,不当 silent pass)
- 日志记录所有 RBAC deny,便于审计

上游:被后续 `auth/`、`rbac/` 的 routes 用来保护 view。
下游:`accounts/feature_storage` 查 session/user,`rbac/feature_role` 做 role 判断。
