# accounts / feature_storage

SQLite 抽象层,**所有 DB 写的唯一入口**(7/22 RBAC 业务级 lock 原则)。

- 单文件 DB(`data/project_board.db`),`journal_mode=WAL` + `foreign_keys=ON`
- `threading.Lock` 串行化所有写,免并发 sqlite 撞车
- 表:`users(id, username UNIQUE, password_hash, role, created_at)`、`sessions(sid PK, user_id FK, expires_at)`
- users 接口:`create_user` / `find_by_username` / `find_by_id` / `find_usernames_by_ids` (v0.9.2 sub-task 8 N+1 fix) / `list_all_users` / `count_users_by_role` / `update_role` / `set_rank_by_id` / `set_role_admin` (bootstrap) / `update_password` / `set_username` / `count_admins` / `count_users`
- sessions 接口:`create_session` / `get_session` (过期 lazy delete) / `delete_session`
- 所有 SQL 全部参数化,无字符串拼接,无 SQL 注入面

**v0.9.7p1 cleanup 删**:
- `list_all` (alias of `list_all_users`, 0 caller)
- `get_rank` (0 caller)
- `set_rank` (0 caller — `set_rank_by_id` 是真活写路径, 接受 user_id 不用 username)
- `delete_sessions_for_user` (从未实现, 0 caller)
- `purge_expired` (从未实现, lazy delete 已兜底, 0 caller)

上游:`rbac/feature_create_admin` 首启 seed、`rbac/feature_require_auth` 装饰器读 session、`auth/` 后续模块读写 user。
下游:无(本特性是 storage 唯一所有者)。
