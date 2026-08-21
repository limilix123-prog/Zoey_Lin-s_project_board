# project_board

> 有鉴权的项目管理系统 · Python Flask · workspace 单机

## v0.9.8.0 milestone (2026-08-20 user 拍板升版, v0.9.7 阶段拍板 + 3 agent audit 提议修)

**scope — 4 批 + 3 sub-stage (2026-08-19 ~ 8/20)**:

| 批 | worker | 范围 | 报告 |
|---|---|---|---|
| 1 | bg_785e29bb (explore) → verifier 1 | 8/19 verifier coverage audit: 26 候选 dead code + 11 P2 + 1 latent bug | `dead_code_scan_v097p1_2026-08-18.md` |
| 2 | 3 worker (6a729717 / 3e798ab1 / dcb9c7d1) | 8/19 三批补 62 smoke case (v070 P0 30 / v071 P1 21 / v072 P2 11) | `smoke_v070/071/072_audit_v097p1_2026-08-19.md` |
| 3 | 3 agent (explore / worker / verifier) | 8/19 18:42 试 sub-agent 系统能力: explore 出 v0.9.8 调研报告, worker 实现 `/api/v1/system/status` 端点 + 1 新 smoke, verifier 出 7/17+7/22 守门深度 audit (459 行) | `explore_v098_potential_2026-08-19.md` / `worker_trial_v098_api_status_2026-08-19.md` / `verifier_guardian_audit_v0971_2026-08-19.md` |
| 4 | bg_5d44027e (worker) + bg_ed4744de (worker) | 8/20 silent drift 修 + 8 P1 smoke (v074) + copy-editor v0.9.8.0 milestone 上报 | `smoke_v074_audit_v098_2026-08-20.md` / `copy_editor_report_v0980_2026-08-20.md` |

**总产物 (v0.9.7 阶段拍板, 含 8/19 + 8/20 全部 dev work)**:
- 8/19 三批补 62 smoke case (P0 30 / P1 21 / P2 11, 全部 1 行为 = 1 spec, 7/15 守门)
- 8/19 verifier audit 找 3 agent 试系统能力 (explore / worker / verifier 0 conflict 跑通)
- 1 new endpoint: `GET /api/v1/system/status` (read-only JSON, 0 副作用)
- 8/20 silent drift 修: `feature_storage_nodes.py:54` `MAX_NODE_LEVEL` 跟 `feature_board.py:79` lazy import helper 重复, 改顶部 import `_MAX_NODE_LEVEL` (消除 silent drift 风险)
- 8 P1 smoke (v074, verifier 提议 8/8 全补, 0 hit 显式测):
  - 7/22 smuggle grant 防御 (v0.9.3 dropped `/members/<uid>/permissions` → 404 stub)
  - 7/22 system project 跨 4 端点完整守门 (delete / change-owner / owner / edit)
  - 7/22 5x5 rank matrix 完整 100 组合 chokepoint 真值 + 4 守门
  - 7/22 7 端点 hand-crafted 错 cookie 注入 (require_auth 兜底)
  - 7/22 legacy member add 9 边界 case (self/ghost/dup/admin/system/method/cross-project/path/empty)
  - 7/17 /settings 1 form 1 page + 7/22 owner_id 注入
  - 7/17 /me 4 块 self-contained (账户/更改密码/我的项目/我参与的项目)
  - 7/17 /board 6 层 tree 缩进表达 (padding-left × level)
- copy-editor `/team/_internal/report` 上报完成: 8/20 00:1x worker bg_ed4744de 跑通, 5 agent row UPSERT
- 7/17 + 7/22 守门深度 audit: **7/17 PASS** (20 page 100%), **7/22 PASS** (27 写端点 100%)

**v0.9.8.0 升版 gate (8/4 教训 — 必查产物 LastWriteTime)**:
- 12 smoke **389/389 PASS** (v032 49 + v053 46 + v054 32 + v055 31 + v056 21 + v061 43 + v062 51 + v070 34 + v071 21 + v072 51 + v073 1 + v074 9)
- Flask healthz 200 (**50 routes** — 49 旧 + 1 new `/api/v1/system/status`)
- cleancode **1 violation** 残留 (`feature_storage.py` 1051 行 > 1000 cap, user 8/18 19:58 拍"接受", v0.9.8.0 沿用)
- `import project_board` OK, 0 active dead code
- 7/17 + 7/22 + 7/31 守门深化 (8 P1 case 全过, 0 P0 缺口)
- 升版产物: `history/release_v0.9.8.0.zip` (v0.9.8 阶段发版快照)
- copy-editor `/team/_internal/report` 上报完成: 8/20 00:1x bg_ed4744de 跑通, 5 agent row UPSERT

