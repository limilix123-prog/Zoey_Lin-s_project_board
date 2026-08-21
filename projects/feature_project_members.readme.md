# projects / feature_project_members

项目成员 add / remove 端点。

**端点**:
- `POST /projects/<int:project_id>/members` — 加 user
- `POST /projects/<int:project_id>/members/<int:user_id>/remove` — 删 user

**保护**:`@require_auth` + server-side `can_manage_members` (7/22 业务级 lock, owner-based)。T0/T1 (auto-own) 永远通过, T2 (project_leader) 仅当 `project.owner_id == user.id` 时通过, T3/T4 永远不通过 → 403。

**v0.7.2a target-rank gate**:
- add: target 是 T0/T1 (auto-own) → 400 "T0/T1 已 auto-own, 无需 add"
- remove: target 是 T0/T1 (auto-own) → 400 "T0/T1 auto-own, 不能 remove"

rank 读 `target.rank`,用 `_is_auto_own()` helper(降级时 fallback 到 legacy `role` string)。7/22 业务 lock:UI 过滤了 T0/T1,server 端 handler 再 hard reject 一次防 hand-crafted POST 绕过。

**Anti-self**(旧规则保留):
- add: `actor.id == target_user_id` → 400 "cannot add self"
- remove: `actor.id == user_id` → 400 "cannot remove self"

**Storage 错误处理**:
- add: composite PK `(project_id, user_id)` 重复 → 302 + `?error=already a project member`
- remove: row 不存在 → 302 + `?error=user is not a member of this project`

成功都 302 → `project_view.show_project(project_id=...)`。

**审计日志**:每次 add 成功 → "project member added project_id=X user_id=Y role=Z";每次 remove 成功 → "project member removed project_id=X user_id=Y"(都从 `ProjectStorage` 内部 log,handler 薄)。
