# projects / feature_delete

删除项目端点。**只接受 POST**(`/projects/<int:project_id>/delete`),防 CSRF 和意外 GET。

**保护**:`@require_auth` + server-side `require_owner_or_admin` (7/22 业务级 lock)。

**流程**:
1. 拿 `g.current_user` + `ProjectStorage.find_by_id(project_id)`
2. 项目不存在 → abort(404)
3. `require_owner_or_admin` raise `PermissionError` → abort(403)
4. 调 `ProjectStorage.delete(project_id)` → `ON DELETE CASCADE` 清 `project_members`
5. 302 → `projects_list.show_projects` (回列表)

**写权限**:
- admin → 允许
- owner (`project.owner_id == user.id`) → 允许
- 其他 → PermissionError → 403

**日志**:成功 → `project deleted id=X by user_id=Y`;失败 → `project delete denied user_id=X project_id=Y (403)`。