**v0.9.8 阶段 4 项挂账(下个窗口消化)**:
1. `feature_storage.py` 1051 行 `file_too_long` violation (user 接受, 长期)
2. 13 份 `_storage` helper boilerplate (架构债, user 8/18 19:58 拍"不管")
3. 14 pre-existing `comment_block_too_long` 仍可能存在 (挂账 3, 跨多文件)
4. ad-hoc verifier `_admin_perspective_check.py` + `_sanity_check.py` (test/ 下次清理)

**v0.9.8 阶段不做的业务方向 (推 v0.9.9+ / v1.0.0+)**:
- 审计日志 (1-2 day, 7/22 业务 lock 改 8+ chokepoint, 推 v0.9.9)
- 多用户协作 (2-3 day, 7/17 难守, 推 v1.0.0+)
- 密码重置 + 邮箱验证 (需 user 拍 7/28 第三方依赖, 推 v0.9.9)
- 项目模板 + clone (1.5-2 day, 推 v0.9.9)
- perf 进一步降 (3 endpoint 30% target, 需换框架, 不推荐)

**硬约束(守住的)**:
- 不动 `demo_pptx/` (独立 Node.js 项目, 8/20 20:00 migrate 到 workspace 根, 不在 project_board/ 下)
- 不动 `test/` 7 smoke 之外的脚本 (cleancode scope 外, AGENTS.md L89)
- 不动 v0.9.3 拍板保留的 404 stub 端点 (`feature_members_page.py:741, 754`)
- 不动 14 `history/release_*.zip` (发版产物, 8/4 教训)
- 7/17 + 7/22 守门跟 v0.9.7 阶段一致 (没破)

---

## v0.9.7.0 milestone (2026-08-18 user 拍板升版, 从 v0.9.7p1 cleanup patch 拍板)

**scope — 8 批 worker 跑完 (2026-08-18)**:

| 批 | worker | 范围 | 报告 |
|---|---|---|---|
| 1 | c778ff05 | team 模块 dead code (4 函数 + team.html 删) | `team_cleanup_v097p1_20260818.md` |
| 2 | bg_785e29bb (explore) | 全 project_board/ dead code 扫描 (26 候选 + 11 P2 + 1 bug) | `dead_code_scan_v097p1_2026-08-18.md` |
| 3 | 93b324c1 | `feature_storage.py:424` latent NameError 修 | `feature_storage_v091_nameerror_fix_2026-08-18.md` |
| 4 | 6a729717 | Pass 1 死代码删 (26 标识符) + P2 #1-4 #6-9 + Pass 2 readme 同步 | `cleanup_pass2_v097p1_2026-08-18.md` |
| 5 | ac8d3b18 | 5 bug 修 (P0 `feature_list.py:93` `user.role` → `_role_at_least`) + 1 CSS dead code + history 整合 | `cleanup_pass3_v097p1_2026-08-18.md` |
| 6 | 3e798ab1 | 14 pre-existing `comment_block_too_long` 缩到 5 行内 | `comment_refactor_v097p1_2026-08-18.md` |
| 7 | dcb9c7d1 | `feature_storage.py` 1382 → 1084 行,拆 2 块 (migrations + bootstrap) | `feature_storage_split_v097p1_20260818.md` |
| 8 | 4ca4e1e4 | 5 新增 comment violation + 22 处 double-blank 消 | `comment_refactor_v097p1_pass2_2026-08-18.md` |

