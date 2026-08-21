# projects / feature_list

项目列表端点:GET `/projects`。

**保护**:`@require_auth`。未登录 → 302 → /login。

**流程**:
1. 从 `app.config["PB_CONFIG"]["DB_PATH"]` 构造 `ProjectStorage`(每次请求新建,内部 lock 串行化)
2. 拿 `g.current_user`,`is_admin = user.role == "admin"`
3. 调 `storage.list_visible_to(user, is_admin)` 拿可见项目列表
4. 收集所有 owner_id,批量查 `UserStorage.find_by_id` 拿 username
5. 每项算 viewer_role:`owner_id == user.id` → "owner",否则 "member"
6. description 截前 100 字 + 省略号
7. 渲染 `projects/list.html`

**模板 context**:`items`(list of dict:id / name / description_preview /
owner_username / created_at / viewer_role)、`new_project_url="/projects/new"`、
`is_admin`。

**模板**:`projects/list.html` 继承 `app/templates/base.html`,表格 5 列
(name / description / owner / created / your role);空列表时显示
"No projects yet.";顶部 "New project" 链接到 `/projects/new`。
