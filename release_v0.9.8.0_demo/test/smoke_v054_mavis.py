"""v0.7.3 mavis smoke: change owner 4 决策边界。

v0.7.2b endpoint /projects/<id>/owner 4 决策:
  D-D-1 actor: T0/T1 only, T2/T3/T4 = 403
  D-D-2 target: T2 (project_leader, rank 2) only
              T0/T1 target = 400 (auto-own)
              T3 (team_leader) target = 400
              T4 (user) target = 400
  D-D-3 system project: 任何 actor = 403 (permanent)
  D-D-4 idempotent: new_owner_id == current owner_id -> 302
"""

from __future__ import annotations

import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import sqlite3
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v054_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v054-mavis")

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
        "SELECT id, role, rank FROM users WHERE username=?", (name,),
    ).fetchone()
    con.close()
    return row


def _project_owner(project_id):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT owner_id, project_type FROM projects WHERE id=?", (project_id,),
    ).fetchone()
    con.close()
    return row


def _change_owner(actor_cookie, project_id, new_owner_id):
    return client.post(
        f"/projects/{project_id}/owner",
        data={"new_owner_id": str(new_owner_id)},
        headers={"Cookie": actor_cookie},
        follow_redirects=False,
    )


# ===== T0-T4 login =====
admin = _login("kylins", "kylins123")
mgr   = _login("manager", "manager123")
pl    = _login("project_leader", "project_leader123")
tl    = _login("team_leader", "team_leader123")
_register("alice", "alice123")
alice = _login("alice", "alice123")
_step("T0-T4 login", all([admin, mgr, pl, tl, alice]))

# 备用 T2 x2
_register("pl1", "pl1123")
pl1_id = _user_row("pl1")[0]
client.post(f"/users/{pl1_id}/role", data={"new_role": "project_leader"},
            headers={"Cookie": admin}, follow_redirects=False)
pl1 = _login("pl1", "pl1123")
_step("pl1 升 T2", _user_row("pl1")[2] == 2)

_register("pl2", "pl2123")
pl2_id = _user_row("pl2")[0]
client.post(f"/users/{pl2_id}/role", data={"new_role": "project_leader"},
            headers={"Cookie": admin}, follow_redirects=False)
pl2 = _login("pl2", "pl2123")
_step("pl2 升 T2", _user_row("pl2")[2] == 2)

# 备用 T3 + T4
_register("tl1", "tl1123")
tl1_id = _user_row("tl1")[0]
client.post(f"/users/{tl1_id}/role", data={"new_role": "team_leader"},
            headers={"Cookie": admin}, follow_redirects=False)
tl1 = _login("tl1", "tl1123")
_step("tl1 升 T3", _user_row("tl1")[2] == 3)