**总产物**:
- 21 dead 标识符删 + 1 整模块 (`rbac/feature_storage.py`) + 1 整 `home/` 目录删
- 3 re-export alias 删
- 1 CSS dead code 段 (3 var + 3 selector)
- 19 个 `comment_block_too_long` 段缩/转
- 22 处 double-blank 消
- 6 个 readme 同步 (rbac / app / project_board / projects / auth / team)
- 1 整 `feature_storage.py` 拆 2 块 (`feature_storage_migrations.py` 236 行 + `feature_storage_bootstrap.py` 219 行)
- 12 archived entry 整合成 1 bundle zip (2.80 MB)
- ~700 行 .py 减, ~50 行 CSS 减
- 1 P0 latent bug 修 (`feature_list.py:93`, v0.9.2+ 永 `is_admin_or_manager=False`)

**v0.9.7.0 升版 gate (8/4 教训 — 必查产物 LastWriteTime)**:
- 7 smoke **273/273 PASS** (v032 49 + v053 46 + v054 32 + v055 31 + v056 21 + v061 43 + v062 51, 实跑验证)
- Flask healthz 200 (**49 routes**, 从 50 砍 /home 整删, 加 2 个新 storage 子模块无新路由)
- cleancode **1 violation** 残留 (`feature_storage.py` 1051 行 > 1000 cap, user 8/18 19:58 拍"接受 1084 行,正常代码应该不至于")
- pb_sid 字面量 **1 处** (`auth/feature_session.py` 是 single source, 从 3 处去重)
- 22 modules import OK, 0 active `--color-perm-*` / 0 `.status-(read|write|admin)` (CSS dead)
- admin 视角 `/projects` 验证: admin / manager 看 1 (seed system), alice (T4) 看 0 — Bug 1 fix PASS
- 升版产物: `history/release_v0.9.7.0.zip` (v0.9.7 阶段发版快照)
- copy-editor `/team/_internal/report` 上报完成: 8/18 20:1x worker bg_8f8fd22a 跑通, 5 agent row UPSERT

**4 项挂账(下个窗口消化 + 长期挂账)**:
1. `feature_storage.py` 1051 行 `file_too_long` violation (user 接受, 长期)
2. ad-hoc verifier `_admin_perspective_check.py` + `_sanity_check.py` (test/ 下次清理)
3. 14 pre-existing `comment_block_too_long` 仍可能存在 (`feature_board.py` 等, worker 2 漏 1 段)
4. demo_pptx 引用 `/home` (long-term, user 8/18 19:58 拍"等做满意项目再处理 ppt", 8/20 20:00 migrate 到 workspace 根)

**硬约束(守住的)**:
- 不动 `demo_pptx/` (独立 Node.js 项目, 8/20 20:00 migrate 到 workspace 根, 不在 project_board/ 下)
- 不动 `test/` 7 smoke 之外的脚本 (cleancode scope 外, AGENTS.md L89)
- 不动 v0.9.3 拍板保留的 404 stub 端点 (`feature_members_page.py:741, 754`)
- 不动 `team/` 模块 .py (batch 1 done, 只改 `feature_team_storage.readme.md`)
- 不动 14 `history/release_*.zip` (发版产物, 8/4 教训)
- 不动挂账 4 (13 份 `_storage` helper boilerplate, 架构债 user 8/18 19:58 拍"不管")

---

## v0.9.3 (patch 上一段, 2026-08-13 user 拍板升版)

**v0.9.3 patch 范围 — 1 段 5 sub-tasks (user 8/13 19:34 拍, 删 user-level 节点权限整套)**:

| # | sub-task | 改动 |
|---|---|---|
| 1 | 删 DB schema | `project_node_permissions` 表 + `idx_node_perms_node_user` 索引从 DDL fragment 移除 (不 install); `feature_migrate_v092` Step 2 砍 |
| 2 | 删 storage 整套 | `feature_storage_node_permissions.py` + `.readme.md` 物理删 (走回收站); 3 个 `_do_*` helpers (grant/revoke/list) 跟着没 |
| 3 | 改 RBAC 走 role 路径 | `feature_role_v121`: `grant_node_action` 4th chokepoint 删; `_has_node_grant` 改 `_has_node_role_grant` (走 `project_custom_role_permissions` JOIN `project_members`); `_BUCKET_PER_NODE` 改名 `_BUCKET_ROLE_GRANT`; `add_member_action` 内部 import 删 (dead code); `feature_role_v121_ddl.py` + `_cascade.py` + `.readme.md` 物理删 (引已删表, 无 caller) |
| 4 | 删 UI 段 | `members.html` 删 "Per-(user, node) permissions" 表 + "Permissions" 链接 (Actions cell); `node_permissions.html` 转 role view (改名 "Role permissions for <node>", 模板无人调但保留 reference); `/projects/<id>/members/<uid>/permissions` GET + POST 端点删 (改 404 stub, stale bookmark 给信号 + 7/22 RBAC 端点删 = storage 写端无 caller) |
| 5 | 验证 | 7 smoke 273/273 PASS; Flask import 47 routes (从 49 砍 2); 所有 .py 还能 parse |

