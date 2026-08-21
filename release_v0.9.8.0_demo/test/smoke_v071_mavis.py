"""v0.9.7 mavis smoke: 21 P1 cases from verifier coverage audit (8/19).

Per 7/15 spec 守门, 每条 case 对应 1 个真实行为, 不凑数。
所有 case 来自 ``history/verifier_coverage_audit_v097p1_2026-08-19.md`` §4.2。
P-level: P1 重要 (挂账可发, 不阻塞 release)。

设计原则:
- 共享 helper 跟 smoke_v032_mavis.py 一致 (_step / _login / _register / _user_row)
- 不依赖 test/ 现有 helper — 自己写简化 helper
- 不依赖 project_board 内部 import — 只 import create_app (public entry) + rbac.feature_role primitives
- 不 race — project / user 名字用 v071- 前缀
- 副作用不清理 (临时 SQLite in TEMP)
- try/except 不兜底 — 任何错直接 raise
"""

from __future__ import annotations

import os
import re
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import unquote

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v071_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v071-mavis")

_WORKSPACE = Path(r"C:\Users\lying\.minimax-agent-cn\projects")
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from project_board.app.feature_app_factory import create_app  # noqa: E402
from project_board.accounts.feature_user_model import User  # noqa: E402
from project_board.rbac.feature_role import (  # noqa: E402
    ADMIN, MANAGER, PROJECT_LEADER, TEAM_LEADER, USER,
    _role_at_least,
)

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


def _user_id(name):
    row = _user_row(name)
    assert row is not None, f"user {name} not found"
    return int(row[0])


def _user(name):
    """Build a User instance from DB row (for _role_at_least)."""
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT id, username, password_hash, role, rank, created_at "
        "FROM users WHERE username=?", (name,),
    ).fetchone()
    con.close()
    assert row is not None, f"user {name} not found"
    # Build a sqlite3.Row-like object so User.from_row works.
    return User.from_row({
        "id": row[0],
        "username": row[1],
        "password_hash": row[2],
        "role": row[3],
        "rank": row[4],
        "created_at": row[5],
    })


# ===== Setup: 4 seed users login + 3 test user register =====
admin = _login("kylins", "kylins123")              # T0
mgr   = _login("manager", "manager123")            # T1
pl    = _login("project_leader", "project_leader123")  # T2
tl    = _login("team_leader", "team_leader123")    # T3

# v071-* prefix to avoid race with other workers using "alice"/"bob"
_register("v071_test_alice", "v071_alice_pw_123")   # T4
_register("v071_test_bob",   "v071_bob_pw_123")     # T4
_register("v071_test_charlie", "v071_charlie_pw_123")  # T4

alice = _login("v071_test_alice", "v071_alice_pw_123")
bob   = _login("v071_test_bob",   "v071_bob_pw_123")

# IDs
admin_id = _user_id("kylins")
alice_id = _user_id("v071_test_alice")
bob_id   = _user_id("v071_test_bob")
charlie_id = _user_id("v071_test_charlie")

# Create a project owned by admin (T0 can create; alice T4 cannot)
r = client.post(
    "/projects/new",
    data={
        "name": "v071-smoke-proj",
        "description": "P1 smoke test project",
        "owner_id": str(admin_id),
        "project_type": "common",
    },
    headers={"Cookie": admin},
    follow_redirects=False,
)
assert r.status_code in (302, 303), f"create project failed: {r.status_code}"
con = sqlite3.connect(_TMP_DB)
proj_id = con.execute("SELECT id FROM projects WHERE name=?", ("v071-smoke-proj",)).fetchone()[0]
con.close()

# Add bob to project (admin owner) — for case 11 (already) + case 13 (T2 not owner)
r = client.post(
    f"/projects/{proj_id}/members",
    data={"user_id": str(bob_id)},
    headers={"Cookie": admin},
    follow_redirects=False,
)
assert r.status_code in (302, 303), f"add bob to proj failed: {r.status_code}"


# =====================================================
# Case 1: smoke_register_get_001
# 场景: GET /register 200 + form 渲染
# 真实行为: 未登录用户访问注册表单, 拿到 200 + 渲染 form
# =====================================================
r = client.get("/register", follow_redirects=False)
body = r.get_data(as_text=True)
has_form = "<form" in body and 'name="username"' in body and 'name="password"' in body
_step(
    "smoke_register_get_001: GET /register 200 + form 渲染",
    r.status_code == 200 and has_form,
    f"status={r.status_code} has_form={has_form}",
)


