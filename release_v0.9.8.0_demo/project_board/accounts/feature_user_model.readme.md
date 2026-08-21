# accounts / feature_user_model

User 数据类(id / username / password_hash / role / created_at)。

- 不可变 dataclass(`frozen=True`),防止调用方原地改 user 记录
- `from_row()` 从 sqlite3 Row 构造,`to_dict()` 用于 JSON 序列化
- 不做 IO、不做 hash、不调 storage;只表达"一个 user 长什么样"

上游:`accounts/feature_storage.py` 读 sqlite 行后用它包成对象。
下游:`rbac/feature_require_auth.py` 和后续 `auth/` 模块用 `current_user` 属性。
