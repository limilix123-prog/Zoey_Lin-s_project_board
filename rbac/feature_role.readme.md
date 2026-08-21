# rbac / feature_role

角色常量 + 纯函数检查 helper。无 IO,无装饰器。

- 常量:`USER` / `TEAM_LEADER` / `PROJECT_LEADER` / `MANAGER` / `ADMIN` 5 个 role string
- 已知角色集合 `_KNOWN_ROLES = frozenset({USER, TEAM_LEADER, PROJECT_LEADER, MANAGER, ADMIN})`,加新 role 改两行
- rank 表 `_RANK_FOR_ROLE` (T0=admin .. T4=user, lower wins)
- 严格相等 helper:`is_admin(user)` / `is_manager(user)` / `is_project_leader(user)` / `is_team_leader(user)` / `is_known_role(role)`
- 等级比较 `_role_at_least(user, required)` — 7/22 RBAC 业务 lock 的单一 source of truth
- 互转:`rank_for_role(role)` / `role_for_rank(rank)`
- 全部纯函数,易测;装饰器在 `feature_require_auth.py`,seed 在 `feature_create_admin.py`

**v0.9.7p1 cleanup 删**:`is_user` / `role_rank` / `role_check` 3 个死函数 + `__all__` 同步条目。
- `is_user` (T4 严格相等) — 0 caller, T4 业务上无对应权限场景
- `role_rank` (role string → rank int) — 跟 `rank_for_role` 重复,后者真活
- `role_check` shim — 自述 "backwards-compat" 但无 shim caller, `_role_at_least` 已是 source of truth

上游:被 `feature_require_auth.py` 和 `feature_create_admin.py` 用。
下游:无。
