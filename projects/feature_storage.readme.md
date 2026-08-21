# projects / feature_storage

SQLite 抽象层,管 `projects` + `project_members` 两表。**所有 DB 写的唯一入口**(7/22 RBAC 业务级 lock 原则)。

**类**:
- `ProjectRow` — frozen dataclass(id / name / description / owner_id / created_at / updated_at)
- `ProjectStorage` — 线程安全包装,`threading.Lock` 串行化所有写

**与 accounts/feature_storage 关系**:
- 共享同一个 SQLite 文件(`data/project_board.db`)
- 不继承、不包装,各自管自己的表(7/22 模块化)
- `list_members` 用 SQL JOIN 读 `users.username`(只读,写仍走 UserStorage)

**Schema**:
- `projects(id, name UNIQUE, description, owner_id FK→users.id, project_type, created_at, updated_at)`
- `project_members(project_id, user_id, role_in_project, added_at)` — 复合 PK,project_id 上 `ON DELETE CASCADE`
- **`project_features(id, project_id FK→projects.id ON DELETE CASCADE, name, description, status, position, created_at, updated_at)`** — Feature Board 行;`status` 白名单 `backlog` / `in_progress` / `done` / `archived`
- 索引:`idx_projects_owner(owner_id)`、`idx_members_user(user_id)`、`idx_features_project_status(project_id, status, position)`

**接口**:
- `init_schema()` — DDL idempotent (含 project_features 表 + index)
- `create(name, description, owner_id) -> int` — 重名 raise `IntegrityError`
- `find_by_id(project_id) -> Optional[ProjectRow]`
- `list_visible_to(user, is_admin) -> list[ProjectRow]` — admin 看 all,user 看 own + member
- `list_members(project_id) -> list[(user_id, username, role_in_project, added_at)]`
- `delete(project_id) -> bool` — `ON DELETE CASCADE` 带走 project_members + project_features
- `is_member(project_id, user_id) -> bool` (v0.9.7p1 cleanup: `count_members` / `count_all` / `get_member_role_id` 3 死方法删)
- **`list_owned_by(user_id) -> list[ProjectRow]`** — 拿 user 创建的所有项目;`/me` 第 3 块用
- **`list_member_of(user_id) -> list[ProjectRow]`** — 拿 user 作为 member 参与的项目,SQL 内 `AND p.owner_id != ?` 排除 own 避免双显;`/me` 第 4 块用
- **`create_feature / list_features / move_feature / delete_feature`** — Feature Board CRUD;move / delete 带 `AND project_id = ?` 跨项目保护

**RBAC helpers**(模块级函数):
- `user_can_see_project(user, project, is_admin) -> bool` — 读侧
- `require_owner_or_admin(user, project, is_admin) -> None` — 写侧,raise `PermissionError`

**上游**:`app/feature_app_factory` 启动 init;`projects/feature_list` / `feature_me` 渲染列表;`feature_create` / `feature_view` / `feature_delete` 调 `create` / `find_by_id` / `delete`。
