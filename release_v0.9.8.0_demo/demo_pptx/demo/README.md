# project_board v0.9.8.0 + mavis 设计哲学 演示 Demo

> 两个视角: 项目怎么用 + 系统怎么设计
> **v0.9.8.0 重新打包** (2026-08-20, 8/20 user 拍板, layout 修复 + PPT 内容更新)

## 包含文件

| # | 文件 | 张数 | 角度 | 读者 |
|---|---|---|---|---|
| 1 | `project_board_how_to_use.pptx` | 11 | 使用者 · 个人 / 团队 | 看完知道项目怎么跳 + 怎么部署 |
| 2 | `mavis_design_philosophy.pptx`   |  6 | 设计者 · 如何设计 mavis | 看完知道 mavis 为什么这么做 |

## PPT 1: 使用手册 (11 张)

> 用户视角 · 讲"怎么用" · 不谈架构 · 不谈表结构 · 不谈实现

| # | 主题 |
|---|---|
| 01 | 封面 · 5 分钟上手 (v0.9.8.0 新增: 12 smoke · 389/389 PASS · /api/v1/system/status) |
| 02 | 两种使用姿态 (一个人 / 团队) |
| 03 | 第一次进入 (登录 · /me) |
| 04 | 创建项目 (UI mockup) |
| 05 | 加同事 + 4 个 default role |
| 06 | 6 层节点树 · 拆任务 |
| 07 | 4 状态列 · 跟踪进度 |
| 08 | 常用操作速查 |
| 09 | FAQ 5 问 |
| 10 | Quick start · 3 命令 + 3 点击 · demo 免责声明 |
| 11 | 部署教程 · 5 步从 0 到跑通 (环境/依赖/解压/启动/访问 + 常见坑) |

> 2026-08-16 实际在 http://127.0.0.1:5000 跳过完整 5 步流程 · 17/17 PASS
> 2026-08-18 修订: 删除 /team 一页 (v0.9.3 中 /team 已重定向到 /projects, 不再是 team 监控页)
> 2026-08-20 升 v0.9.8.0: cover 改版本号 + 新增行, footer 更新, 内容不变 (5 分钟 tour 是 timeless)

## PPT 2: mavis 设计哲学 (6 张)

> 设计者视角 · 讲"如何设计 mavis 这个系统" · 不谈实现 · 不谈 project_board 项目细节

| # | 主题 | 问一句话 |
|---|---|---|
| 01 | 封面 · Designing for Sharp Agents | 设计不让 agent 变僵 |
| 02 | 3 条原则总览 | 不变僵 · 不乱搞 · 不传垃圾 |
| 03 | 原则 1: 不变僵 | 上下文预算 + skill 治理 |
| 04 | 原则 2: 不乱搞 | 验证独立 · 抵假通过 = 系统死 |
| 05 | 原则 3: 不传垃圾 | cleancode · memory 三层 · context 漂移 |
| 06 | 一页查阅 cheat sheet | 遇到决策 查这个 |

## 核心设计哲学 3 条

```
1. 不变僵     上下文 ≤ 10K · 能不加 skill 不加 · 能不查 不查 · 不负担冗信息
2. 不乱搞     verifier 独立 · smoke 真跳 · 抵假通过 = 系统已经死
3. 不传垃圾  cleancode / cleanword · memory 三层 · 上下文中的旧信息 会被当现行规则
```

## 启动

```
$ python -m project_board
  or
$ flask --app project_board.app.feature_app_factory:create_app run
```

config.yaml 默认 seed:
- admin: `kylins / kylins123`
- manager: `manager / manager123`
- project_leader: `project_leader / project_leader123`
- team_leader: `team_leader / team_leader123`

首次启动自动 seed 4 个 user + 1 个 system project · 跳项目前先跳 /login

## 使用

PowerPoint / Keynote / WPS 打开 .pptx:
- 只看"项目怎么用" → 看 PPT 1
- 只看"mavis 为什么这么做" → 看 PPT 2
- 两个都看 → 16 张 · 5 分钟

## 元数据

- 快照时间: 2026-08-20
- project_board 版本: v0.9.8.0 (2026-08-20 拍板升版, 12 smoke 389/389 PASS)
- mavis: MiniMax Code orchestrator agent
- demo 数据: 1 system project "项目管理系统" (kylins owner, 4 seed users)

## v0.9.8.0 关键变更(对比 v0.9.3 PPT)

| 项 | v0.9.3 (旧) | v0.9.8.0 (新) |
|---|---|---|
| project_board 基线 | v0.9.3 (8/13 拍) | **v0.9.8.0** (8/20 拍) |
| smoke 数 | 7 套 / 273 case | **12 套 / 389 case** |
| Flask routes | 49 | **50** (新增 `/api/v1/system/status`) |
| 错误页 | 英文 | **中文** (v0.9.5 polish) |
| demo_pptx/ 位置 | `project_board/demo_pptx/` (违反 6 原则) | **workspace 根 `demo_pptx/`** (8/20 修复) |
| 内容 | 5-min tour 跟 3 原则 | **同** (timeless) |
