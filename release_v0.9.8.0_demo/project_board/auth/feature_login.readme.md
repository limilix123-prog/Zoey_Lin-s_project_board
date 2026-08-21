# feature_login

登录端点:GET /login 渲染表单,POST 用 accounts/feature_storage.find_by_username
查 user,再用 accounts/feature_password.verify_password(hmac.compare_digest 常数时间比较)
校验密码。成功用 auth/feature_session.create_session 建会话,通过 `pb_sid` cookie 下发。

**响应**:
- 成功 → 302 → `/projects`(若提交时带了合法 `next` 同源路径,跳 next)
- 失败 → 401 + re-render login.html + 通用错误"invalid username or password"
  (不区分 "user 不存在" vs "密码错",避免 username 枚举)

**Cookie 设置**:HttpOnly=True,Secure 按 config,SameSite=Lax,Max-Age = SESSION_LIFETIME_HOURS × 3600。

**不做**:登录失败计数 / 锁定 / 二次验证(后续 milestone)。
