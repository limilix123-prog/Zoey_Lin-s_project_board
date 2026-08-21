# auth

注册 / 登录 / 登出 / session 管理。

管"用户跟系统交互的入口流程",账号存储调 accounts/,鉴权检查调 rbac/。

**特性**:
- `feature_register.py` — GET/POST /register,创建 user(role='user')
- `feature_login.py` — GET/POST /login,验证密码 + 创建 session
- `feature_logout.py` — POST /logout,销毁 session
- `feature_session.py` — server-side session 抽象(sid + user_id + 过期)

**不做**:User 模型 / 密码 hash(在 accounts/)+ 鉴权装饰器(在 rbac/)。
