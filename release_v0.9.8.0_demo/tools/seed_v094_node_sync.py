"""v0.9.4 patch: sync 29 nodes description + status to v0.9.3 actual state.

Idempotent: re-running yields same result (uses fixed string values).

Targets 14 nodes (L1=3, L2=7, L3=3+1 renamed, L4=1):
- L1: all 3 phases (sync to v0.9.3)
- L2: all 7 modules (sync to v0.9.3)
- L3: 4 features (status or name change for v0.9.3 user-level deletion)
- L4: 1 sub (extend role-field-deprecated note)

Other 14 nodes keep their current description (already accurate).

DB connection via env var PROJECT_BOARD_DB_PATH (default: project_board/data/project_board.db).
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = Path(
    os.environ.get(
        "PROJECT_BOARD_DB_PATH",
        r"C:\Users\lying\.minimax-agent-cn\projects\project_board\data\project_board.db",
    )
)

# Each entry: (id, new_name, new_status, new_description)
# Only include nodes that need sync (idempotent fixed strings).
UPDATES = [
    # ===== L1: 3 phases (全部 sync to v0.9.3) =====
    (
        38,
        "Phase-A: Foundation",
        "done",
        "Auth, RBAC, project CRUD, and the 6-level node tree. "
        "Shipped: v0.9.3 baseline (Auth + RBAC + CRUD + 6-level tree + project_board.db schema). "
        "v0.9.2 8 sub-tasks done.",
    ),
    (
        39,
        "Phase-B: Collaboration",
        "done",
        "Multi-user, per-project role (3 baseline + N custom), node-level role-grant (per-(role, node) write), member list. "
        "v0.9.3 删 user-level grant 整套, 全部走 role 路径. "
        "v0.9.2 custom role flow + auto-grant 3 default roles done.",
    ),
    (
        40,
        "Phase-C: Self-Status",
        "done",
        "System self-monitoring: 6-level board, project status descriptions, copy-editor 4 skills "
        "(md doc audit / comment audit / readme maintenance / test-case maintenance). "
        "v0.9.2 done. "
        "v0.9.3 cleanup 3 categories done (FeatureRow.version 删 + 4 v0.9.6 stale refs 清 + 14 readme 写 + 53 v0.9.1/v0.9.2 标签归位).",
    ),
    # ===== L2: 7 modules (全部 sync) =====
    (
        41,
        "Module-A1: Auth & Identity",
        "done",
        "Server-side session with opaque sid cookie (pb_sid), bcrypt-style password hashing, rank integer 0-4. "
        "v0.9.2 register + login + logout + change_password 端点 done.",
    ),
    (
        42,
        "Module-A2: RBAC",
        "done",
        "T-scale (0=admin/T0 .. 4=user/T4) and per-project role (3 baseline + N custom). "
        "v0.9.3 删 user-level grant 整套, 决策路径走 role 路径 "
        "(_has_node_role_grant JOIN project_members). "
        "7/22 RBAC 业务级 lock 仍守 (server 唯一鉴权口 + _audit + sql_ops_ledger).",
    ),
    (
        43,
        "Module-A3: Project CRUD",
        "done",
        "Project create / read / update / delete + 6-level node tree (project_nodes level 1..6) "
        "+ project_features 独立表. "
        "v0.9.2 6-level depth check done.",
    ),
    (
        44,
        "Module-B1: Members",
        "done",
        "Project membership list, add / remove member, change owner (T0/T1 only). "
        "v0.9.3 members.html UI 改 2 段结构 (current role + change to dropdown), "
        "single Role column 含 (no role) + 全部 roles, role_id 字段 + 描述显示.",
    ),
    (
        45,
        "Module-B2: Node Permissions",
        "done",
        "v0.9.3 删 user-level grant 整套. "
        "Per-(role, node) can_write grant stored in project_custom_role_permissions "
        "(custom_role_id, node_id, can_write). "
        "3 default roles (project_leader/team_leader/user) auto-grant 每个节点. "
        "project_node_permissions 表 DDL 不 install (pre-v0.9.3 DB 保留表但 0 行).",
    ),
    (
        46,
        "Module-C1: Migrations",
        "done",
        "v0.7.1 rank column added; "
        "v0.9.1 role deprecate (role field RENAME -> users_role); "
        "v0.9.2 12-step role migration (role_in_project -> custom_role_id); "
        "v0.9.3 删 user-level migration (DDL 不 install + 索引 删).",
    ),
    (
        47,
        "Module-C2: Maintenance",
        "done",
        "copy-editor 4 skills: team-report (职责 1), md doc audit (职责 2), "
        "comment audit (职责 3), readme maintenance (职责 4), "
        "test-case maintenance (职责 5). "
        "v0.9.2 done. "
        "v0.9.3 cleanup 3 categories done "
        "(FeatureRow.version 删 + 4 v0.9.6 stale refs 清 + 14 readme 写好).",
    ),
    # ===== L3: 4 features sync (含 1 个 name 改 + 1 个 archived) =====
    (
        51,
        "Feature: Project Role",
        "done",
        "project_members.custom_role_id FK to project_custom_roles. "
        "3 default roles (project_leader=can_write=1, team_leader=can_write=1, user=can_write=0) "
        "auto-seeded per project + per-node. "
        "v0.9.3 baseline role grant done.",
    ),
    (
        53,
        "Feature: Project Board",
        "done",
        "Sidebar tree + main detail (CSS sibling selector, no-JS). "
        "/projects/<id>/board?selected=<n> for v0.9.1 quick-add path. "
        "v0.9.3 _can_write_board 改走 role 路径.",
    ),
    (
        54,
        "Feature: Member List",
        "done",
        "GET /projects/<id>/members shows every member + self + change role dropdown "
        "(v0.9.3 2 段结构: 已添加角色 + 改为 dropdown) + change owner form (T0/T1 only) "
        "+ add member form (default rank 4). "
        "7/22 RBAC 业务级 lock 守.",
    ),
    (
        56,
        "Feature: Node Grant (role, per-node)",  # name 改: per-user -> role
        "archived",
        "v0.9.3 删 user-level grant surface. "
        "Only per-(role, node) can_write grant. "
        "project_custom_role_permissions 表 (custom_role_id, node_id, can_write). "
        "3 default roles auto-grant 每个节点 (project_leader=1, team_leader=1, user=0). "
        "/projects/<id>/nodes/<n>/permissions 端点 404 stub (preserve 49 routes 计数). "
        "feature_storage_node_permissions.py 物理删 (6 文件送回收站).",
    ),
    # ===== L4: 1 sub extended (role field deprecated 加 v0.9.3 注) =====
    (
        64,
        "Sub: role field deprecated",
        "done",
        "users.role is read-only legacy. Storage layer never writes it. "
        "v0.9.3 进一步: 删 project_node_permissions 表 + per-user grant 整套, "
        "完全走 role 路径.",
    ),
]


def main() -> int:
    if not DB.exists():
        print(f"DB not found: {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB))
    try:
        cur = conn.cursor()
        updated = 0
        for node_id, name, status, desc in UPDATES:
            # Verify project_id = 1
            row = cur.execute(
                "SELECT project_id FROM project_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if row is None:
                print(f"  WARN: node {node_id} not found", file=sys.stderr)
                continue
            if row[0] != 1:
                print(
                    f"  SKIP: node {node_id} belongs to project {row[0]}, not 1",
                    file=sys.stderr,
                )
                continue
            # Update
            cur.execute(
                "UPDATE project_nodes "
                "SET name = ?, status = ?, description = ?, updated_at = datetime('now') "
                "WHERE id = ? AND project_id = 1",
                (name, status, desc, node_id),
            )
            updated += 1
        conn.commit()
        print(f"OK: updated {updated} nodes in {DB}")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