# =====================================================
# Case 2: smoke_register_dup_001
# 场景: POST /register 重复 username → 409
# 真实行为: 重复用户名 (kylins 已存在) 触发 storage IntegrityError → 409 + error 渲染
# =====================================================
r = client.post(
    "/register",
    data={"username": "kylins", "password": "anypassword"},
    follow_redirects=False,
)
body = r.get_data(as_text=True) if r.status_code == 409 else b""
ok = r.status_code == 409 and ("already taken" in body or "username already" in body)
_step(
    "smoke_register_dup_001: POST /register 重复 username → 409 + error",
    ok,
    f"status={r.status_code}",
)


# =====================================================
# Case 3: smoke_register_validation_001
# 场景: POST /register username/password 长度边界 → 400
# 真实行为: 空 username / 空 password / >64 字符 username 都被 _validate 拒绝 → 400
# =====================================================
r1 = client.post("/register", data={"username": "", "password": "valid123"}, follow_redirects=False)
r2 = client.post("/register", data={"username": "validname", "password": ""}, follow_redirects=False)
r3 = client.post("/register", data={"username": "x" * 65, "password": "valid123"}, follow_redirects=False)
all_400 = r1.status_code == 400 and r2.status_code == 400 and r3.status_code == 400
_step(
    "smoke_register_validation_001: 3 长度边界 (空 user / 空 pw / >64 user) → 400",
    all_400,
    f"empty_user={r1.status_code} empty_pw={r2.status_code} long_user={r3.status_code}",
)


# =====================================================
# Case 4: smoke_login_get_001
# 场景: GET /login 200
# 真实行为: 未登录用户访问登录表单, 拿到 200 + 渲染 form
# =====================================================
r = client.get("/login", follow_redirects=False)
body = r.get_data(as_text=True)
has_form = "<form" in body and 'name="username"' in body and 'name="password"' in body
_step(
    "smoke_login_get_001: GET /login 200 + form",
    r.status_code == 200 and has_form,
    f"status={r.status_code} has_form={has_form}",
)


# =====================================================
# Case 5: smoke_login_401_001
# 场景: POST /login 错密码 / 不存在 user → 401
# 真实行为: 错密码 + 不存在 user 都触发同一路径 → 401 (避免 user enumeration)
# =====================================================
r1 = client.post("/login", data={"username": "kylins", "password": "wrong_password_xxx"}, follow_redirects=False)
r2 = client.post("/login", data={"username": "ghost_user_v071_xxx", "password": "any"}, follow_redirects=False)
ok = r1.status_code == 401 and r2.status_code == 401
_step(
    "smoke_login_401_001: 错密码/不存在 user → 401",
    ok,
    f"wrong_pw={r1.status_code} ghost={r2.status_code}",
)


# =====================================================
# Case 6: smoke_login_next_001
# 场景: POST /login ?next=//evil.example (开放重定向) 拒绝 + ?next=/me (合规) 接受
# 真实行为: _safe_next 防 //evil.example, 接受 /me
# =====================================================
r1 = client.post(
    "/login",
    data={"username": "kylins", "password": "kylins123", "next": "//evil.example/x"},
    follow_redirects=False,
)
loc1 = r1.headers.get("Location", "")
# 开放重定向拒绝: Location 不该含 evil.example
rejected_open_redirect = r1.status_code in (302, 303) and "evil.example" not in loc1

r2 = client.post(
    "/login",
    data={"username": "kylins", "password": "kylins123", "next": "/me"},
    follow_redirects=False,
)
loc2 = r2.headers.get("Location", "")
# 合规 next=/me 应该被保留
accepted_valid_next = r2.status_code in (302, 303) and (loc2.endswith("/me") or "/me?" in loc2)

_step(
    "smoke_login_next_001: 开放重定向拒绝 + 合规 next 接受",
    rejected_open_redirect and accepted_valid_next,
    f"open_loc={loc1!r} valid_loc={loc2!r}",
)


