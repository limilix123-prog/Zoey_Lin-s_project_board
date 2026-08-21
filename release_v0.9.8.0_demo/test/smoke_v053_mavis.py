"""v0.7.3 mavis smoke: per-project role 概念 + add/remove T0/T1 拒绝 + 列表过滤。

v0.7 RBAC 重新设计核心:
  - T0 (admin) / T1 (manager) 是 auto-own, 不在 project_members 表
  - T2 (project_leader) 是 leader_role in project_members
  - T3 (team_leader) / T4 (user) 是 per-project role (project_members.role_in_project)

D-A add/remove: T0/T1 target -> 400 (auto-own, 不能 add/remove)
D-B list: 过滤 T0/T1 (auto-own, 不在 members 显示)
"""

from __future__ import annotations

import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import sqlite3
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v053_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v053-mavis")

_WORKSPACE = Path(r"C:\Users\lying\.minimax-agent-cn\projects")
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from project_board.app.feature_app_factory import create_app  # noqa: E402

app = create_app(run_seed=True)
client = app.test_client(use_cookies=False)

COOKIE = "pb_sid"
PASS = 0
FAIL = 0


def _step(label, ok, detail=""):
    global PASS, FAIL
    tag = "OK" if ok else "FAIL"
    print(f"  [{tag}] {label}" + (f"  -- {detail}" if detail else ""), flush=True)
    PASS += 1 if ok else 0
    FAIL += 0 if ok else 1


def _login(u, p):
    r = client.post("/login", data={"username": u, "password": p}, follow_redirects=False)
    assert r.status_code in (302, 303), f"login {u} {r.status_code}"
    return f"{COOKIE}={r.headers['Set-Cookie'].split(COOKIE + '=')[1].split(';', 1)[0]}"


def _register(u, p):
    r = client.post("/register", data={"username": u, "password": p}, follow_redirects=False)
    assert r.status_code in (302, 303), f"register {u} {r.status_code}"


def _user_row(name):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT id, username, role, rank FROM users WHERE username=?", (name,),
    ).fetchone()
    con.close()
    return row


def _project_row(name):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT id, name, project_type, owner_id FROM projects WHERE name=?", (name,),
    ).fetchone()
    con.close()
    return row


def _member_role(project_id, user_id):
    """Return the role name (joined from project_custom_roles) for a member.

    v0.9.1 (8/13 mavis) — the per-project role is now a
    FK into ``project_custom_roles`` (the single role table
    for both baseline and user-created roles). The
    ``role_in_project`` column is gone (replaced by
    ``custom_role_id``). The helper JOINs to surface the
    human-readable role name; ``None`` means either the
    member is not in ``project_members`` (row absent) or
    the member has the null role (``custom_role_id IS NULL``,
    the default after ``add_project_member``). Both
    situations return ``None`` so the call site can use
    ``is None`` as a "not assigned" check.
    """
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT cr.name FROM project_members pm "
        "LEFT JOIN project_custom_roles cr ON cr.id = pm.custom_role_id "
        "WHERE pm.project_id=? AND pm.user_id=?",
        (project_id, user_id),
    ).fetchone()
    con.close()
    return row[0] if row and row[0] is not None else None


def _is_member(project_id, user_id):
    """True iff a row exists in ``project_members`` for this (project, user).

    v0.9.1 (8/13 mavis) — separated from ``_member_role``
    because the post-merge "null role" case returns
    ``None`` from ``_member_role`` (the same as "not a
    member"); callers that want the membership check
    use this helper.
    """
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT 1 FROM project_members "
        "WHERE project_id=? AND user_id=? LIMIT 1",
        (project_id, user_id),
    ).fetchone()
    con.close()
    return row is not None


# ===== T0-T4 login =====
admin = _login("kylins", "kylins123")
mgr   = _login("manager", "manager123")
pl    = _login("project_leader", "project_leader123")
tl    = _login("team_leader", "team_leader123")
_register("alice", "alice123")
alice = _login("alice", "alice123")
_step("T0-T4 login", all([admin, mgr, pl, tl, alice]))

