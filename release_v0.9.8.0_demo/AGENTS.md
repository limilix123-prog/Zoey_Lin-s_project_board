# Workspace AGENTS.md

> **single source of truth** — mavis + 所有 sub-agent 在本 workspace 的工作纪律
> 6 条原则 + 全部澄清(定稿,拍板时间归档到 `history/AGENTS_v091_clean_changelog.md`)
> 跟项目内容相关的描述进 `project_board/readme.md`,本文件只管"怎么工作"

---

## 原则 1 — 3 级结构

项目 / 模块 / 特性 → 根目录文件夹 / 项目下文件夹 / 一个 `.py` 文件

- **模块 = 标准 Python package**(`__init__.py` 要),纯命名空间布局
- **特性 = 一个 `.py` 文件**,只做一件事
- **特性 `.py` ≤ 2000 行**(项目级硬约束;超了 = 不是单一特性,要拆)
- 文档配套:`module/readme.md` + `module/feature.readme.md`(跟 `.py` 同级),**小写 `readme.md`**

## 原则 2 — 附属产物统一收编

workspace 根的 3 个目录,只放"非项目本体"的东西:

- `log/` — 运行时日志、工具输出、debug trace
  - 子结构:`log/<project>/<module>/<feature>.log`
- `test/` — 所有测试
- `history/` — 过期 / 废弃 / 失效文件 + release zip

> 这 3 个目录是 workspace 级别,所有项目共用,不按项目分散。

## 原则 3 — project_board 最小文件集

`project_board/` 只允许保留**"运行 + 理解" project_board 的最小文件集**:

- **运行**:代码 + 配置 + 依赖声明
- **理解**:每个模块 / 特性一份 `readme.md`,**概括性 WHAT**,不写 HOW / design / 历史 / TODO
- **文档严格约束**:`readme.md` only,**不允许其他任何 md 文件**
  - ❌ design doc / spec / changelog / notes / todo / 多余 README
  - ✅ 设计决策 / trade-off 嵌入 `readme.md` 或本 `AGENTS.md`

## 原则 4 — 任务分发独占 + 文件总上下文硬上限

- **mavis = 唯一任务分发者**;其他 agent 不互派、不直接联系 user
- **mavis → 单一 sub-agent 任务总上下文 ≤ 10,000 行**(per-task total,不是 per-file)
- **sub-agent 只能读 mavis 给的文件**(不能自主补查;option b)
- mavis 角色:**orchestrator + 守门人 + 预处理器**
  - 读大文件 → 抽相关段 → 拼成 ≤ 10K 总输入 → 派给 sub-agent

## 原则 5 — 流程迭代 + 用户验收

### 3 阶段流程

**x.y.1 开始前**(scope 锁定)
1. user → mavis 提需求
2. mavis 分解需求
3. mavis 提议 scope(模块 + 特性变更范围)
4. **user 确认 scope**(人拍)

**x.y.z 迭代**(每轮执行,5 角色)
1. mavis → coder 发要求
2. coder 实施 + 给出修改意见
3. verifier 写用例跟踪
4. evaluator 评估(P0 / P1 / P2 分类)
5. tools 脚本拦截问题
6. 全过 → 回合代码,z++
7. 任一不过 → **重做当前 z**(不跳版本)

**x.y.max 收口**(客观触发 + 用户终裁)
- 触发条件(客观):**全 P0 解决 + evaluator 通过 + tools 0 拦截**
- mavis 自判完成 → 上报 user
- user 接受 / 拒绝
- 拒绝 → 迭代失败(原则 5 兜底)
- **user 接受后(升 x.(y+1).0 milestone 前)** — mavis 派 copy-editor 履行 /team 数据上报:
  1. copy-editor 拉 mavis agent list + 任务数
  2. POST 到 project_board `/team/_internal/report` (shared secret 认证)
  3. 上报完成后, mavis 升下一个 milestone (v0.x.y → v0.x.(y+1).0)
- 详见 v0.6.2 起的 copy-editor 3 职责 (`history/project_board_design_decisions_v0.6.0.md` 引用)

### P-level 处理