# =====================================================
# Case 7: smoke_login_cookie_001
# 场景: POST /login Set-Cookie HttpOnly + SameSite=Lax + Secure (按 config)
# 真实行为: feature_login 用 Flask set_cookie 设 HttpOnly + SameSite=Lax;
#          Secure 由 SESSION_COOKIE_SECURE config 决定 (config: false)
# =====================================================
r = client.post(
    "/login",
    data={"username": "kylins", "password": "kylins123"},
    follow_redirects=False,
)
set_cookie = r.headers.get("Set-Cookie", "")
has_httponly = "HttpOnly" in set_cookie
has_samesite = "SameSite=Lax" in set_cookie or "samesite=lax" in set_cookie.lower()
# config SESSION_COOKIE_SECURE=false, 所以 Secure 不该出现
no_secure = "Secure" not in set_cookie
_step(
    "smoke_login_cookie_001: HttpOnly + SameSite=Lax, Secure absent (config: false)",
    has_httponly and has_samesite and no_secure,
    f"httponly={has_httponly} samesite={has_samesite} secure_absent={no_secure} | {set_cookie[:120]}",
)


# =====================================================
# Case 8: smoke_logout_no_cookie_001
# 场景: POST /logout 无 cookie → 302 no-op
# 真实行为: feature_logout 看到没 cookie 也不报错, 直接 redirect (7/17 self-contained)
# =====================================================
r = client.post("/logout", follow_redirects=False)  # 无 cookie
# 也 delete cookie
_step(
    "smoke_logout_no_cookie_001: POST /logout 无 cookie → 302 no-op",
    r.status_code in (302, 303),
    f"status={r.status_code}",
)


# =====================================================
# Case 9: smoke_logout_405_001
# 场景: GET /logout → 405 (CSRF 防御, v0.9.7p1 改 abort(405))
# 真实行为: GET /logout 走 reject_get_logout → abort(405) → 中文 405 页
# =====================================================
r = client.get("/logout", follow_redirects=False)
body = r.get_data(as_text=True)
# 中文 405 error page (v0.9.5 P0-1/2 加的)
ok = r.status_code == 405
_step(
    "smoke_logout_405_001: GET /logout → 405 (CSRF 防御)",
    ok,
    f"status={r.status_code}",
)


# =====================================================
# Case 10: smoke_projects_list_001
# 场景: GET /projects 列表渲染 + 5 rank 视角
# 真实行为: admin 看到所有 (含 system); T4 看到 owned+membered; 都 200 + 含项目
# =====================================================
all_200 = True
all_have_h1 = True
for cookie, name in [(admin, "T0"), (mgr, "T1"), (pl, "T2"), (tl, "T3"), (alice, "T4")]:
    r = client.get("/projects", headers={"Cookie": cookie})
    if r.status_code != 200:
        all_200 = False
    body = r.get_data(as_text=True)
    if "<h1>项目</h1>" not in body:
        all_have_h1 = False
_step(
    "smoke_projects_list_001: 5 rank GET /projects → 200 + h1",
    all_200 and all_have_h1,
    f"all_200={all_200} all_h1={all_have_h1}",
)


# =====================================================
# Case 11: smoke_members_already_001
# 场景: POST /members 重复 → 302 + error query (already)
# 真实行为: storage.add_member 抛 IntegrityError (composite PK) → redirect ?error=already
# 注: verifier §4.2 描述"200 渲染", 实际是 302 redirect + error query (下面 GET 才是 200)
# =====================================================
r = client.post(
    f"/projects/{proj_id}/members",
    data={"user_id": str(bob_id)},
    headers={"Cookie": admin},
    follow_redirects=False,
)
loc = r.headers.get("Location", "")
ok = r.status_code in (302, 303) and "already" in loc.lower()
_step(
    "smoke_members_already_001: 重复 add → 302 + error=already",
    ok,
    f"status={r.status_code} loc={loc!r}",
)


# =====================================================
# Case 12: smoke_remove_not_member_001
# 场景: POST /remove 不在 member → 302 + error query (not a member)
# 真实行为: storage.remove_member 返回 False → redirect ?error=user is not a member
# =====================================================
r = client.post(
    f"/projects/{proj_id}/members/{charlie_id}/remove",
    headers={"Cookie": admin},
    follow_redirects=False,
)
loc = r.headers.get("Location", "")
loc_decoded = unquote(loc).lower()
ok = r.status_code in (302, 303) and "not a member" in loc_decoded
_step(
    "smoke_remove_not_member_001: 移除非成员 → 302 + error=not+a+member",
    ok,
    f"status={r.status_code} loc={loc!r}",
)


