# accounts

User 数据模型 + 密码 hash + SQLite 存储层。

管"账号是什么"和"账号怎么存",不管"账号怎么用"(鉴权在 auth/ 模块)。

**特性**:
- `feature_user_model.py` — User dataclass / TypedDict
- `feature_password.py` — 密码 hash / verify(用 pbkdf2 或 scrypt,stdlib)
- `feature_storage.py` — SQLite 抽象(crud + 表 schema)

**不做**:session 管理(session 在 auth/)+ 鉴权装饰器(在 rbac/)。
