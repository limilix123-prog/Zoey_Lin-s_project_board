# rbac / feature_create_admin

启动时检查 + 无 admin 则用 config 建一个。幂等。

- `ensure_admin_exists(storage, admin_username, admin_password) -> int`
  - 有 admin → 跳过,返回当前 admin 数
  - 无 admin 且 username 没被占 → 用 `hash_password` 建一条 role=admin
  - 无 admin 但 username 已被非 admin 占 → 升级该用户为 admin(避免重复)
- 启动时由 `app/feature_app_factory.create_app(run_seed=True)` 调
- 每次启动都跑;开销一个 COUNT(*),可忽略
- 入参空字符串 → `ValueError`,不静默放过

上游:`app/feature_app_factory` 启动时调。
下游:`accounts/feature_password` 做 hash,`accounts/feature_storage` 写 users 表。
