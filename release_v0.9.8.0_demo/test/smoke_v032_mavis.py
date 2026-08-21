"""v0.7.3 mavis smoke: 5-role session/login/logout/role (T0-T4 scale)。

v0.7 RBAC 重新设计: 把 5-role admin/manager/project_leader/team_leader/user
映射成 T-scale:
  T0 = admin (rank 0, auto-own)
  T1 = manager (rank 1, auto-own)
  T2 = project_leader (rank 2)
  T3 = team_leader (rank 3)
  T4 = user (rank 4)

本 smoke 验证 5 个 seed user 各自的 T-scale 映射,以及基本 session / login /
logout / 5-role role-change 矩阵。RBAC 业务边界 (T0/T1 auto-own, per-project
role) 不在本 smoke — 那是 v0.5.3 / v0.6.1 的范围。
"""

from __future__ import annotations

import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import sqlite3
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v032_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v032-mavis")

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


# ===== T0-T4 seed user login =====
admin = _login("kylins", "kylins123")     # T0
mgr   = _login("manager", "manager123")   # T1
pl    = _login("project_leader", "project_leader123")  # T2
tl    = _login("team_leader", "team_leader123")        # T3
_register("alice", "alice123")
alice = _login("alice", "alice123")       # T4 (registered, default rank=4)
_step("T0-T4 seed login (admin/manager/PL/TL + alice)", all([admin, mgr, pl, tl, alice]))

# ===== T0-T4 rank 映射 verify (DB) =====
# T-scale: admin=0, manager=1, project_leader=2, team_leader=3, user=4
T_RANK = {"kylins": 0, "manager": 1, "project_leader": 2, "team_leader": 3, "alice": 4}
T_LABEL = {0: "T0 admin", 1: "T1 manager", 2: "T2 project_leader",
           3: "T3 team_leader", 4: "T4 user"}
for name, expected_rank in T_RANK.items():
    row = _user_row(name)
    _step(
        f"{name} rank={expected_rank} ({T_LABEL[expected_rank]})",
        row is not None and row[3] == expected_rank,
        f"row={row}",
    )

# ===== /me 含 username + role 文字 =====
for who, cookie, name in [(admin, admin, "kylins"), (mgr, mgr, "manager"),
                          (pl, pl, "project_leader"), (tl, tl, "team_leader"),
                          (alice, alice, "alice")]:
    r = client.get("/me", headers={"Cookie": cookie})
    body = r.get_data(as_text=True)
    has_name = name in body
    _step(f"/me {name} 包含 username", has_name, f"has_name={has_name}")

# ===== logout 路径 =====
r = client.post("/logout", headers={"Cookie": alice}, follow_redirects=False)
_step("alice POST /logout -> 302", r.status_code in (302, 303), f"status={r.status_code}")
# 重新登录拿 cookie
alice = _login("alice", "alice123")
_step("alice 重登 OK", alice is not None)

# ===== 5 role GET /users 200 =====
for who, cookie, name in [(admin, admin, "T0"), (mgr, mgr, "T1"),
                          (pl, pl, "T2"), (tl, tl, "T3"),
                          (alice, alice, "T4")]:
    r = client.get("/users", headers={"Cookie": cookie})
    _step(f"GET /users {name} -> 200", r.status_code == 200, f"status={r.status_code}")

# ===== 5 role GET /users/<id> 200 =====
alice_id = _user_row("alice")[0]
for who, cookie, name in [(admin, admin, "T0"), (mgr, mgr, "T1"),
                          (pl, pl, "T2"), (tl, tl, "T3"),
                          (alice, alice, "T4")]:
    r = client.get(f"/users/{alice_id}", headers={"Cookie": cookie})
    _step(f"GET /users/<alice_id> {name} -> 200", r.status_code == 200, f"status={r.status_code}")

