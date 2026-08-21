# feature_logout

登出端点:仅 POST /logout 接受(GET /logout 返回 405,防 `<img src="/logout">` 类 CSRF)。

**行为**:
- 从请求 cookie 读 `pb_sid`,调 auth/feature_session.destroy_session 删 sessions 表行
- response.delete_cookie("pb_sid", path="/") 清浏览器 cookie
- 302 跳 `/`(由 app/feature_routes 的 index 路由决定落地 — 已登录跳 /projects,否则跳 /login)

**无 session 也能调**:未登录用户调 POST /logout 是 no-op(没有 sid 就跳过 destroy),直接跳 /。这避免 "未登录但 cookie 还在" 时 500。

**不做**:全设备登出(同 user 跨 session 批量撤销)— 后续 milestone 加 user_id 级清会话。

**v0.9.7p1 cleanup 改**: `GET /logout` handler (L36-39 `reject_get_logout`) 返裸字符串 `"method not allowed"` 改 `abort(405)`, 走 `app/feature_app_factory` 注册的中文 405 错误模板 (`app/templates/errors/405.html`), 跟其他 405 响应统一 (`feature_logout` 不再自带英文 fallback)。
