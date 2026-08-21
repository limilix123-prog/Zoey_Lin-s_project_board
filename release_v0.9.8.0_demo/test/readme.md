# test/ — 测试用例库

> 6 原则 2: workspace 附属产物 test/ 放 workspace 根(不按项目分散)
> **v0.9.8.0 demo 拍板** (2026-08-20): 12 smoke 累计 **389/389 PASS**

## 测试目录结构(12 套,389 case)

| 文件 | 阶段 | 测什么 | case |
|---|---|---|---|
| `smoke_v032_mavis.py` | v0.7.3 | 5-role session/login/logout/role (T0-T4 scale) | 49 |
| `smoke_v053_mavis.py` | v0.7.3 (8/13 v0.9.2 改) | RBAC T0-T4 per-project role + 拆 membership / role 检查 | 46 |
| `smoke_v054_mavis.py` | v0.7.3 | 项目 per-project 边界 | 32 |
| `smoke_v055_mavis.py` | v0.7.3 | project_create 业务 (T0/T1 only) | 31 |
| `smoke_v056_mavis.py` | v0.7.3 | system project | 21 |
| `smoke_v061_mavis.py` | v0.7.3 | Feature Board CASCADE | 43 |
| `smoke_v062_mavis.py` | v0.7.3 | /team + /team/_internal | 51 |
| `smoke_v070_mavis.py` | v0.9.7.0 | 16 P0 核心区 0 hit(7/15 spec 守门, 8/19 verifier audit) | 34 |
| `smoke_v071_mavis.py` | v0.9.7.0 | 21 P1 polish(verify audit 补漏) | 21 |
| `smoke_v072_mavis.py` | v0.9.7.0 | 11 P2 边角(P2 backlog) | 51 |
| `smoke_v073_mavis.py` | v0.9.8.0 | `/api/v1/system/status` 端点(8/19 worker trial) | 1 |
| `smoke_v074_mavis.py` | v0.9.8.0 | 8 P1 polish(8/20 silent drift 修 + 8/20 verifier 8 case) | 9 |

**累计**: 49+46+32+31+21+43+51+34+21+51+1+9 = **389 case / 389 PASS**

## 跑法

```bash
# 单个跑
python test/smoke_v032_mavis.py

# 全部跑(用 smoke_runner,推荐)
python tools/smoke_runner.py --all

# 列已发现
python tools/smoke_runner.py --list

# 跑指定
python tools/smoke_runner.py --id v032 --id v074
```

`smoke_runner.py` 跨 7/22 教训 守门(subprocess + Windows GBK 兼容 + cwd=str 强制):
- 每个 smoke 独立 subprocess 跑,自己启 Flask + temp DB
- 读 raw bytes 解析 `TOTAL: pass=N fail=M`,GBK 编码也 OK
- 任何 fail = exit code 1

## 阶段历史

- v0.7 阶段(2026-08-07): 7 smoke 重写(按 v0.7 RBAC 概念), 270 case
- v0.8 阶段(2026-08-07): 7 smoke 从 `smoke/` 归档到 `test/`, 273 case
- v0.9.0 → v0.9.2 patch(8/8 - 8/13): 273 → 273(没新加/没删,只改 v053 `_is_member` helper)
- v0.9.7.0 milestone(8/19): +3 smoke(v070/v071/v072) = 34+21+51=106 case
- v0.9.8.0 milestone(8/20): +2 smoke(v073/v074) = 1+9=10 case
- **v0.9.8.0 终态**: 12 smoke 389/389 PASS

## 声明 vs 实际(7/21 教训)

12 smoke 测的功能跟实际代码端点对齐:

- v032 session/login/logout: ✓ `auth/feature_session.py` + `feature_login.py` + `feature_logout.py`
- v053 RBAC T0-T4 + null role: ✓ `projects/feature_members_page.py` `_is_member` helper
- v054 per-project 边界: ✓ `projects/feature_storage.user_can_see_project`
- v055 project_create 业务: ✓ `projects/feature_create.py` `@require_role(MANAGER)`
- v056 system project: ✓ `app/feature_app_factory.ensure_admin_exists`
- v061 Feature Board CASCADE: ✓ `projects/feature_storage` `ON DELETE CASCADE` + `projects/feature_board.py`
- v062 /team + /team/_internal: ✓ `team/feature_team.py` 端点
- v070 16 P0 核心区: ✓ 8/19 verifier audit 报告
- v071 21 P1 polish: ✓ verify audit 补漏
- v072 11 P2 边角: ✓ P2 backlog
- v073 system-status JSON: ✓ `app/feature_api_v1.py` 端点
- v074 8 P1 polish: ✓ 8/20 silent drift 修 + verifier 8 case

**本次 v0.9.8.0**: 12 smoke 全部对齐, 无声明 vs 实际脱节。

## 跨迭代清理(7/31 教训)

白名单是迭代级临时, 跨迭代必清:

- v0.9.7.0 → v0.9.8.0: 5 新 smoke (v070-v074), 0 跳过
- 12 smoke 跨 v0.9.x 阶段数量稳定 + 116, 跨迭代不需白名单清理
- 跑前 `tools/smoke_runner.py` 自带 preflight(7/31 教训工具自带 preflight)

## 不做

- 不放设计文档 / spec / changelog(6 原则 3, 放 `history/`)
- 不放 `tools/` 工程工具(6 原则 2, test/ 只放测试)
- 不放项目代码(6 原则 6, test/ 跟 project_board/ 平级)
- 不放 demo zip 专属(8/4 教训, demo zip 复制本目录即可)