**v0.9.3 升版 gate (8/4 教训 — 必查产物 LastWriteTime)**:
- 7 smoke 273/273 PASS (v032 49 + v053 46 + v054 32 + v055 31 + v056 21 + v061 43 + v062 51, 实跑验证)
- Flask healthz 200 (47 routes, 从 49 砍 2 = 删 `/projects/<id>/members/<uid>/permissions` GET + POST)
- 6 文件物理删 (走回收站): `feature_storage_node_permissions.py/.readme.md`, `feature_role_v121_ddl.py/.readme.md`, `feature_role_v121_cascade.py/.readme.md`
- pre-v0.9.3 DB 上 `project_node_permissions` 表保留 (0 行实际数据, 7/22 业务级 lock 禁 silent DELETE)

**详细 changelog**: `history/release_notes.md` (v0.9.3 段)

---

## v0.9.2 (2026-08-13 user 拍板升版)

**v0.9.2 patch 范围 — 8 sub-tasks (user 8/13 07:23 拍)**:

| # | sub-task | 改动 |
|---|---|---|
| 1 | WAL toggle + FK rebuild | `PRAGMA journal_mode=DELETE` 临时关 WAL 跑 migration; 4 步 FK rebuild (sessions 空 / projects 3 / project_features 1 / project_nodes 20 / project_node_permissions cascade) |
| 2 | users.role → NULL | 12-step migration 清空 legacy `users.role` 字段; 5 步 (backup / column add / role 字符串拼接 / idx 加 / verify) |
| 3 | Full RBAC 迁 rank | `user.rank` 取代 `user.role` 鉴权; `_role_at_least(user, required)` 取代 `role_check`; 9 feature_*.py 改完; URL 路径保留 `/users/<id>/role` 接受 int 或 string |
| 4 | UI polish | change rank dialog inline `font-size: var(--text-sm); padding: 2px 6px/8px`; new project / change owner form 同款 + dropdown display 改 `T{{ u.rank }}` (3 处) |
| 5 | P1 board 内容 | seed P1 6-level node tree (29 nodes: 3 L1 + 7 L2 + 12 L3 + 7 L4) with descriptions |
| 6 | Custom role flow | 6 端点 (create/list/show/delete role + grant perm + assign member); 2 表 (`project_custom_roles` + `project_custom_role_permissions`); UI custom_roles.html + custom_role.html |
| 7 | Role + Custom role merge | DDL: drop `project_role_permissions` + rebuild `project_members` (drop `role_in_project`); 5 default roles 合并到 `project_custom_roles` + auto-grant 节点权限 (PL=write, TL=write, user=read); null role 支持 |
| 8 | Perf 9 ops | 5 索引 (idx_members_project_added_at / idx_custom_role_perms_role_granted / idx_nodes_project_parent_pos / idx_node_perms_node_user / idx_users_created_at) + 3 CTE (list_visible_to UNION ALL / members per_user_permissions 1 query / board per-node perm 1 query) + 2 extra N+1 fix (/users 列表 + /projects 列表) |

**v0.9.2 升版 gate (8/4 教训 — 必查产物 LastWriteTime)**:
- 7 smoke 273/273 PASS (v032 49 + v053 46 + v054 32 + v055 31 + v056 21 + v061 43 + v062 51,实跑验证)
- cleancode 1 / cleanword 0 (cleancode 1 = file_too_long `feature_storage.py 1445 lines > 1000`, structural refactor 挂账)
- EXPLAIN 5/5 hot paths 无 TEMP B-TREE (5 索引全生效)
- Perf: /projects/1/members 80.5ms → 52.3ms (-35%), /users 61.8ms → 21.4ms (-65%), 其余 3 endpoint 在 framework floor 持平 (1 project + 8 user 数据集太小, 30% target 不可达, 挂账)
- Flask healthz 200 (49 routes)
- 升版产物: `history/release_v0.9.2.zip` (311079 bytes, 131 files, integrity OK, clean unpack + 7 smoke 跑通)