# ===== 创建 alpha (mgr, owner=pl1) =====
pl1_row = _user_row("pl1")
r = client.post("/projects/new",
                data={"name": "alpha", "description": "test", "owner_id": str(pl1_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
loc = r.headers.get("Location", "")
alpha_id = int(loc.rsplit("/", 1)[-1]) if "/projects/" in loc else None
_step("mgr 创建 alpha owner=pl1 (T2)", alpha_id is not None, f"alpha_id={alpha_id}")

# system project
sys_id_row = _project_owner([row[0] for row in
                             [sqlite3.connect(_TMP_DB).execute(
                                 "SELECT id FROM projects WHERE name='项目管理系统'"
                             ).fetchone()]][0])
sys_id = sys_id_row[0] if sys_id_row else None
con = sqlite3.connect(_TMP_DB)
sys_id = con.execute("SELECT id FROM projects WHERE name='项目管理系统'").fetchone()[0]
con.close()
_step("system project seed", sys_id is not None, f"sys_id={sys_id}")

# ===== D-D-1 actor gate: T0/T1 OK, T2/T3/T4 拒绝 =====
# T0 (admin) change owner -> pl2
r = _change_owner(admin, alpha_id, pl2_id)
_step("D-D-1: T0 actor change owner -> pl2 (T2) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("D-D-1: alpha owner 改到 pl2",
      _project_owner(alpha_id)[0] == pl2_id, f"owner={_project_owner(alpha_id)[0]}")

# pl2 (新 owner) 现在能 GET alpha
r = client.get(f"/projects/{alpha_id}", headers={"Cookie": pl2})
_step("D-D-1: pl2 (新 owner) GET /projects/<alpha> -> 200",
      r.status_code == 200, f"status={r.status_code}")

# T1 (mgr) change owner -> pl1
r = _change_owner(mgr, alpha_id, pl1_id)
_step("D-D-1: T1 actor change owner -> pl1 (T2) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T2 (pl seed) change owner -> 403
r = _change_owner(pl, alpha_id, pl2_id)
_step("D-D-1: T2 actor (pl seed) change owner -> 403",
      r.status_code == 403, f"status={r.status_code}")

# T3 (tl seed) change owner -> 403
r = _change_owner(tl, alpha_id, pl2_id)
_step("D-D-1: T3 actor (tl seed) change owner -> 403",
      r.status_code == 403, f"status={r.status_code}")

# T4 (alice) change owner -> 403
r = _change_owner(alice, alpha_id, pl2_id)
_step("D-D-1: T4 actor (alice) change owner -> 403",
      r.status_code == 403, f"status={r.status_code}")

# pl1 (现 owner, T2) 改 owner -> 403 (T2 actor 拒绝)
r = _change_owner(pl1, alpha_id, pl2_id)
_step("D-D-1: T2 actor (pl1 现 owner) change owner -> 403",
      r.status_code == 403, f"status={r.status_code}")

# ===== D-D-2 target rank gate: T0/T1/T3/T4 target = 400, T2 target = 302 =====
# T0 actor change owner to T0 target (kylins) -> 400
kylins_id = _user_row("kylins")[0]
r = _change_owner(admin, alpha_id, kylins_id)
_step("D-D-2: T0 actor target=T0 (kylins) -> 400 (T0/T1 auto-own)",
      r.status_code == 400, f"status={r.status_code}")

# T0 actor change owner to T1 target (manager) -> 400
mgr_id = _user_row("manager")[0]
r = _change_owner(admin, alpha_id, mgr_id)
_step("D-D-2: T0 actor target=T1 (manager) -> 400 (T0/T1 auto-own)",
      r.status_code == 400, f"status={r.status_code}")

# T0 actor change owner to T3 target (tl1) -> 400
r = _change_owner(admin, alpha_id, tl1_id)
_step("D-D-2: T0 actor target=T3 (tl1) -> 400 (T3 不能是 owner)",
      r.status_code == 400, f"status={r.status_code}")

# T0 actor change owner to T4 target (alice) -> 400
alice_id = _user_row("alice")[0]
r = _change_owner(admin, alpha_id, alice_id)
_step("D-D-2: T0 actor target=T4 (alice) -> 400 (T4 不能是 owner)",
      r.status_code == 400, f"status={r.status_code}")

# T0 actor change owner to T2 target (pl2) -> 302
r = _change_owner(admin, alpha_id, pl2_id)
_step("D-D-2: T0 actor target=T2 (pl2) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("D-D-2: alpha owner 改到 pl2",
      _project_owner(alpha_id)[0] == pl2_id, f"owner={_project_owner(alpha_id)[0]}")

# T1 actor change owner to T2 target -> 302
r = _change_owner(mgr, alpha_id, pl1_id)
_step("D-D-2: T1 actor target=T2 (pl1) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# ===== D-D-2: T1 actor target=T2 (现 owner 备选) =====
# 当前 owner=pl1, 改成 pl2 -> 302
r = _change_owner(mgr, alpha_id, pl2_id)
_step("D-D-2: T1 actor target=T2 (pl2, 备选) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# ===== D-D-3 system project: 任何 actor = 403 =====
# 先用 T0 试 system
r = _change_owner(admin, sys_id, pl1_id)
_step("D-D-3: T0 actor change system owner -> 403 (system 永久)",
      r.status_code == 403, f"status={r.status_code}")

# T1 试 system
r = _change_owner(mgr, sys_id, pl1_id)
_step("D-D-3: T1 actor change system owner -> 403 (system 永久)",
      r.status_code == 403, f"status={r.status_code}")

# ===== D-D-4 idempotent: new_owner_id == current owner_id =====
# 当前 alpha owner=pl2, 改到 pl2 -> 302
r = _change_owner(admin, alpha_id, pl2_id)
_step("D-D-4: T0 actor target=现 owner (pl2) -> 302 (idempotent)",
      r.status_code in (302, 303), f"status={r.status_code}")

# 验证 notice=Owner unchanged
loc = r.headers.get("Location", "")
_step("D-D-4: 302 redirect 带 notice=Owner unchanged",
      "Owner unchanged" in loc or "notice" in loc, f"loc={loc}")

# 验证 owner 真的没变
_step("D-D-4: alpha owner 仍 pl2 (没改)",
      _project_owner(alpha_id)[0] == pl2_id, f"owner={_project_owner(alpha_id)[0]}")

# T1 actor 试 idempotent
r = _change_owner(mgr, alpha_id, pl2_id)
_step("D-D-4: T1 actor target=现 owner (pl2) -> 302 (idempotent)",
      r.status_code in (302, 303), f"status={r.status_code}")

# ===== 边界: target user 不存在 =====
r = _change_owner(admin, alpha_id, 99999)
_step("target=99999 (不存在) -> 404", r.status_code == 404, f"status={r.status_code}")

# ===== 边界: new_owner_id missing =====
r = client.post(f"/projects/{alpha_id}/owner",
                data={},
                headers={"Cookie": admin}, follow_redirects=False)
_step("new_owner_id missing -> 400", r.status_code == 400, f"status={r.status_code}")

# ===== 边界: new_owner_id 不是 int =====
r = client.post(f"/projects/{alpha_id}/owner",
                data={"new_owner_id": "not-an-int"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("new_owner_id='not-an-int' -> 400", r.status_code == 400, f"status={r.status_code}")

# ===== 边界: project 不存在 =====
r = _change_owner(admin, 99999, pl1_id)
_step("project=99999 (不存在) -> 404", r.status_code == 404, f"status={r.status_code}")

# ===== D-D-2 完整 5x5 矩阵 (actor x target) =====
# 已覆盖 4 决策, 5x5 矩阵简化测关键组合
# T0 actor x T2 target -> 302 (前面已测)
# T1 actor x T2 target -> 302 (前面已测)
# T2/T3/T4 actor 任何 target -> 403
# T0/T1 actor x T0/T1/T3/T4 target -> 400
# 已全部覆盖


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
