# projects / feature_edit

项目级 name + description 编辑端点(v0.9.1 sub-task 2 完整权限设计引入)。

**端点**:
- `GET  /projects/<int:project_id>/edit` — 渲染编辑表单
- `POST /projects/<int:project_id>/edit` — 校验 + `ProjectStorage.update()` + 重定向

**保护**:`@require_auth` + server-side `can_manage_members` (7/22 业务级 lock)。未登录 → 302 → /login;非 admin/manager + 非 owner → 403(不泄露存在性给非 owner 的 member,但 project 不存在返回 404)。

**7/22 RBAC chokepoint**:
handler **永远** 走 `ProjectStorage.update()`,不直接 SQL 也不接受 `owner_id` / `project_type` 字段。Hand-crafted POST 想塞这两个字段会被静默丢弃(storage 方法的参数列表根本不包含它们,route 层也不读)。

**system project 守门**(额外):
`is_system == True` 的项目即使 admin 也不能改 — 平台 self-status 项目名永久。`abort(403, "system project is permanent")`。

**v0.9.1 3-bucket 矩阵的"非 settings"版本**:
- 跟 `feature_settings` 区别:本端点走 `can_manage_members`(v0.7.x legacy 规则),settings 端点走 3-bucket `_resolve_role`(`_BUCKET_AUTO_OWN` / `_BUCKET_OWNER`)。
- 两端点都能改 name + description,UI 上 edit 是"快速改",settings 是"完整 self-contained 页面"(sub-task 4 Issue 3 后 settings 不再含 change owner)。

**Form contract**:
- `name` — 必填,≤ 200 字符,UNIQUE 约束
- `description` — 选填,≤ 4000 字符
- 重复 name → `sqlite3.IntegrityError` → 400 + `error=project name taken`
- 空 name / 超长 → 表单 re-render + 错误

**流程**:
1. 拿 `g.current_user` + `ProjectStorage.find_by_id(project_id)`
2. `_check_can_edit(user, project)` — system project 403,非 manage 403
3. 拉 form data(trim,storage 层 re-validate)
4. 校验 name / description 长度
5. `storage.update(project_id, name, description)` — 7/22 chokepoint
6. 成功 → 302 → `project_view.show_project`;失败 → 表单 re-render + 错误

**字段常量**(`_NAME_FIELD` / `_DESCRIPTION_FIELD` / `_NAME_MAX` / `_DESCRIPTION_MAX`):
跟模板 `projects/edit.html` 同步,grep `_FIELD_` / `_MAX` 找到所有 form 读写点。

**上游**:`app/feature_routes.register_routes` 注册 `project_edit_bp`(v0.9.1 sub-task 1)。
**下游**:`ProjectStorage.update`(7/22 chokepoint);`projects/edit.html` 模板。
