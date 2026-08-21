# projects / feature_users_list

`GET /users` 端点。User directory,每个登录用户都可见全部账号。

## 端点

- `GET /users` — 渲染 user directory(每行 → /users/<id> 详情)

## RBAC

`require_auth` 拒未登录用户;每个登录 user 都到得了页面。"Change rank" form 模板内由 `can_change_rank` + `available_new_ranks` gate:plain user 看不到 form,admin target / self 也隐藏。

`POST /users/<id>/rank` 写路径在 `feature_user_role` rank-gated 在 TEAM_LEADER,plain user 即使到达 /users 也不能 promote/demote。

## 上下文

模板得:`users`(list)、`can_change_rank`(bool)、`available_new_ranks`(list[int])、`project_counts_owned_by` + `project_counts_member_of`(per-user counters, v0.9.2 sub-task 8 N+1 fix)。

## 上游 / 下游

- 上游:`app/feature_routes.register_routes` 注册
- 下游:`accounts/feature_storage` 读 users 表