**详细 changelog**: `history/release_notes.md` (v0.9.2 段)

---

## v0.9.1(2026-08-12 user 拍板升版)

**v0.9.1 patch 范围 — 14 sub-tasks (user 8/12 18:18 拍)**:

| # | sub-task | 改动 |
|---|---|---|
| 1 | basics | view 端点收尾 + 7 smoke 验证 |
| 2 | RBAC | 3-bucket OR 矩阵 + 4 server-side chokepoints (`add_member_action` / `remove_member_action` / `change_owner_action` / `grant_node_action`) |
| 3 | UI cleanup | per-project Members 链接 + 模板文案统一 |
| 4 | 4 issues | Issue 1 (per-page title) / 2 (view 简化) / 3 (change owner 移到 /members) / 4 (nav hookup) |
| 5 | system_view | 平台 self-status dashboard 整合(system_view.html cleanup) |
| 6 | perf + dead code | `@lru_cache(maxsize=1)` + 模块预热(/projects/1 3.8s→47-58ms,~80x 提速);归档 3 dead code(catalog.html / feature_board.html / feature_board.readme.md) |
| 7 | nav + sidebar | base.html 砍 4 业务链接(projects/users/profile/members)→ 6 层树 sidebar+main 双列 |
| 8 | 砍 kanban | 砍 4 列 kanban 段 + sidebar B-1/B-2/B-4 (sub-task 9 回滚) |
| 9 | 回滚 sub-task 8 B 段 | 保留 A 砍 kanban,回滚 B-1/B-2/B-4 |
| 10 | designer v4 移植 | sidebar 6 层树 + main 单 node 详情 + 操作栏(+ 加子节点 / 删除节点)+ 加子节点跳新未命名详情页 |
| 11 | 真删 (physical delete) | `archive_subtree` → `delete_subtree` (BFS DELETE),7/22 RBAC 守门:server 鉴权 + chokepoint + 不可逆 |
| 12 | base.html nav 修正 | user 拍 "丢反了",加回 Projects + Users,保留 username + Log out |
| 13 | username 跳 me.html | `<span class="muted">kylins</span>` → `<a href="/me">kylins</a>` |
| 14 | 模板文案修正 | delete button inline confirm 文案 "节点将被 archive" → "物理删除 (BFS DELETE)"(status form 跟 delete button 是两个不同操作) |

**v0.9.1 升版 gate (8/4 教训 — 必查产物 LastWriteTime)**:
- 7 smoke 273/273 PASS(v032 49 + v053 46 + v054 32 + v055 31 + v056 21 + v061 43 + v062 51,实跑验证)
- cleancode 0 / cleanword 0(默认 scan = project_board/,test/ 在 scope 外)
- 7 smoke 数量稳定 — 没新加/没删
- copy-editor 4 职责合并 1 task 跑完(职责 1 /team skip,因 v0.9.1 是 patch 不是 milestone 升)
- 升 v0.9.1 patch(2026-08-12 user 拍)

**当前 milestone 状态**:v0.9.8.0(2026-08-20 user 拍板升版,v0.9.7 阶段拍板 + 8/19 三批 62 smoke + 8/20 silent drift + 8 P1 smoke + 1 new endpoint + 3 agent audit 提议修)
**v0.9.8 阶段 scope**:v0.9.8.0 milestone 升完,下个 milestone 升 v0.9.9.0 由 user 拍板
**之前 milestone**:v0.9.7.0(2026-08-18 user 拍板升版,v0.9.7p1 cleanup patch 8 批 worker 跑完后拍板)

**核心约束(沿用 v0.8 + v0.9.1 补)**:
- 6 原则 1-6 全守
- 升版由 copy-editor readme-maintenance skill(职责 4)改 readme 顶部 + 渐进式重写
- 测试代码 test/ 在 cleancode/cleanword scope 外(scope 决策 2026-08-08 拍)
- 7/17 self-contained UI 守门(v0.9.1 sub-task 13 拍):一个页面包含所有需要的信息,缩进表达层级,card / pill / badge 不用
- 7/22 RBAC 业务级 lock(沿用 v0.7.1):server 端每个写必有 chokepoint,client 永远走 server,hand-crafted POST 必拒