# =====================================================
# Case 13: smoke_remove_T2_not_owner_001
# 场景: POST /remove T2 not-owner → 403
# 真实行为: project_leader (T2) 不是 proj 的 owner 也不是 admin/manager → 403
# =====================================================
r = client.post(
    f"/projects/{proj_id}/members/{bob_id}/remove",
    headers={"Cookie": pl},
    follow_redirects=False,
)
_step(
    "smoke_remove_T2_not_owner_001: T2 not-owner remove → 403",
    r.status_code == 403,
    f"status={r.status_code}",
)


# =====================================================
# Case 14: smoke_rank_matrix_001
# 场景: 5x5 _role_at_least 矩阵显式测试 (25 case = 5 actor × 5 required)
# 真实行为: actor.rank <= required_rank (lower rank = higher authority)
# =====================================================
users_by_rank = {0: _user("kylins"), 1: _user("manager"), 2: _user("project_leader"),
                 3: _user("team_leader"), 4: _user("v071_test_alice")}
rank_for = {ADMIN: 0, MANAGER: 1, PROJECT_LEADER: 2, TEAM_LEADER: 3, USER: 4}
roles = [ADMIN, MANAGER, PROJECT_LEADER, TEAM_LEADER, USER]
all_ok = True
fail_detail = ""
for actor_rank in (0, 1, 2, 3, 4):
    actor = users_by_rank[actor_rank]
    for required in roles:
        result = _role_at_least(actor, required)
        expected = actor_rank <= rank_for[required]
        if result != expected:
            all_ok = False
            fail_detail = f"actor_rank={actor_rank} required={required} got={result} expected={expected}"
            break
    if not all_ok:
        break
_step(
    "smoke_rank_matrix_001: 5x5 _role_at_least 矩阵 (25 case 全对)",
    all_ok,
    fail_detail,
)


# =====================================================
# Case 15: smoke_sid_unique_001
# 场景: 连续 login 3 次 sid 不重复 (time.time_ns() 守门)
# 真实行为: feature_session._new_sid() 用 time.time_ns() 纳秒级, 3 次连续 sid 全不同
# =====================================================
sids = []
for _ in range(3):
    r = client.post(
        "/login",
        data={"username": "kylins", "password": "kylins123"},
        follow_redirects=False,
    )
    sc = r.headers.get("Set-Cookie", "")
    sid = sc.split(f"{COOKIE}=")[1].split(";", 1)[0]
    sids.append(sid)
all_unique = len(set(sids)) == 3
# 也验证 sessions 表里 admin 至少有 3 行
con = sqlite3.connect(_TMP_DB)
n_sessions = con.execute(
    "SELECT COUNT(*) FROM sessions WHERE user_id=?", (admin_id,),
).fetchone()[0]
con.close()
_step(
    "smoke_sid_unique_001: 3 sid 唯一 + sessions 表 ≥3 行",
    all_unique and n_sessions >= 3,
    f"unique={all_unique} n_sessions={n_sessions}",
)


# =====================================================
# Case 16: smoke_init_schema_idempotent_001
# 场景: 重启 create_app (同 DB) 无报错, 数据完整
# 真实行为: init_schema() 用 CREATE TABLE IF NOT EXISTS + OperationalError 守门;
#          第二次 create_app 同 DB 不报错 + users 表数据完整
# =====================================================
con = sqlite3.connect(_TMP_DB)
n_users_before = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
n_projects_before = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
con.close()
try:
    app2 = create_app(run_seed=False)  # 不跑 seeder, 只测 schema 幂等
    with app2.test_client() as c2:
        r = c2.get("/healthz")
        healthz_ok = r.status_code == 200
    con = sqlite3.connect(_TMP_DB)
    n_users_after = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    n_projects_after = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    con.close()
    data_intact = (n_users_after == n_users_before) and (n_projects_after == n_projects_before)
    _step(
        "smoke_init_schema_idempotent_001: 重启同 DB (run_seed=False) 无报错 + 数据完整",
        healthz_ok and data_intact,
        f"healthz={healthz_ok} users={n_users_before}->{n_users_after} "
        f"projects={n_projects_before}->{n_projects_after}",
    )
except Exception as exc:
    _step(
        "smoke_init_schema_idempotent_001: 重启同 DB 无报错",
        False,
        f"err={exc!r}",
    )


