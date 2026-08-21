"""Verify workspace directory layout aligns with AGENTS.md 6 原则.

原则 6 — project_board 纯化: ``project_board/ = 项目相关内容 only``,
任何非项目相关(参考 / snippet / generic infra / scratch / tooling 备份 /
投机代码)全部驱逐。

原则 2 — 附属产物统一收编: workspace 根的 4 个目录(log/ test/ history/)
只放"非项目本体"的东西,所有项目共用,不按项目分散。

This tool enforces the layout by checking:

1. ``project_board/`` 下不应该有非项目相关的目录
   (Node.js 独立项目, scratch, 临时脚本等)。
2. workspace 根应该有规范的 4 个附属目录
   (log/ test/ history/ tools/), 不能放在 project_board/ 内。
3. demo_pptx/ 应在 workspace 根(不是 project_board/ 内),因为它是
   跨项目 demo 产物,不是 project_board source。

History:
- 2026-08-20: 初版,源于 v0.9.8.0 demo 打包时 user 抓出
  ``project_board/demo_pptx/`` 误放问题,清洁 check 漏检查
  目录布局,补这个守门。

Run:
    python tools/check_directory_layout.py [WORKSPACE_ROOT]

Exit 0 = OK, exit 1 = violation found.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# 禁止出现在 project_board/ 下的目录/文件 pattern
# 这些是"非项目相关"的产物,该放 workspace 根或其他附属目录
FORBIDDEN_IN_PROJECT_BOARD = [
    "demo_pptx",          # 独立 Node.js 项目,放 workspace 根
    "node_modules",       # 第三方依赖,放各自项目根,不该是 project_board/
    ".git",               # workspace 根的 VCS
    ".vscode",            # 编辑器配置
    ".idea",              # 编辑器配置
    "scratch",            # 临时脚本
    "snippets",           # 代码片段
]

# workspace 根应有的附属目录
EXPECTED_ROOT_DIRS = [
    "log",
    "test",
    "history",
    "tools",
    "AGENTS.md",
]


def check_project_board_purity(workspace: Path) -> list[str]:
    """Return list of violations found in project_board/."""
    violations = []
    pb = workspace / "project_board"
    if not pb.is_dir():
        violations.append(f"project_board/ not found at {pb}")
        return violations

    for forbidden in FORBIDDEN_IN_PROJECT_BOARD:
        target = pb / forbidden
        if target.exists():
            violations.append(
                f"project_board/{forbidden}/ exists "
                f"—— 违反 AGENTS.md 原则 6 (project_board/ = 项目相关内容 only)"
            )
    return violations


def check_root_layout(workspace: Path) -> list[str]:
    """Return list of missing expected root dirs."""
    missing = []
    for entry in EXPECTED_ROOT_DIRS:
        target = workspace / entry
        if not target.exists():
            missing.append(f"workspace root missing: {entry}/")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify AGENTS.md 6 原则 directory layout"
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=r"C:\Users\lying\.minimax-agent-cn\projects",
        help="workspace root (default: C:\\Users\\lying\\.minimax-agent-cn\\projects)",
    )
    args = parser.parse_args()
    workspace = Path(args.workspace)

    print(f"[INFO] checking workspace: {workspace}")
    print()

    pb_violations = check_project_board_purity(workspace)
    root_missing = check_root_layout(workspace)

    all_violations = pb_violations + root_missing

    if pb_violations:
        print("== project_board/ violations ==")
        for v in pb_violations:
            print(f"  [FAIL] {v}")
        print()

    if root_missing:
        print("== workspace root missing ==")
        for v in root_missing:
            print(f"  [FAIL] {v}")
        print()

    if not all_violations:
        print("[OK] workspace layout aligns with AGENTS.md 6 原则")
        print(f"  - project_board/ pure: {len(FORBIDDEN_IN_PROJECT_BOARD)} patterns checked")
        print(f"  - root dirs present: {len(EXPECTED_ROOT_DIRS)} expected")
        return 0

    print(f"[FAIL] {len(all_violations)} violation(s) found")
    return 1


if __name__ == "__main__":
    sys.exit(main())