**v0.1.0 起点 → v0.5 阶段 → v0.6.0 milestone → v0.7.0 milestone → v0.8.0 milestone → v0.9.0 milestone → v0.9.1 patch**:见 workspace `AGENTS.md` 升版记录(6 原则 3:不写独立 changelog)

## 模块-特性目录

| 模块 | 职责 | 特性数 | 特性列表 |
|---|---|---|---|
| accounts | User 数据模型 + 密码 hash + SQLite 存储层。 | 4 | feature_migrate_v071, feature_password, feature_storage, feature_user_model |
| app | Flask app factory + 路由注册 + config 加载 + Jinja templates。 | 5 | feature_app_factory, feature_config, feature_routes, feature_templates, feature_api_v1 |
| auth | 注册 / 登录 / 登出 / session 管理。 | 4 | feature_login, feature_logout, feature_register, feature_session |
| data | (无职责描述) | 0 | (无特性) |
| profile | 用户改密码端点模块。 | 1 | feature_change_password |
| project_board | (无职责描述) | 0 | (无特性) |
| projects | 项目看板核心 — 项目 CRUD + 列表 + 整合主页。 | 21 | feature_board, feature_create, feature_delete, feature_edit, feature_list, feature_me, feature_members_page, feature_migrate_v092, feature_project_members, feature_project_owner, feature_role_v121, feature_settings, feature_storage, feature_storage_ddl_v092, feature_storage_features, feature_storage_nodes, feature_storage_rbac, feature_user_role, feature_user_view, feature_users_list, feature_view |
| rbac | Role-Based Access Control 基础层。 | 3 | feature_create_admin, feature_require_auth, feature_role |
| team | Team module — 仅 `POST /team/_internal/report` 写端点(copy-editor 上报);`GET /team` v0.9.7 退役 (302 → /projects)。 | 2 | feature_team, feature_team_storage |

