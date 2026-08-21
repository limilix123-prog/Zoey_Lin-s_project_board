# feature_register

自助注册端点:GET /register 渲染表单,POST 校验后用 accounts/feature_password
hash 密码,调 accounts/feature_storage.create_user(role='user') 建号,成功跳 /login。

**校验**:
- username:1–64 字符(去前后空格),unique
- password:1–1024 字符 (不限强度)

**错误返回**:
- 校验失败 → 400 + re-render register.html + 错误文案
- username 重复(sqlite3.IntegrityError)→ 409 + re-render + "username already taken"

**重定向**:成功 → 302 → `/login?registered=1`,由 login.html 显示"account created"提示(避免依赖 base.html flash block)。

**不做**:邮件验证 / 验证码 / admin 邀请码(后续 milestone)。
