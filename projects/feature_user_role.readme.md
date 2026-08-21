# projects / feature_user_role

`POST /users/<int:user_id>/rank` 端点 — 改另一个 user 的 T-scale rank。

## RBAC 矩阵(`_can_change_rank`)

| Actor | 可设 target | 禁设 |
|---|---|---|
| admin (T0) | T1, T2, T3, T4 | T0, self |
| manager (T1) | T1, T2, T3, T4 | T0, self |
| project_leader (T2) | T3, T4 | T0, T1, T2, self |
| team_leader (T3) | T4 | T0, T1, T2, T3, self |
| user (T4) | (无) | (always) |

## Hard 规则

- **T0 永久** — admin (T0) 不能通过该端点设。`set_rank_by_id` 是 direct write,但 route 拒 T0。T0 唯一来源是 bootstrap seed (`ensure_admin_exists`)
- URL 接受 int 或 string(string 走 reverse lookup)

## 上游 / 下游

- 上游:`feature_users_list` + `feature_user_view` 模板 form
- 下游:`accounts/feature_storage.set_rank_by_id` (v0.9.2 sub-task 3 rank-based write chokepoint; v0.9.7p1 cleanup 删 `set_rank` 死方法, 此端点改用 `_by_id` 版本)