# =====================================================
# Case 17: smoke_user_view_admin_target_001
# 场景: GET /users/<admin_id> form 隐藏 (T2 actor 看 admin target)
# 真实行为: target_is_admin → form 隐藏 (admin 永久, 不能改)
# =====================================================
r = client.get(f"/users/{admin_id}", headers={"Cookie": pl})
body = r.get_data(as_text=True)
# form 隐藏 → 没有 <select name="new_rank">
no_form = 'name="new_rank"' not in body
_step(
    "smoke_user_view_admin_target_001: T2 看 admin target form 隐藏",
    no_form,
    f"no_select={no_form}",
)


# =====================================================
# Case 18: smoke_user_view_T2_T3_actor_001
# 场景: GET /users/<id> form whitelist (T2 看到 rank=3,4; T3 看到 rank=4)
# 真实行为: _available_new_ranks 决定 <select> option; T2=[3,4], T3=[4]
# =====================================================
# T2 (project_leader) 看 bob (T4, 不是自己, 不是 admin)
r1 = client.get(f"/users/{bob_id}", headers={"Cookie": pl})
body1 = r1.get_data(as_text=True)
opts_t2 = re.findall(r'<option value="(\d+)"', body1)
expected_t2 = {"3", "4"}
t2_ok = set(opts_t2) == expected_t2

# T3 (team_leader) 看 bob
r2 = client.get(f"/users/{bob_id}", headers={"Cookie": tl})
body2 = r2.get_data(as_text=True)
opts_t3 = re.findall(r'<option value="(\d+)"', body2)
expected_t3 = {"4"}
t3_ok = set(opts_t3) == expected_t3

_step(
    "smoke_user_view_T2_T3_actor_001: T2 看到 [3,4]; T3 看到 [4]",
    t2_ok and t3_ok,
    f"t2_opts={opts_t2} t3_opts={opts_t3}",
)


# =====================================================
# Case 19: smoke_seed_idempotent_001
# 场景: 4 seed users (admin/manager/PL/TL) 重启幂等 (不重复)
# 真实行为: 4 个 ensure_*_exists seeder 都是幂等 (find_by_username 先, 存在只更新密码)
# =====================================================
con = sqlite3.connect(_TMP_DB)
n_users_before = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
con.close()
app3 = create_app(run_seed=True)  # 跑 seeder
con = sqlite3.connect(_TMP_DB)
n_users_after = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
con.close()
# 期望: 7 users (4 seed + 3 test) → 重启后仍 7
_step(
    "smoke_seed_idempotent_001: 4 seed users 重启 (run_seed=True) 幂等",
    n_users_before == n_users_after,
    f"before={n_users_before} after={n_users_after}",
)


# =====================================================
# Case 20: smoke_profile_redirect_001
# 场景: GET /profile → 302 → /me (含 ?changed=1 forward)
# 真实行为: feature_routes.redirect_profile_to_me 走 302 + query string 转发
# =====================================================
r1 = client.get("/profile", headers={"Cookie": alice}, follow_redirects=False)
loc1 = r1.headers.get("Location", "")
ok_plain = r1.status_code in (302, 303) and loc1.endswith("/me")

r2 = client.get("/profile?changed=1", headers={"Cookie": alice}, follow_redirects=False)
loc2 = r2.headers.get("Location", "")
ok_changed = r2.status_code in (302, 303) and "changed=1" in loc2 and "me" in loc2

_step(
    "smoke_profile_redirect_001: /profile → 302 → /me (含 ?changed=1 forward)",
    ok_plain and ok_changed,
    f"plain_loc={loc1!r} changed_loc={loc2!r}",
)


# =====================================================
# Case 21: smoke_me_4_blocks_001
# 场景: GET /me 渲染 4 块 (account / change password / owned / member of)
# 真实行为: me.html 渲染 4 个 h2: 账户 / 更改密码 / 我的项目 / 我参与的项目
# =====================================================
r = client.get("/me", headers={"Cookie": alice})
body = r.get_data(as_text=True)
h2_count = body.count("<h2>")
ok_count = h2_count >= 4
ok_account = "账户" in body
ok_pw = "更改密码" in body
ok_owned = "我的项目" in body
ok_member = "我参与的项目" in body
_step(
    "smoke_me_4_blocks_001: /me 4 块 (账户/更改密码/我的项目/我参与的项目)",
    ok_count and ok_account and ok_pw and ok_owned and ok_member,
    f"h2={h2_count} account={ok_account} pw={ok_pw} owned={ok_owned} member={ok_member}",
)


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
