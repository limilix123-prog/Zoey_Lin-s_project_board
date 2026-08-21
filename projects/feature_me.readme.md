# projects / feature_me

整合主页端点:GET `/me`。

**保护**:`@require_auth`。未登录 → 302 → /login?next=/me。

**流程**:
1. 拿 `g.current_user`
2. 调 `ProjectStorage.list_owned_by(user.id)` 拿"我创建的项目"
3. 调 `ProjectStorage.list_member_of(user.id)` 拿"我作为 member 参与的项目"(SQL
   内 `AND p.owner_id != ?` 排除 owner 自己)
4. 合并 owner_id 集合,批量调 `UserStorage.find_by_id` 拿 username(走
   `owner_username_lookup` 共享 helper)
5. 投影成 `owned_projects` / `member_projects` 列表(走 `build_project_items` 共享 helper)
6. 读 `?changed=1` query → `notice = "Password updated."`(给改密码成功后的
   跨页通知用,无 flash 队列)
7. 渲染 `projects/me.html`

**模板 context**:
- `user` — User 对象(已 re-read storage,反映密码 / role 并发变更)
- `owned_projects` / `member_projects` — list of dict(id / name / description_preview / owner_username / created_at)
- `change_password_url` = `"/profile/password"` — 改密码表单 action(端点 URL 保留)
- `logout_url` = `"/logout"`
- `new_project_url` = `"/projects/new"`
- `notice` / `error` — 任一为 None 即不显示

**模板**:共享 `projects/templates/projects/me.html` (v0.9.7p1 从 `app/templates/` 迁入),4 块 self-contained,层级靠
`<h2>` + `<ul>` / `<dl>`,**不**用卡片 / 边框 / 阴影 / 徽章(用户 UI 原则:
"页面要 self-contained,层级靠 padding-left / h2 / h3")。

**共享 helper**:
- `build_project_items(rows, owner_names)` — 投影 ProjectRow → me.html dict,
  `feature_change_password` 失败渲染 me.html 时复用
- `owner_username_lookup(user_ids)` — 批量查 owner username,同上

**上游**:`app/feature_routes.register_routes` 注册 me_bp。
**下游**:`ProjectStorage.list_owned_by` / `list_member_of` / `UserStorage.find_by_id`;
`projects/me.html` 共享模板;`profile/feature_change_password` 失败 re-render 同模板。