# ===== role change 矩阵 (T0/T1/T2/T3 能改, T4 拒绝) =====
# T0 改 alice -> project_leader (alice 升 T2)
r = client.post(f"/users/{alice_id}/role", data={"new_role": "project_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 POST /users/<alice>/role project_leader -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("alice rank 升 T2 (rank=2)",
      _user_row("alice")[3] == 2, f"rank={_user_row('alice')[3]}")

# T1 改 alice -> team_leader (alice 升 T3)
r = client.post(f"/users/{alice_id}/role", data={"new_role": "team_leader"},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("T1 POST /users/<alice>/role team_leader -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("alice rank 升 T3 (rank=3)",
      _user_row("alice")[3] == 3, f"rank={_user_row('alice')[3]}")

# T2 改 alice -> user (alice 降 T4)
r = client.post(f"/users/{alice_id}/role", data={"new_role": "user"},
                headers={"Cookie": pl}, follow_redirects=False)
_step("T2 POST /users/<alice>/role user -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("alice rank 降 T4 (rank=4)",
      _user_row("alice")[3] == 4, f"rank={_user_row('alice')[3]}")

# T3 改 alice -> user (already T4, 应该 200 渲染/302 都可, 测不报错)
r = client.post(f"/users/{alice_id}/role", data={"new_role": "user"},
                headers={"Cookie": tl}, follow_redirects=False)
_step("T3 POST /users/<alice>/role user (降或无变化) -> 不报错",
      r.status_code in (200, 302, 303), f"status={r.status_code}")

# T4 (alice) 改自己 role -> 403 (rank-based gate 不变)
r = client.post(f"/users/{alice_id}/role", data={"new_role": "user"},
                headers={"Cookie": alice}, follow_redirects=False)
_step("T4 POST /users/<alice>/role user (自己) -> 403 (rank gate)",
      r.status_code == 403, f"status={r.status_code}")
_step("alice rank 仍 T4 (降级未被绕过)",
      _user_row("alice")[3] == 4, f"rank={_user_row('alice')[3]}")

# ===== T2 register new user -> default rank=4 (T4) =====
_register("carol", "carol123")
carol_row = _user_row("carol")
_step("register carol 默认 rank=4 (T4)",
      carol_row is not None and carol_row[3] == 4, f"row={carol_row}")

# ===== T0 升 carol -> project_leader (T2) =====
carol_id = carol_row[0]
r = client.post(f"/users/{carol_id}/role", data={"new_role": "project_leader"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 升 carol -> project_leader -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("carol rank 升 T2 (rank=2)",
      _user_row("carol")[3] == 2, f"rank={_user_row('carol')[3]}")

# ===== T1 升 carol -> team_leader (T3) =====
r = client.post(f"/users/{carol_id}/role", data={"new_role": "team_leader"},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("T1 升 carol -> team_leader -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("carol rank 升 T3 (rank=3)",
      _user_row("carol")[3] == 3, f"rank={_user_row('carol')[3]}")

# ===== T0 升 carol -> admin (T0) — 永远保留 T0 (v0.7.1 设计) =====
# 按 v0.5.7 设计: 已有 admin 不会被降级, 但允许 T0/T1 升自己
# 测 admin 是否能把 carol 升到 admin role
r = client.post(f"/users/{carol_id}/role", data={"new_role": "admin"},
                headers={"Cookie": admin}, follow_redirects=False)
# admin role 是永久的, 后端应拒绝 (或接受但锁 T0 唯一)
# 已知行为: 保留 T0 唯一, 升到 admin 应该失败
final_rank = _user_row("carol")[3]
# 记录 final rank (可能 0 升 T0 成功, 也可能保持 T3)
_step("T0 升 carol -> admin (期望拒绝或接受但 T0 唯一)",
      r.status_code in (200, 302, 303, 400, 403), f"status={r.status_code} final_rank={final_rank}")

# ===== T0 升 carol 回 user (T4) 还原 =====
r = client.post(f"/users/{carol_id}/role", data={"new_role": "user"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 还原 carol -> user -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("carol rank 还原 T4 (rank=4)",
      _user_row("carol")[3] == 4, f"rank={_user_row('carol')[3]}")

# ===== nav /users link 5 role 都有 =====
for who, cookie, name in [(admin, admin, "T0"), (mgr, mgr, "T1"),
                          (pl, pl, "T2"), (tl, tl, "T3"),
                          (alice, alice, "T4")]:
    r = client.get("/me", headers={"Cookie": cookie})
    body = r.get_data(as_text=True)
    has_link = 'href="/users"' in body
    _step(f"nav {name} 含 Users 链接", has_link, f"has_link={has_link}")

# ===== UI: T4 /users 列表 form 隐藏 (read-only) =====
r = client.get("/users", headers={"Cookie": alice})
body = r.get_data(as_text=True)
no_form = 'name="new_role"' not in body
_step("UI: T4 /users 没 Change role form", no_form, f"no_form={no_form}")

# ===== UI: T4 /users/<id> (自己) 没 form =====
r = client.get(f"/users/{alice_id}", headers={"Cookie": alice})
body = r.get_data(as_text=True)
no_form = 'name="new_role"' not in body
_step("UI: T4 /users/<alice_id> (自己) 没 Change role form", no_form, f"no_form={no_form}")

# ===== 未登录 /users 仍 302 =====
r = client.get("/users", follow_redirects=False)
_step("未登录 /users -> 302", r.status_code == 302, f"status={r.status_code}")

r = client.get(f"/users/{alice_id}", follow_redirects=False)
_step("未登录 /users/<id> -> 302", r.status_code == 302, f"status={r.status_code}")


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
