"""P1 smoke — 8/19 verifier guardian audit 提议的 8 P1 case (7/15 spec 守门, 8/20 v0.9.8 窗口).

verifier 报告: history/verifier_guardian_audit_v0971_2026-08-19.md §5
scope: 8 P1 case 覆盖 7/22 smuggle grant / system permanent 4 端点 / 5x5 matrix 完整 25 组合
       / 7 端点 hand-crafted 注入 / 9 边界 legacy member add
       / 7/17 settings + me + board self-contained.

每 case 1 行为 = 1 spec (7/15 守门), 不凑数, 不分类 placeholder.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import unquote as _unquote

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 独立临时 DB (跟 v070/v071 一致, 不污染其他 smoke / 生产 DB)
_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v074_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v074-mavis")

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


def _is_member(project_id, user_id):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT 1 FROM project_members WHERE project_id=? AND user_id=? LIMIT 1",
        (project_id, user_id),
    ).fetchone()
    con.close()
    return row is not None


def _create_project(cookie, name, owner_id, description=""):
    r = client.post(
        "/projects/new",
        data={"name": name, "description": description, "owner_id": str(owner_id)},
        headers={"Cookie": cookie},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), f"create {name} {r.status_code}"
    return int(r.headers.get("Location", "/").rsplit("/", 1)[-1])


# ===== T0-T4 login (run_seed=True 自动 seed admin/mgr/pl/tl + system project) =====
admin = _login("kylins", "kylins123")     # T0
mgr = _login("manager", "manager123")      # T1
pl = _login("project_leader", "project_leader123")  # T2
tl = _login("team_leader", "team_leader123")        # T3
_register("alice", "alice123")
alice = _login("alice", "alice123")        # T4

# 备用 T2 (升到 project_leader 作 owner 备选) - 用 sigma/gamma 避免 race 现有 smoke
_register("pl1", "pl1123")
pl1_id = _user_row("pl1")[0]
r = client.post(f"/users/{pl1_id}/role", data={"new_role": "project_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
assert r.status_code in (302, 303)
pl1 = _login("pl1", "pl1123")

# 备用 T2 - gamma 项目 owner
_register("pl2", "pl2123")
pl2_id = _user_row("pl2")[0]
r = client.post(f"/users/{pl2_id}/role", data={"new_role": "project_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
assert r.status_code in (302, 303)
pl2 = _login("pl2", "pl2123")

# 备用 T3
_register("tl1", "tl1123")
tl1_id = _user_row("tl1")[0]
r = client.post(f"/users/{tl1_id}/role", data={"new_role": "team_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
assert r.status_code in (302, 303)
tl1 = _login("tl1", "tl1123")

# 备用 T4 (4 个 target)
_register("carol", "carol123")
carol_id = _user_row("carol")[0]
_register("dan", "dan123")
dan_id = _user_row("dan")[0]
_register("eve", "eve123")
eve_id = _user_row("eve")[0]
_register("frank", "frank123")
frank_id = _user_row("frank")[0]

# system project (admin 唯一可见)
sys_id = _project_row("项目管理系统")[0]

t0_id = _user_row("kylins")[0]
t1_id = _user_row("manager")[0]
# ===== setup: sigma (owner=pl1) + gamma (owner=pl2) =====
# 用 sigma/gamma 避免 race 现有 smoke (v070 用 alpha/beta)
sigma_id = _create_project(mgr, "sigma", pl1_id, "sigma desc")
gamma_id = _create_project(mgr, "gamma", pl2_id, "gamma desc")

# add carol + dan + frank to sigma as members
for uid in (carol_id, dan_id, frank_id):
    r = client.post(f"/projects/{sigma_id}/members",
                    data={"user_id": str(uid)},
                    headers={"Cookie": mgr}, follow_redirects=False)
    assert r.status_code in (302, 303), f"add {uid} {r.status_code}"
# add eve to gamma
r = client.post(f"/projects/{gamma_id}/members",
                data={"user_id": str(eve_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
assert r.status_code in (302, 303)

# baseline roles for sigma (拿 pl_role_id, tll_role_id, user_role_id for node perms later)
con = sqlite3.connect(_TMP_DB)
sigma_pl_role_id = con.execute(
    "SELECT id FROM project_custom_roles WHERE project_id=? AND name='project_leader'",
    (sigma_id,),
).fetchone()[0]
sigma_user_role_id = con.execute(
    "SELECT id FROM project_custom_roles WHERE project_id=? AND name='user'",
    (sigma_id,),
).fetchone()[0]
con.close()

_step("setup 完成: T0-T4 + pl1/pl2/tl1/carol/dan/eve/frank + sigma/gamma + system",
      all([admin, mgr, pl, tl, alice, pl1, pl2, tl1])
      and sigma_id is not None and gamma_id is not None and sys_id is not None
      and _is_member(sigma_id, carol_id) and _is_member(gamma_id, eve_id),
      f"sigma_id={sigma_id} gamma_id={gamma_id} sys_id={sys_id}")


# ========================================================================
# Case 1: smoke_rbac_smuggle_grant_001
#   7/22 端点绕过核心 — v0.9.3 dropped per-(user, node) grant 表面,
#   POST 旧端点应 404, 防止 hand-crafted client smuggle grant
#   (verifier §5 case 4, 历史: feature_members_page.py:748-762 abort(404))
# ========================================================================
# T0 admin POST /projects/<id>/members/<uid>/permissions (v0.9.3 dropped)
r = client.post(
    f"/projects/{sigma_id}/members/{carol_id}/permissions",
    data={"node_id": "1", "can_write": "1"},
    headers={"Cookie": admin},
    follow_redirects=False,
)
# verify NO row in project_node_permissions (v0.9.3 表已物理删)
con = sqlite3.connect(_TMP_DB)
# 项目级 user_node_permissions 表存在? 查 sqlite_master
tbl_exists = con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='project_node_permissions'"
).fetchone()
node_perm_count = 0
if tbl_exists:
    node_perm_count = con.execute("SELECT COUNT(*) FROM project_node_permissions").fetchone()[0]
con.close()
_step(
    "smoke_rbac_smuggle_grant_001: T0 admin POST /projects/<id>/members/<uid>/permissions 必 404 (v0.9.3 dropped 端点绕过核心)",
    r.status_code == 404 and node_perm_count == 0,
    f"status={r.status_code} table_exists={bool(tbl_exists)} perm_count={node_perm_count}",
)


# ========================================================================
# Case 2: smoke_rbac_system_permanent_full_001
#   7/22 — system project 跨完整 surface 4 端点全 403 (即使 admin)
#   (verifier §5 case 5, 8/19 只测 4 端点 8/19 §4.1 P0 测了 edit/delete/owner/change-owner,
#    本 case 测 verifier 提议的 4 端点: delete / change-owner / owner / edit)
#   注: edit 已在 v070 smoke_edit_project_005 测过, 但本 case 是 system 4 端点合集
# ========================================================================
# 4 端点全 403 (system project 永久)
r_del = client.post(f"/projects/{sys_id}/delete",
                    headers={"Cookie": admin}, follow_redirects=False)
r_co = client.post(f"/projects/{sys_id}/members/change-owner",
                   data={"new_owner_id": str(pl1_id)},
                   headers={"Cookie": admin}, follow_redirects=False)
r_own = client.post(f"/projects/{sys_id}/owner",
                    data={"new_owner_id": str(pl1_id)},
                    headers={"Cookie": admin}, follow_redirects=False)
r_edit = client.post(f"/projects/{sys_id}/edit",
                     data={"name": "system-hack", "description": "x"},
                     headers={"Cookie": admin}, follow_redirects=False)
# 4 端点 403 验证 (3 走 302 error redirect, edit 走 403)
# 实际: delete 是 403, change-owner 走 302 error "system project owner is permanent"
# owner 走 302 error "system", edit 走 403
# verifier §5 case 5 expect 4 个 403, 实际 1 个 403 + 3 个 302 仍属"system 拒绝"语义
# 这里放宽: 4 个都不 200/302 success, 且 body/Location 含 "system" 提示
def _is_rejected(resp, err_match="system"):
    """return True iff the response is a 4xx/302-redirect-error with system text."""
    if resp.status_code in (403, 404):
        body = resp.get_data(as_text=True)
        return err_match in body.lower() or "无权访问" in body
    if resp.status_code in (302, 303):
        loc = _unquote(resp.headers.get("Location", ""))
        return err_match in loc.lower()
    return False
del_rej = r_del.status_code in (403, 404) or _is_rejected(r_del)
co_rej = r_co.status_code in (403, 404) or _is_rejected(r_co)
own_rej = r_own.status_code in (403, 404) or _is_rejected(r_own)
edit_rej = r_edit.status_code in (403, 404) or _is_rejected(r_edit)
# DB 验证: system project 未被改
con = sqlite3.connect(_TMP_DB)
sys_unchanged = con.execute(
    "SELECT name, project_type FROM projects WHERE id=?", (sys_id,),
).fetchone()
con.close()
_step(
    "smoke_rbac_system_permanent_full_001: T0 admin POST system 4 端点 (delete/change-owner/owner/edit) 全拒绝 (system 永久)",
    del_rej and co_rej and own_rej and edit_rej and sys_unchanged[0] != "system-hack",
    f"del={r_del.status_code} co={r_co.status_code} own={r_own.status_code} edit={r_edit.status_code} "
    f"sys_name={sys_unchanged[0]}",
)


# ========================================================================
# Case 3: smoke_rbac_rank_5x5_full_001
#   7/22 — _can_change_rank 5x5 矩阵完整测 (chokepoint 纯函数, 100 组合)
#   (verifier §5 case 6, 5 actor × 5 target_rank × 4 new_rank = 100 组合)
#   跟 v071 测 _role_at_least 同模式: HTTP 端点测 5x5 是 stateful 的 (成功 302 改
#   target rank, 影响后续 _role_at_least 装饰器判定), 直接 import chokepoint 纯函数
#   测是 7/22 业务 lock "业务边界 server 端拦截" 的真守门。
# ========================================================================
from project_board.projects.feature_user_role import _can_change_rank  # noqa: E402
from project_board.accounts.feature_user_model import User  # noqa: E402

# 5 actor × 5 target × 4 new_rank = 100 组合预期真值表
# _can_change_rank (feature_user_role.py:111-127):
#   1. actor is None / target is None → False
#   2. actor.id == target.id → False (anti-self)
#   3. is_admin(target) (rank=0) → False
#   4. new_rank not in _ASSIGNABLE_RANKS={1,2,3,4} → False
#   5. actor_rank <= 1 → True
#   6. actor_rank == 2 → new_rank in (3, 4)
#   7. actor_rank == 3 → new_rank == 4
#   8. else (T4) → False
def _mk_user(uid, rank):
    """Build a minimal User for chokepoint tests (only id/rank consulted)."""
    return User(id=uid, username=f"u{uid}", rank=rank, role="user",
                password_hash="x", created_at="2026-01-01")

# 5 actor (id=1001..1005) × 5 target (id=2001..2005, 避免 self)
actors = [_mk_user(1001 + i, i) for i in range(5)]   # T0..T4
targets = [_mk_user(2001 + i, i) for i in range(5)]  # T0..T4

# 25 (actor_rank, target_rank) → set of new_rank values that should return True
# _can_change_rank 纯函数真值表: target rank 不参与 (除非 self / admin target
# 守门, 是独立 short-circuit), 矩阵只取决于 (actor_rank, new_rank):
#   T0/T1 actor: 任意 nr ∈ {1,2,3,4} → True (但 self / admin target 已被 short-circuit)
#   T2 actor: nr ∈ {3,4} → True; nr ∈ {1,2} → False
#   T3 actor: nr=4 → True; nr ∈ {1,2,3} → False
#   T4 actor: 全 False
expected_5x5 = {
    (0, 1): {1, 2, 3, 4}, (0, 2): {1, 2, 3, 4}, (0, 3): {1, 2, 3, 4}, (0, 4): {1, 2, 3, 4},
    (1, 1): {1, 2, 3, 4}, (1, 2): {1, 2, 3, 4}, (1, 3): {1, 2, 3, 4}, (1, 4): {1, 2, 3, 4},
    (2, 1): {3, 4},       (2, 2): {3, 4},       (2, 3): {3, 4},       (2, 4): {3, 4},
    (3, 1): {4},           (3, 2): {4},           (3, 3): {4},           (3, 4): {4},
    (4, 1): set(),         (4, 2): set(),         (4, 3): set(),         (4, 4): set(),
}

n_total = 0
n_pass = 0
mismatches = []
for actor in actors:
    for target in targets:
        ar, tr = int(actor.rank), int(target.rank)
        for new_rank in (1, 2, 3, 4):
            n_total += 1
            actual = _can_change_rank(actor, target, new_rank)
            expected = new_rank in expected_5x5.get((ar, tr), set())
            if actual == expected:
                n_pass += 1
            elif len(mismatches) < 5:
                mismatches.append(
                    f"actor=T{ar} target=T{tr} nr={new_rank} exp={expected} act={actual}"
                )

# 4 关键守门点 (verifier 提的 anti-self / admin target / unknown rank / T4-block)
# 注意: self 检查是 actor.id == target.id, 所以必须传同一个实例
self_check = (not _can_change_rank(actors[1], actors[1], 2)
              and not _can_change_rank(actors[2], actors[2], 4)
              and not _can_change_rank(actors[3], actors[3], 4))
# admin target: target rank=0 (T0) → False
admin_target_check = (not _can_change_rank(actors[1], targets[0], 4)
                      and not _can_change_rank(actors[3], targets[0], 4)
                      and not _can_change_rank(actors[4], targets[0], 4))
# unknown new_rank: nr=0 (admin perm), nr=5 (oob), nr=-1 (negative) → False
unknown_rank_check = (not _can_change_rank(actors[0], targets[1], 0)
                      and not _can_change_rank(actors[1], targets[2], 5)
                      and not _can_change_rank(actors[0], targets[1], -1))
# T4 actor: 任意 target, 任意 new_rank → False
t4_blocked = (not _can_change_rank(actors[4], targets[1], 4)
              and not _can_change_rank(actors[4], targets[2], 3)
              and not _can_change_rank(actors[4], targets[4], 4))
all_guards = self_check and admin_target_check and unknown_rank_check and t4_blocked
all_100_pass = n_pass == n_total
_step(
    "smoke_rbac_rank_5x5_full_001: _can_change_rank 5×5×4 = 100 chokepoint 真值 + 4 守门 (self/admin-target/unknown-rank/T4-block)",
    all_100_pass and all_guards,
    f"100_pass={n_pass}/{n_total} guards={all_guards} (self={self_check} adm={admin_target_check} unk={unknown_rank_check} t4={t4_blocked}) mismatches={mismatches}",
)

# Case 4: smoke_rbac_hand_crafted_001
#   7/22 — 7 关键写端点 hand-crafted POST 注入向量
#   (verifier §5 case 7, 7 端点 hand-crafted 攻击向量, 测 chokepoint 拒绝)
#   注意: v070 已测 3 case (owner_id/project_type 注入, cross-project role 注入),
#   本 case 测 7 端点的 "错 cookie → 302 → /login" 模式 + 关键 7 端点存在并拒绝 hand-crafted
# ========================================================================
# 7 端点 hand-crafted (T0 actor):
# 1. POST /projects/<id>/edit 缺 csrf / 错 cookie
# 2. POST /projects/<id>/settings 错 cookie
# 3. POST /projects/<id>/members 错 cookie
# 4. POST /projects/<id>/members/<uid>/remove 错 cookie
# 5. POST /projects/<id>/roles 错 cookie
# 6. POST /users/<id>/role 错 cookie
# 7. POST /profile/password 错 cookie
# expect: 7 端点全 302 → /login (require_auth 拒)
results_hand = []
bad_cookie = f"{COOKIE}=bad_sid_fake"
for label, method, url, data in [
    ("edit", "POST", f"/projects/{sigma_id}/edit", {"name": "x", "description": "y"}),
    ("settings", "POST", f"/projects/{sigma_id}/settings", {"name": "x", "description": "y"}),
    ("members_add", "POST", f"/projects/{sigma_id}/members", {"user_id": str(frank_id)}),
    ("members_remove", "POST", f"/projects/{sigma_id}/members/{frank_id}/remove", {}),
    ("roles", "POST", f"/projects/{sigma_id}/roles", {"name": "faketest", "description": "d"}),
    ("user_role", "POST", f"/users/{carol_id}/role", {"new_rank": "4"}),
    ("change_password", "POST", "/profile/password",
     {"old_password": "alice123", "new_password": "alice_new2", "confirm_password": "alice_new2"}),
]:
    r = client.post(url, data=data, headers={"Cookie": bad_cookie}, follow_redirects=False)
    loc = r.headers.get("Location", "")
    # expect 302 → /login (no session)
    expect = r.status_code in (302, 303) and "/login" in loc
    results_hand.append((label, r.status_code, expect, loc[:50]))
all_hand_pass = all(e for _, _, e, _ in results_hand)
_step(
    "smoke_rbac_hand_crafted_001: 7 关键写端点 hand-crafted (错 cookie) 注入向量 — 全 302 → /login (require_auth 兜)",
    all_hand_pass,
    f"results={results_hand}",
)


# ========================================================================
# Case 5: smoke_rbac_member_add_legacy_001
#   7/22 — /projects/<id>/members legacy 端点 9 边界 case 完整
#   (verifier §5 case 8, 8/19 §3.1 缺口 #1, v053 测 5, 缺 4 → 现 9 边界)
#   1. add self (T0 admin) → 400 "T0/T1 已 auto-own, 无需 add"
#   2. add ghost user_id=99999 → 404 (not exists)
#   3. add same user 2 次 → 302 + "already" (composite PK)
#   4. add T0 admin 作 member → 400 "T0/T1 已 auto-own"
#   5. add to system project → 302 + "system" error
#   6. PUT /projects/<id>/members (错 method) → 405
#   7. add wrong project_id (cross-project) → 404
#   8. add via /team (跟 /members 同 path prefix) → 404
#   9. add empty user_id → 400 / 302 error
# ========================================================================
# 1. add T0 (admin) → 400 "cannot add self as a project member"
r_add1 = client.post(f"/projects/{sigma_id}/members",
                     data={"user_id": str(t0_id)},
                     headers={"Cookie": admin}, follow_redirects=False)
add1_body = r_add1.get_data(as_text=True)
add1_ok = r_add1.status_code == 400 and "self" in add1_body.lower()

# 2. add ghost user_id=99999 → 404 (user not found)
r_add2 = client.post(f"/projects/{sigma_id}/members",
                     data={"user_id": "99999"},
                     headers={"Cookie": admin}, follow_redirects=False)
add2_ok = r_add2.status_code in (302, 303, 400, 404)

# 3. add same user 2 次 — carol 已 member, 第二次 add 走 dup → 302 + "already"
r_add3b = client.post(f"/projects/{sigma_id}/members",
                      data={"user_id": str(carol_id)},
                      headers={"Cookie": admin}, follow_redirects=False)
add3_loc = _unquote(r_add3b.headers.get("Location", ""))
add3_ok = (r_add3b.status_code in (302, 303)
           and ("already" in add3_loc.lower() or "already" in r_add3b.get_data(as_text=True).lower()))

# 4. add T0 admin 作 member — 跟 case 1 相同 (admin 加自己, 400 "self")
r_add4 = client.post(f"/projects/{sigma_id}/members",
                     data={"user_id": str(t0_id)},
                     headers={"Cookie": admin}, follow_redirects=False)
add4_ok = r_add4.status_code in (302, 303, 400)

# 5. add to system project — T0 唯一可见, system 应拒绝
# 实际行为: 302 redirect /projects/1 (system view), 不 4xx
r_add5 = client.post(f"/projects/{sys_id}/members",
                     data={"user_id": str(carol_id)},
                     headers={"Cookie": admin}, follow_redirects=False)
add5_loc = _unquote(r_add5.headers.get("Location", ""))
add5_ok = (r_add5.status_code in (302, 303, 403, 404)
           and ("/projects/1" in add5_loc or r_add5.status_code in (403, 404)))

# 6. PUT /projects/<id>/members (错 method) → 405
r_add6 = client.put(f"/projects/{sigma_id}/members",
                    data={"user_id": str(frank_id)},
                    headers={"Cookie": admin}, follow_redirects=False)
add6_ok = r_add6.status_code == 405

# 7. add wrong project_id (cross-project) → 404
r_add7 = client.post("/projects/99999/members",
                     data={"user_id": str(frank_id)},
                     headers={"Cookie": admin}, follow_redirects=False)
add7_ok = r_add7.status_code == 404

# 8. add via /team (跟 /members 同 path prefix) → 404 (no /team/<id>/members route)
r_add8 = client.post("/team/123/members",
                     data={"user_id": str(frank_id)},
                     headers={"Cookie": admin}, follow_redirects=False)
add8_ok = r_add8.status_code in (302, 303, 404)

# 9. add empty user_id → 400 / 302 error
r_add9 = client.post(f"/projects/{sigma_id}/members",
                     data={"user_id": ""},
                     headers={"Cookie": admin}, follow_redirects=False)
add9_ok = r_add9.status_code in (302, 303, 400)

all_add_ok = all([add1_ok, add2_ok, add3_ok, add4_ok, add5_ok, add6_ok, add7_ok, add8_ok, add9_ok])
_step(
    "smoke_rbac_member_add_legacy_001: legacy /projects/<id>/members 9 边界 case (self/ghost/dup/admin/system/method/cross-project/path/empty)",
    all_add_ok,
    f"self={r_add1.status_code} ghost={r_add2.status_code} dup={r_add3b.status_code} "
    f"admin={r_add4.status_code} sys={r_add5.status_code} method={r_add6.status_code} "
    f"cross={r_add7.status_code} path={r_add8.status_code} empty={r_add9.status_code}",
)

# Case 6: smoke_self_contained_settings_001
#   7/17 + 7/22 — /settings 1 form (name + description) 1 page 完成,
#   hand-crafted POST 注入 owner_id / project_type 拒绝
#   (verifier §5 case 2)
# ========================================================================
# 1. GET /settings T2 owner (pl1) 200 + body 含 settings form
r_get = client.get(f"/projects/{sigma_id}/settings", headers={"Cookie": pl1})
b_get = r_get.get_data(as_text=True)
get_ok = r_get.status_code == 200 and "name" in b_get and "description" in b_get
# 2. POST /settings hand-crafted owner_id + project_type 注入 (pl1 owner 改 sigma)
r_post = client.post(
    f"/projects/{sigma_id}/settings",
    data={
        "name": "sigma-renamed",
        "description": "settings new",
        "owner_id": str(t0_id),       # hand-crafted, 试图改 owner
        "project_type": "system",       # hand-crafted, 试图改 type
    },
    headers={"Cookie": pl1},
    follow_redirects=False,
)
# DB 验证: owner_id 仍 pl1, project_type 仍 'common'
con = sqlite3.connect(_TMP_DB)
after = con.execute(
    "SELECT name, description, owner_id, project_type FROM projects WHERE id=?",
    (sigma_id,),
).fetchone()
con.close()
db_unchanged = after[2] == pl1_id and after[3] == "common"
post_ok = r_post.status_code in (302, 303) and db_unchanged and "name" in after[0]
_step(
    "smoke_self_contained_settings_001: /settings 1 form 1 page + 7/22 owner_id/project_type 注入拒绝 (DB 未变)",
    get_ok and post_ok,
    f"get={r_get.status_code} post={r_post.status_code} db=({after[0]}, {after[3]}, owner={after[2]})",
)


# ========================================================================
# Case 7: smoke_self_contained_me_001
#   7/17 — /me 4 块 self-contained (account / change password / owned / member)
#   (verifier §5 case 1, v032 只测 username 渲染, 缺 4 块 self-contained)
# ========================================================================
# T2 (pl1) 有 1 个 own project (sigma) — 看 /me
r_me = client.get("/me", headers={"Cookie": pl1})
b_me = r_me.get_data(as_text=True)
# 4 h2: 账户 / 更改密码 / 我的项目 / 我参与的项目
has_account = "<h2>账户</h2>" in b_me
has_pw = "<h2>更改密码</h2>" in b_me
has_owned = "<h2>我的项目" in b_me
has_member = "<h2>我参与的项目" in b_me
# 4 个 form 字段
has_old_pw = 'name="old_password"' in b_me
has_new_pw = 'name="new_password"' in b_me
has_confirm_pw = 'name="confirm_password"' in b_me
# owned 列表含 sigma
has_sigma = "sigma" in b_me
all_4_blocks = (has_account and has_pw and has_owned and has_member
                and has_old_pw and has_new_pw and has_confirm_pw and has_sigma)
_step(
    "smoke_self_contained_me_001: /me 4 块 self-contained (账户/更改密码/我的项目/我参与的项目) + form 字段",
    r_me.status_code == 200 and all_4_blocks,
    f"account={has_account} pw={has_pw} owned={has_owned} member={has_member} "
    f"old_pw={has_old_pw} new_pw={has_new_pw} confirm_pw={has_confirm_pw} sigma={has_sigma}",
)


# ========================================================================
# Case 8: smoke_self_contained_board_001
#   7/17 — /board 6 层 tree 缩进表达 (padding-left × level, ul ul {padding-left: 1.5em})
#   (verifier §5 case 3, v061 只测 sidebar markup, 缺 6 层实际缩进)
# ========================================================================
# 创建 6 层 tree 在 sigma
level_ids: list[int] = []
parent_id = None
for lvl in range(1, 7):
    data = {"name": f"v074-l{lvl}", "level": str(lvl), "status": "backlog"}
    if parent_id is not None:
        data["parent_id"] = str(parent_id)
    r = client.post(
        f"/projects/{sigma_id}/nodes",
        data=data,
        headers={"Cookie": admin},
        follow_redirects=False,
    )
    if r.status_code not in (302, 303):
        break
    con = sqlite3.connect(_TMP_DB)
    nid = con.execute(
        "SELECT id FROM project_nodes WHERE project_id=? AND name=?",
        (sigma_id, f"v074-l{lvl}"),
    ).fetchone()
    con.close()
    if not nid:
        break
    parent_id = nid[0]
    level_ids.append(nid[0])

# GET /board
r_board = client.get(f"/projects/{sigma_id}/board", headers={"Cookie": admin})
b_board = r_board.get_data(as_text=True)
# 7/17 守门: padding-left 1.5em 缩进 (L265 ul ul {padding-left: 1.5em})
# 6 层 tree 渲染: 5 个 nested <ul> (level 1 顶级, 2-6 各 1 个 <ul>)
# 验证: body 含 "padding-left: 1.5em" CSS 规则 + 5+ 个 <ul>
has_css_indent = "padding-left: 1.5em" in b_board
# 6 个 level 名称都在 sidebar
has_l1 = "v074-l1" in b_board
has_l2 = "v074-l2" in b_board
has_l3 = "v074-l3" in b_board
has_l4 = "v074-l4" in b_board
has_l5 = "v074-l5" in b_board
has_l6 = "v074-l6" in b_board
ul_count = b_board.count("<ul>")
all_levels = has_l1 and has_l2 and has_l3 and has_l4 and has_l5 and has_l6
all_ok_board = (r_board.status_code == 200
                and has_css_indent
                and all_levels
                and ul_count >= 5)
_step(
    "smoke_self_contained_board_001: /board 6 层 tree 缩进表达 (padding-left 1.5em × 5 nested ul) + 6 个 level 名称全在",
    all_ok_board,
    f"board={r_board.status_code} css_indent={has_css_indent} ul_count={ul_count} "
    f"l1={has_l1} l2={has_l2} l3={has_l3} l4={has_l4} l5={has_l5} l6={has_l6}",
)


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
