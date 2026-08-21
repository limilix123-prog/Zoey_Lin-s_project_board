# projects

项目看板核心 — 项目 CRUD + 列表 + 整合主页。

**特性**:
- `feature_storage.py` — ProjectStorage 主类 + projects 表 + project_members 表 + project_features 表 + 9 个 runtime CRUD 方法 (init_schema / create / find_by_id / list_visible_to / list_members / delete / is_member / list_owned_by / list_member_of / list_owned_and_member_counts / update_owner / update / add_member / remove_member / set_member_role)
- `feature_storage_rbac.py` — RBAC 7/22 业务级 lock helpers: get_db_path / _is_auto_own / _is_member_cached / _invalidate_member_cache / format_rank_label
- `feature_storage_migrations.py` — v0.9.2 sub-task 7 role-model migration (_install_role_v091_migration) + _table_exists / _column_exists + _BASELINE_ROLE_NAMES
- `feature_storage_bootstrap.py` — system-project bootstrap chokepoint: _seed_baseline_roles_for_project + create_system_project_if_missing
- `feature_storage_ddl_v092.py` — v0.9.2 DDL fragment (project_nodes / project_custom_roles / project_custom_role_permissions + 5 indexes)
- `feature_storage_features.py` — 4 列 kanban methods (create_feature / list_features / move_feature / delete_feature)
- `feature_storage_nodes.py` — 6-level tree methods (create_node / find_node_by_id / list_children / list_tree / get_tree / update_node / move_node / delete_node)
- `feature_storage_roles.py` — 6 role-grant methods (create_role / list_roles / delete_role / set_role_node_permission / list_role_node_permissions / clear_role_node_permission)
- `feature_list.py` — GET /projects,owner+member 共享 / admin 看 all
- `feature_create.py` — GET/POST /projects/new,建项目(自动 owner=current user)
- `feature_view.py` — GET /projects/<id>,简单详情(name / desc / owner / members / Feature Board 链接)
- `feature_delete.py` — POST /projects/<id>/delete,只 owner/admin 删
- **`feature_me.py`** — GET /me,整合主页(账号 / 改密码 / 我创建的项目 / 我参与的项目)
- **`feature_board.py`** — per-project Feature Board,4 列 kanban (backlog / in_progress / done / archived)

**RBAC**(7/22 业务级 lock):
- 所有写操作走 server 端 ProjectStorage
- `require_owner_or_admin(project, user)` helper 在 server 端拦截
- SQL 直改 = 致命漏洞

**Feature Board (per-project kanban)**:
- 每个 project 自己的 Feature Board (kanban),4 列状态,手动 add / move / delete
- 权限:`can_manage_members` 风格 — owner + admin + manager 写,team_leader / user 只读
- 数据表 `project_features` (FK→projects, ON DELETE CASCADE)
- view.html / system_view.html 加 "View Feature Board" 链接 (can_manage_members 看到)

**不做**:
- Kanban 实际列(To Do / Doing / Done)+ 卡片
- 项目成员邀请 / 管理 UI
- 项目编辑(name/desc 修改)
- 审计日志