# 备用 T2 x2 (升到 project_leader)
_register("pl1", "pl1123")
pl1_id = _user_row("pl1")[0]
r = client.post(f"/users/{pl1_id}/role", data={"new_role": "project_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
assert r.status_code in (302, 303)
pl1 = _login("pl1", "pl1123")
_step("pl1 升 T2 (rank=2)", _user_row("pl1")[3] == 2)

_register("pl2", "pl2123")
pl2_id = _user_row("pl2")[0]
r = client.post(f"/users/{pl2_id}/role", data={"new_role": "project_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
assert r.status_code in (302, 303)
pl2 = _login("pl2", "pl2123")
_step("pl2 升 T2 (rank=2)", _user_row("pl2")[3] == 2)

# 备用 T3 (升到 team_leader, 用作 addable target)
_register("tl1", "tl1123")
tl1_id = _user_row("tl1")[0]
r = client.post(f"/users/{tl1_id}/role", data={"new_role": "team_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
assert r.status_code in (302, 303)
tl1 = _login("tl1", "tl1123")
_step("tl1 升 T3 (rank=3)", _user_row("tl1")[3] == 3)

# 备用 T4
_register("carol", "carol123")
carol_id = _user_row("carol")[0]
_step("carol T4 (rank=4)", _user_row("carol")[3] == 4)

# ===== T0/T1 创建 project (T2/T3/T4 已被 v0.7.2a revert 拒绝) =====
# 用 mgr 创建 alpha, owner=pl1 (T2 备用)
pl1_row = _user_row("pl1")
r = client.post("/projects/new",
                data={"name": "alpha", "description": "first", "owner_id": str(pl1_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
loc = r.headers.get("Location", "")
alpha_id = int(loc.rsplit("/", 1)[-1]) if "/projects/" in loc else None
_step("T1 (mgr) 创建 alpha owner=pl1 (T2)", alpha_id is not None, f"alpha_id={alpha_id}")

# system project
sys_id = _project_row("项目管理系统")[0]
_step("system project seed", sys_id is not None, f"sys_id={sys_id}")

# ===== T0/T1 auto-own: 看 alpha (任何 T0/T1) =====
for label, cookie in [("T0 (admin)", admin), ("T1 (mgr)", mgr)]:
    r = client.get(f"/projects/{alpha_id}", headers={"Cookie": cookie})
    _step(f"{label} GET /projects/<alpha> (auto-own) -> 200",
          r.status_code == 200, f"status={r.status_code}")

# ===== T2 (pl1, owner) 看 own project =====
r = client.get(f"/projects/{alpha_id}", headers={"Cookie": pl1})
_step("T2 (pl1 owner) GET /projects/<alpha> -> 200",
      r.status_code == 200, f"status={r.status_code}")

# T2 (project_leader seed, 不是 owner 不是 member) 看 alpha -> 404
r = client.get(f"/projects/{alpha_id}", headers={"Cookie": pl})
_step("T2 (pl seed, not owner/member) GET /projects/<alpha> -> 404",
      r.status_code == 404, f"status={r.status_code}")

# T3 看 alpha -> 404
r = client.get(f"/projects/{alpha_id}", headers={"Cookie": tl})
_step("T3 GET /projects/<alpha> -> 404", r.status_code == 404, f"status={r.status_code}")

# T4 (alice) 看 alpha -> 404
r = client.get(f"/projects/{alpha_id}", headers={"Cookie": alice})
_step("T4 (alice) GET /projects/<alpha> -> 404",
      r.status_code == 404, f"status={r.status_code}")

# ===== D-A add member: T0/T1 target -> 400 (auto-own, 不能 add) =====
# 尝试 admin add admin 自己 (kylins) -> 400
kylins_id = _user_row("kylins")[0]
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(kylins_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 actor add T0 target (kylins) -> 400",
      r.status_code == 400, f"status={r.status_code}")

# 尝试 admin add manager -> 400
mgr_id = _user_row("manager")[0]
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(mgr_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 actor add T1 target (manager) -> 400",
      r.status_code == 400, f"status={r.status_code}")

# 尝试 mgr add admin -> 400
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(kylins_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("D-A: T1 actor add T0 target -> 400",
      r.status_code == 400, f"status={r.status_code}")

# 尝试 mgr add mgr 自己 -> 400 (anti-self 优先, 但这里 400 即可)
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(mgr_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("D-A: T1 actor add T1 target (self) -> 400",
      r.status_code == 400, f"status={r.status_code}")

# 验证: T0/T1 真的没进 project_members 表
con = sqlite3.connect(_TMP_DB)
t01_in_members = con.execute(
    "SELECT COUNT(*) FROM project_members WHERE project_id=? AND user_id IN (?, ?)",
    (alpha_id, kylins_id, mgr_id),
).fetchone()[0]
con.close()
_step("D-A: T0/T1 真的没进 project_members 表 (count=0)",
      t01_in_members == 0, f"count={t01_in_members}")

# ===== D-A add: T2/T3/T4 target -> 302 (可加) =====
# T0 add T2 target (pl2)
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(pl2_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 add T2 target (pl2) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("D-A: pl2 added to project_members (T2 默认 null role, 备选 role 在 members 页面 set)",
      _is_member(alpha_id, pl2_id),
      f"role={_member_role(alpha_id, pl2_id)}")

# T0 add T3 target (tl1)
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(tl1_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 add T3 target (tl1) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T0 add T4 target (carol)
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(carol_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 add T4 target (carol) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T1 (mgr, auto-own) add T4 target (alice)
alice_id = _user_row("alice")[0]
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(alice_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("D-A: T1 add T4 target (alice) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T2 owner (pl1) add T4 target
_register("dan", "dan123")
dan_id = _user_row("dan")[0]
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(dan_id)},
                headers={"Cookie": pl1}, follow_redirects=False)
_step("D-A: T2 owner (pl1) add T4 target (dan) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T2 not-owner (project_leader seed) add -> 403
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(_user_row("kylins")[0])},
                headers={"Cookie": pl}, follow_redirects=False)
_step("D-A: T2 not-owner (pl seed) add -> 403",
      r.status_code == 403, f"status={r.status_code}")

# T3 add -> 403
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(_user_row("kylins")[0])},
                headers={"Cookie": tl}, follow_redirects=False)
_step("D-A: T3 add -> 403",
      r.status_code == 403, f"status={r.status_code}")

# T4 add -> 403
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(_user_row("kylins")[0])},
                headers={"Cookie": alice}, follow_redirects=False)
_step("D-A: T4 add -> 403",
      r.status_code == 403, f"status={r.status_code}")

# ===== Anti-self: T0 add 自己 -> 400 (cannot add self) =====
# 用 mgr add mgr 自己
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(mgr_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("Anti-self: T1 actor add self -> 400 (already covered above, re-verify)",
      r.status_code == 400, f"status={r.status_code}")

# ===== D-B list: T0/T1 不在 members list (SQL ground truth) =====
# D-A add 拒绝 T0/T1 target (已测), 所以 T0/T1 从未进 project_members。
# D-B list (view.html) 渲染时再用 _filter_auto_own_members 过滤残留 (v0.7.0 legacy)。
# 这里用 SQL 直接查 project_members, 避免 base.html nav 误匹配 current_username。
con = sqlite3.connect(_TMP_DB)
rows = con.execute(
    "SELECT u.username, u.role, u.rank FROM project_members pm "
    "JOIN users u ON u.id=pm.user_id "
    "WHERE pm.project_id=?", (alpha_id,),
).fetchall()
con.close()
member_names = [r[0] for r in rows]
has_t0 = "kylins" in member_names
has_t1 = "manager" in member_names
_step("D-B SQL: T0 (kylins) 不在 project_members (D-A 拒绝保证)",
      not has_t0, f"members={member_names}")
_step("D-B SQL: T1 (manager) 不在 project_members (D-A 拒绝保证)",
      not has_t1, f"members={member_names}")

# 5 个 add 进去的 user 应该都在
has_pl2 = "pl2" in member_names
has_tl1 = "tl1" in member_names
has_carol = "carol" in member_names
has_alice = "alice" in member_names
has_dan = "dan" in member_names
_step("D-B SQL: T2 (pl2) 在 project_members", has_pl2, f"members={member_names}")
_step("D-B SQL: T3 (tl1) 在 project_members", has_tl1, f"members={member_names}")
_step("D-B SQL: T4 (carol/alice/dan) 在 project_members",
      has_carol and has_alice and has_dan,
      f"members={member_names}")
_step("D-B SQL: members count = 5 (pl2, tl1, carol, alice, dan)",
      len(member_names) == 5, f"count={len(member_names)}")

# view.html 渲染时也过滤 T0/T1 (legacy v0.7.0 row 兜底)
r = client.get(f"/projects/{alpha_id}", headers={"Cookie": admin})
body = r.get_data(as_text=True)
# 准确检查: 在 <h2>Members</h2> 段内, 找 <code>{username}</code>
m_idx = body.find("<h2>Members</h2>")
if m_idx >= 0:
    m_end = body.find("<h2>", m_idx + 1)
    if m_end < 0:
        m_end = len(body)
    members_section = body[m_idx:m_end]
    no_t0_in_section = ">kylins<" not in members_section
    no_t1_in_section = ">manager<" not in members_section
    _step("D-B view: T0 不在 view.html Members 段",
          no_t0_in_section, f"section_len={len(members_section)}")
    _step("D-B view: T1 不在 view.html Members 段",
          no_t1_in_section, f"section_len={len(members_section)}")
else:
    # 没 Members 段 (members 列表为空时)
    _step("D-B view: Members 段渲染 (admin 视角)",
          True, "no Members section (empty list)")

# ===== member 现在能看 alpha =====
r = client.get(f"/projects/{alpha_id}", headers={"Cookie": pl2})
_step("T2 (pl2, member) GET /projects/<alpha> -> 200",
      r.status_code == 200, f"status={r.status_code}")

r = client.get(f"/projects/{alpha_id}", headers={"Cookie": alice})
_step("T4 (alice, member) GET /projects/<alpha> -> 200",
      r.status_code == 200, f"status={r.status_code}")

# ===== D-A remove: T0/T1 target -> 400 =====
# T0 remove T0 target (kylins) -> 400
r = client.post(f"/projects/{alpha_id}/members/{kylins_id}/remove",
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 remove T0 target -> 400",
      r.status_code == 400, f"status={r.status_code}")

# T0 remove T1 target (manager) -> 400
r = client.post(f"/projects/{alpha_id}/members/{mgr_id}/remove",
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 remove T1 target -> 400",
      r.status_code == 400, f"status={r.status_code}")

# ===== D-A remove: T2/T3/T4 target -> 302 (能 remove) =====
# T0 remove carol (T4) -> 302
r = client.post(f"/projects/{alpha_id}/members/{carol_id}/remove",
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 remove T4 target (carol) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("D-A: carol 真的从 project_members 消失",
      not _is_member(alpha_id, carol_id),
      f"role={_member_role(alpha_id, carol_id)}")

# T0 remove pl2 (T2) -> 302
r = client.post(f"/projects/{alpha_id}/members/{pl2_id}/remove",
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 remove T2 target (pl2) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T0 remove tl1 (T3) -> 302
r = client.post(f"/projects/{alpha_id}/members/{tl1_id}/remove",
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 remove T3 target (tl1) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# ===== Anti-self remove: T0/T1 actor remove self =====
# admin (T0, kylins) 不是 project_members (auto-own), 但 try remove self
r = client.post(f"/projects/{alpha_id}/members/{kylins_id}/remove",
                headers={"Cookie": admin}, follow_redirects=False)
_step("Anti-self remove: T0 actor remove self -> 400 (T0/T1 拒绝在前)",
      r.status_code == 400, f"status={r.status_code}")

# ===== Per-project role verify: T2 leader_role (v0.7.1 概念) =====
# 重新 add pl2 到 alpha
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(pl2_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("D-A: T0 re-add T2 pl2 -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("pl2 in project_members (T2 备选 leader)",
      _is_member(alpha_id, pl2_id),
      f"role={_member_role(alpha_id, pl2_id)}")


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