## 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 未登录跳 /login,已登录跳 /projects |
| `/register` | GET/POST | 注册(默认 role='user') |
| `/login` | GET/POST | 登录 |
| `/logout` | POST | 登出 |
| `/me` | GET | 整合主页:owned + member projects + 改密码链接(需登录) |
| `/profile/password` | GET/POST | 改密码(需登录) |
| `/admin/promote` | GET/POST | admin 提升 user(需 admin 权限) |
| `/projects` | GET | 项目列表(需登录) |
| `/projects/new` | GET/POST | 创建项目(需 manager / admin) |
| `/projects/<int:id>` | GET | 项目详情 + Members / Settings / Board nav 链接 |
| `/projects/<int:id>/edit` | GET/POST | 改 name + description(legacy edit 表单,v0.9.1 sub-task 1) |
| `/projects/<int:id>/settings` | GET/POST | 改 name + description 的 self-contained settings 页(v0.9.1 sub-task 2) |
| `/projects/<int:id>/delete` | POST | 删项目(owner / admin only) |
| `/projects/<int:id>/owner` | POST | **legacy** change owner(T0/T1 only, v0.7.2b)— v0.9.1 sub-task 3 砍 nav 但 endpoint 保留供 v054 smoke |
| `/projects/<int:id>/board` | GET/POST | Feature Board(4 列 kanban + 6 层 tree 共存,v0.9.1 sub-task 7 整合) |
| `/projects/<int:id>/members` | GET | members 管理页(单一 self-contained 入口:list + add form + change-owner form + role-grant 说明) |
| `/projects/<int:id>/members` | POST | add member(走 `feature_project_members.add_project_member`,v0.5.2) |
| `/projects/<int:id>/members/change-owner` | POST | 改 owner(v0.9.1 sub-task 4 Issue 3 移过来,`change_owner_action` chokepoint) |
| `/projects/<int:id>/members/<int:uid>/remove` | POST | remove member(走 `feature_project_members.remove_project_member`,v0.5.2) |
| `/projects/<int:id>/members/<int:uid>/role` | POST | 改 member 的 custom_role(assign member → role,v0.9.2 sub-task 6 custom role flow) |
| `/projects/<int:id>/roles` | GET/POST | custom role list / create(v0.9.2 sub-task 6,`create_role` chokepoint) |
| `/projects/<int:id>/roles/<int:role_id>` | GET | custom role detail + per-(role, node) grant UI(v0.9.2 sub-task 6) |
| `/projects/<int:id>/roles/<int:role_id>/delete` | POST | 删 custom role(非 baseline,3 个 baseline 不能删) |
| `/projects/<int:id>/roles/<int:role_id>/permissions` | POST | 改 per-(role, node) grant(v0.9.2 sub-task 6,baseline auto-grant + user override) |
| `/projects/<int:id>/features` | GET/POST | **legacy** 4-column kanban(add,smoke v061 探;v0.9.1 sub-task 8 保留) |
| `/projects/<int:id>/features/<int:fid>/move` | POST | **legacy** 移动 feature 到新列(4-column kanban) |
| `/projects/<int:id>/features/<int:fid>` | DELETE | **legacy** 删 feature(4-column kanban) |
| `/projects/<int:id>/nodes` | POST | 6-level tree create node(v0.9.1 sub-task 7 + v0.9.2 末,6-level cap + status whitelist) |
| `/projects/<int:id>/nodes/<int:nid>/edit` | POST | 6-level tree edit node(name + description + status) |
| `/projects/<int:id>/nodes/<int:nid>/status` | POST | 6-level tree quick-change status |
| `/projects/<int:id>/nodes/<int:nid>/delete` | POST | 6-level tree 物理删 node + subtree(BFS DELETE,v0.9.1 sub-task 11 真删) |
| `/team` | GET (retired) | v0.9.7 退役,302 → /projects(原 Team roster 页已下线) |
| `/team/_internal/report` | POST | Agent 上报(writer,shared secret auth) |
| `/api/v1/system/status` | GET | v0.9.8 experiment — server status JSON (read-only, no auth) |
| `/users` | GET | 用户列表(需登录) |
| `/users/<int:id>` | GET | 用户详情(需登录) |
| `/users/<int:id>/role` | POST | 改 user rank(T0-T4,接受 int 或 string,v0.9.2 sub-task 3 接受 int/string;路径名沿用 v0.3.1) |

## 数据存储

`data/project_board.db`(SQLite 单文件)

**表**(v0.9.3 末期,9 张业务表 + 2 张 sqlite 内部表):

| 表 | 引入 | 字段 |
|---|---|---|
| `users` | v0.1.0 | id, username, password_hash, role (TEXT, default NULL, v0.9.2 sub-task 2 清空;legacy 兼容), rank (INTEGER, T0-T4, default 4), created_at |
| `sessions` | v0.1.0 | sid, user_id, expires_at |
| `projects` | v0.1.0 | id, name (UNIQUE), description, owner_id, is_system, project_type, created_at, updated_at |
| `project_members` | v0.5.0 (v0.9.2 sub-task 7 重建) | (project_id, user_id) composite PK, custom_role_id (INTEGER, FK→project_custom_roles.id, nullable = "未分配 role"), added_at |
| `project_features` | v0.6.1 | id, project_id, name, description, status (backlog/in_progress/done/archived), position, created_at, updated_at |
| `agent_team_status` | v0.6.0 | id, name, role, status, last_heartbeat, metadata (JSON) |
| `project_nodes` | v0.9.1 sub-task 7 | id, project_id (FK CASCADE), parent_id (FK CASCADE, self-ref), level (CHECK ∈ [1, 6]), name, description, status (4 字面量同 project_features), position, created_at, updated_at |
| `project_custom_roles` | v0.9.1 sub-task 2 (v0.9.2 sub-task 7 合并) | id, project_id (FK CASCADE), name, description, created_at;UNIQUE (project_id, name) |
| `project_custom_role_permissions` | v0.9.1 sub-task 2 (v0.9.2 sub-task 7 合并) | (custom_role_id, node_id) composite PK, can_write (INTEGER, default 0), granted_at;FK CASCADE 链 custom_role_id→project_custom_roles, node_id→project_nodes |
| `sqlite_sequence` | (sqlite 内部) | — |
| `sqlite_stat1` | (sqlite ANALYZE) | query planner statistics,自动生成 |