- **P0 = 硬闸门**:任何 P0 遗留 = 阻塞 release
- **P1 / P2 = 软**:不再硬阻断(完整 x.y.max trigger = 全 P0 解决 + evaluator 通过 + tools 0 拦截;P-level 闸门已统一,见 `history/AGENTS_v091_clean_changelog.md`)

## 原则 6 — project_board 纯化

- **`project_board/` = 项目相关内容 only**
- 任何非项目相关(参考 / snippet / generic infra / scratch / tooling 备份 / 投机代码)全部驱逐
- 第三方依赖:
  - 算"项目相关"
  - 删掉**不影响理解**(声明是"运行"最小集,不是"理解"层)
  - 依赖本体住 site-packages;`project_board/` 只需声明文件(`requirements.txt` / `pyproject.toml`)
- 替代去向:
  - 工程工具 → `tools/`(workspace 根,目前不是项目)
  - 测试 → `test/`
  - 日志 → `log/`
  - 历史 → `history/`
  - 个人 scratch → `C:\Users\lying\temp\`(mavis-temp-convention)

---

## Canonical workspace 结构

```
workspace_root/
├── AGENTS.md                          # 本文件
├── project_board/                     # 主项目(目前唯一,具体内容 MVP 拍)
│   ├── readme.md
│   ├── config.yaml / .env / prompts/  # 配置第一层(不进模块)
│   ├── __init__.py
│   ├── module_a/
│   │   ├── __init__.py
│   │   ├── readme.md
│   │   ├── feature_x.py               # ≤ 2000 行
│   │   └── feature_x.readme.md
│   └── ...
├── test/                              # 全部测试
├── log/project_board/<module>/<feature>.log
└── history/                           # 过期 / 废弃 / 失效 + release zip
```

## 5 角色在迭代内的位置

| 角色 | 职责 |
|---|---|
| **mavis** | orchestrator + 守门人 + 预处理器(scope 锁定 / 任务分发 / 上下文化 / 收口) |
| **coder** | 实施 + 修改意见 |
| **verifier** | 写用例跟踪(对账行为) |
| **evaluator** | 系统可用性评估(P0 / P1 / P2 分类) |
| **tools** | 自动化拦截(commit hook / preflight / 白名单 / --strict) |
| **user** | 唯一终局裁者(scope 确认 + x.y.max 验收) |

---

## 版本号约定(mavis 易踩的坑)

**逻辑迭代名 vs 实际版本号**:
- 原则 5 spec 里的 `x.y.1` / `x.y.z` / `x.y.max` 是**逻辑迭代名**(`x.y.1` = 第一次迭代, `x.y.z` = 第 z 次, `x.y.max` = 等 user 验收)
- **实际版本号是 `v(x).(y-1).z`**(`y-1` 是 milestone 的上一段)
- user 拍板升 milestone 时, `v(x).(y-1).z` → `v(x).(y).0`

**具体例子**(project_board 实情,详见 `history/AGENTS_v091_clean_changelog.md`):

| 逻辑名 | 实际版本号 | 状态 |
|---|---|---|
| `x.y.1` | `v0.0.1` | 第一轮 build(stage 1 + stage 2),user 试发现 2 P0,**被拒** |
| `x.y.1`(重做) | **`v0.0.2`** ← 当前 | bug 已修,等 user re-verify |
| `x.y.max`(拍板后) | `v0.1.0` | user 拍板升 milestone(交付版本) |

**反向例子(❌ mavis 之前犯的错)**:把 `x.y.1` 误当成 `v0.1.1` → 实际版本号**不可能**比 milestone 还大 → 倒退。

**记忆法**:**patch 版本 `v(x).(y-1).z` 永远在 milestone `v(x).(y).0` 之前**,user 拍板是"升级"动作,从 patch 升到 milestone。

---

## 落地要决定但还没拍(实施时再补)

- 依赖声明形态(`requirements.txt` / `pyproject.toml`)
- Python 版本基线
- entry point 命名(`main.py` / `app.py` / `server.py` / `cli.py`)
- 测试框架(默认 `pytest`,未 owner 允许前不引入)
- 命名约定(默认 snake_case 文件 / PascalCase 类)
- 工具行为纪律(preflight / --strict / 集成走 subprocess / `time.time_ns()` 等;工具拍板时间归档到 `history/AGENTS_v091_clean_changelog.md`)

> 这些进了实施窗口,跟具体模块 / 特性一起拍;owner 允许前不擅自定。

---

## v0.9.1 changelog (8/13 mavis perf pass)

**9 个 perf 操作落地** (profile 8/13 06:45 暴露的 5 USE TEMP B-TREE + 2 SCAN + 2 N+1):

### 索引 (5 — `init_schema` idempotent CREATE INDEX IF NOT EXISTS)

1. `idx_members_project_added_at` ON `project_members(project_id, added_at)` — 覆盖 `list_members` ORDER BY,无 temp btree
2. `idx_custom_role_perms_role_granted` ON `project_custom_role_permissions(custom_role_id, granted_at)` — 覆盖 `list_role_node_permissions` ORDER BY
3. `idx_nodes_project_parent_pos` ON `project_nodes(project_id, level, parent_id, position, created_at)` — 完整匹配 `list_tree` ORDER BY 列序,列序相对 spec 调过 (spec 是 `(project_id, parent_id, position, created_at)` 缺 `level`,EXPLAIN 仍 TEMP B-TREE FOR RIGHT PART)
4. `idx_node_perms_node_user` ON `project_node_permissions(node_id, granted_at)` — 覆盖 `_do_list_node_permissions` ORDER BY;列序从 spec 的 `(node_id, user_id)` 改为 `(node_id, granted_at)` 才能消掉 TEMP B-TREE
5. `idx_users_created_at` ON `users(created_at, id)` — 兜底 covering index,`/users` 主查走 PK (ORDER BY id)

### CTE / N+1 重写 (4)

6. `list_visible_to` 的 `_USER_LIST_SQL` 改 CTE `WITH owned AS (...) UNION SELECT * FROM membered ORDER BY id ASC` — 替掉 `MULTI-INDEX OR` 计划
7. `list_member_of` — spec 标"可暂时不动"(EXPLAIN 用 `idx_members_user` 已 OK),保留原状
8. members page `per_user_permissions` — 新加 `_list_all_user_perms_rows` helper,1 query 替 N+1
9. board view `per-node perm` — 新加 `_collect_user_node_perms` helper,1 query 替 N+1;同时把原 `_render_board` 里两段重复的 `for n in tree: my_grants.extend(...)` loop 合一

### 顺手 N+1 修复 (不在 spec 9 op 里,但 verify timing 必做)

- `/users` 列表里每 user 调 `list_owned_by` + `list_member_of` (8 user = 16 round-trips) → 新加 `list_owned_and_member_counts` 一次性 GROUP BY 2 query
- `/projects` 的 `_owner_username_lookup` 一 owner 一次 `find_by_id` → 新加 `find_usernames_by_ids` 一次 SELECT

### 验证 (verify_perf_v091.py 全跑)

- 5/5 EXPLAIN: 全部无 TEMP B-TREE
- 5/5 索引: 全部 installed
- 7 smoke: 273/273 PASS
- timing:
  - `/projects/1/members`: 80.5 → 50.7ms (37% 改善) ✓
  - `/users`:              61.8 → 21.5ms (65% 改善) ✓
  - `/projects/1/board`:   30.8 → ~28ms (持平 — 框架开销占大头,DB 已 < 3ms)
  - `/projects`:           22.6 → ~21ms (持平 — 1 project / 1 owner,无 N+1 空间)
  - `/`:                  34.7 → ~33ms (持平 — 302 redirect,urllib follow 拖慢)

### 已知 / 挂账

- 3 endpoint timing 没到 30% target,但都**没 regression**;target 跟 framework 物理下限(15-20ms Flask overhead)冲突,需要换 baseline 或换更轻框架才能继续降。本窗口**不**展开框架层 perf。
- `idx_node_perms_node_user` 列序跟 spec 不一致 (spec `(node_id, user_id)`,实际 `(node_id, granted_at)`);原因 EXPLAIN 验证 spec 版仍 TEMP B-TREE,换列序消掉。verify 脚本里 EXPLAIN 是关键守门。
- `idx_nodes_project_parent_pos` 列序跟 spec 不一致 (spec `(project_id, parent_id, position, created_at)`,实际 `(project_id, level, parent_id, position, created_at)`);同理。


---
