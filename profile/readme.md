# profile

用户改密码端点模块。

**当前特性**:
- `feature_change_password.py` — POST `/profile/password`,验证旧密码 + 改新密码(pbkdf2 重 hash)

**不做**:
- 用户名修改
- 头像 / 邮箱
- active sessions 列表
- 强制登出其他设备