**v0.9.3 删** (user 8/13 19:34 拍板): `project_node_permissions` 表 (v0.9.2 加, 0 行实际数据, 路由层从未真正调用 chokepoint — 混合设计, 整套删)。pre-v0.9.3 DB 上表保留 (7/22 业务级 lock 禁 silent DELETE)。

**6-level tree invariant**(`project_nodes`):`level ∈ [1, 6]`,SQL CHECK 约束 + `feature_storage_nodes._do_create_node` 双重守门。`parent_id` 跨 project 或 cycle 全部 server-side reject。

**null role 语义**(`project_members.custom_role_id`):`IS NULL` 是合法状态,表示"未分配 role"(默认 `add_member` 状态)。`_member_role` 返 None,`_is_member` 拆 membership 检查(见 `feature_members_page.py:104`)。

**13 个索引**(v0.9.3 — `idx_node_perms_node_user` 跟 user-level 表一起删):

| 索引 | 表 | 覆盖查询 |
|---|---|---|
| `idx_users_username` | users | login find_by_username |
| `idx_users_created_at` | users (v0.9.2 sub-task 8) | /users list ORDER BY id, 兜底 covering index |
| `idx_sessions_user_id` | sessions | session lookup by user_id |
| `idx_projects_owner` | projects | list_visible_to OWNED branch |
| `idx_members_user` | project_members | list_member_of JOIN |
| `idx_members_project_added_at` | project_members (v0.9.2 sub-task 8) | list_members ORDER BY,无 TEMP B-TREE |
| `idx_members_custom_role` | project_members (v0.9.2 sub-task 7) | list_members JOIN project_custom_roles (custom role name) |
| `idx_features_project_status` | project_features | Feature Board 4-column ORDER BY (status, position) |
| `idx_nodes_project_level` | project_nodes (v0.9.2) | list_tree 6-level bucket query |
| `idx_nodes_project_parent` | project_nodes (v0.9.2) | list_children by parent_id |
| `idx_nodes_project_parent_pos` | project_nodes (v0.9.2 sub-task 8) | list_tree 完整 ORDER BY 列序匹配 |
| `idx_custom_role_perms_role` | project_custom_role_permissions (v0.9.2) | list_role_node_permissions base |
| `idx_custom_role_perms_role_granted` | project_custom_role_permissions (v0.9.2 sub-task 8) | list_role_node_permissions ORDER BY,无 TEMP B-TREE |

**v0.9.1+ 写 chokepoints 索引**(7/22 业务 lock, v0.9.3 — 从 4 砍 1 chokepoint):
- `add_member_action` / `remove_member_action` — `feature_project_members` 调
- `change_owner_action` — `feature_members_page.submit_change_owner` 调
- ~~`grant_node_action`~~ (v0.9.3 删 — user-level grant surface 整套删; role-grant 走 route-only 路径)
- `create_role_action` / `delete_role_action` / `submit_role_node_permission` — `feature_members_page` 调(v0.9.2 sub-task 6)
- `assign_member_to_role_action` — `feature_members_page.submit_member_custom_role` 调(v0.9.2 sub-task 6)
- `ProjectStorage.update` (name + description) — `feature_edit` + `feature_settings` 调
- `ProjectStorage.delete_subtree` (BFS DELETE) — `feature_board` 物理删节点调(v0.9.1 sub-task 11)

## 启动

1. 编辑 `config.yaml`,设置 `ADMIN_USERNAME` / `ADMIN_PASSWORD`
2. `python -m project_board` 或 `flask --app project_board.app run`
3. 首次启动自动建表(seed: 首个 admin + 系统项目 + 3 baseline roles + auto-grant 节点权限)+ idempotent 跑 v0.7.1 / v0.9.1 / v0.9.2 三段 migration(中间版本 DB 升到 v0.9.2 期间所有 schema 改动;fresh install 跳过)
4. 浏览器访问 `http://localhost:5000`

## 不做(后续 milestone)

- 更细粒度权限(单 role → 多 role × 多 action 矩阵)— v0.9.2 role + custom role merge 是 v0.10.0 之前的 baseline
- 审计日志(_audit + sql_ops_ledger,7/22 原则)
- 邮箱验证 / 密码重置
- 多用户协作场景(v0.6 阶段规划)
