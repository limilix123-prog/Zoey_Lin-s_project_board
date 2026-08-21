# projects / feature_user_view

`GET /users/<int:user_id>` 端点。Read-only per-user detail:账号 + 创建项目 + 项目 member 关系。

## 端点

- `GET /users/<id>` — 渲染 user detail 页(含 "Change rank" form 给可改 rank 的 actor)

## RBAC

- Read:每个登录 user 都可达(匿名跳 /login)
- "Change rank" form 由 `_can_change_rank` + `_available_new_ranks` whitelist 控。Plain user 看不到 form,只 `(read-only)` placeholder。Self / admin target 隐藏 form(server-side anti-self / anti-admin)
- POST 写路径在 `feature_user_role`,rank-gated 在 TEAM_LEADER,plain user 即使到 /users/<id> 也不能改 rank

Anti-self / anti-admin 模板隐藏 + server-side 拒绝双层守门。Non-existent user_id 返 404 不 403(避免 leak existence to 任何 viewer)。

## 上游 / 下游

- 上游:`app/feature_routes.register_routes` 注册
- 下游:`accounts/feature_storage` + `projects/feature_storage.list_owned_and_member_counts`(v0.9.2 N+1 fix)
