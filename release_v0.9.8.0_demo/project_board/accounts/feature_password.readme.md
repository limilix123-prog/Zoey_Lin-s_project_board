# accounts / feature_password

密码 hash / verify,stdlib `hashlib.pbkdf2_hmac`,无三方依赖。

- 每次 hash 用 `secrets.token_bytes(16)` 生成随机 salt
- 存储格式 `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`,自描述,以后升 iterations 不破旧行
- verify 用 `hmac.compare_digest` 做常数时间比较,防时序攻击
- 输入校验:空密码 / 非字符串 → `ValueError`;畸形 stored hash → `False`(不抛)

上游:被 `accounts/feature_storage.create_user` 的调用方、`auth/` 模块登录流程使用。
下游:无。
