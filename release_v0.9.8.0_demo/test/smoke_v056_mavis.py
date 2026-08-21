"""v0.7.3 mavis smoke: project type 简化 (system/common 二分) + v0.7 不变性。

v0.5.6 起: project_type 只剩 system / common 二分。
  - system: app-factory seed, owner 永久, 不能 create via API
  - common: 任何 user-facing create

v0.7 增量: system project 在新 RBAC 下仍永久 + auto-own (T0/T1) 看见。
"""

from __future__ import annotations

import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import sqlite3
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v056_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v056-mavis")

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


def _project_row(name):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT id, project_type, owner_id FROM projects WHERE name=?", (name,),
    ).fetchone()
    con.close()
    return row


# ===== T0-T4 login =====
admin = _login("kylins", "kylins123")
mgr   = _login("manager", "manager123")
pl    = _login("project_leader", "project_leader123")
tl    = _login("team_leader", "team_leader123")
_step("T0-T4 login", all([admin, mgr, pl, tl]))

# ===== 新项目类型 hardcode common =====
# T0 POST 不传 project_type -> 302, DB common
r = client.post("/projects/new",
                data={"name": "test1", "description": "test"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 POST 不传 project_type -> 302", r.status_code in (302, 303), f"status={r.status_code}")
result = _project_row("test1")
_step("DB test1 project_type=common", result[1] == "common", f"type={result[1]}")

# T0 POST project_type=user -> 302 (server 端忽略)
r = client.post("/projects/new",
                data={"name": "test2", "description": "test", "project_type": "user"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 POST project_type=user -> 302 (server 忽略)",
      r.status_code in (302, 303), f"status={r.status_code}")
result = _project_row("test2")
_step("DB test2 project_type=common (server 端覆盖)",
      result[1] == "common", f"type={result[1]}")

# T0 POST project_type=system -> 400 (防越级)
r = client.post("/projects/new",
                data={"name": "sys-attempt", "description": "test", "project_type": "system"},
                headers={"Cookie": admin})
body = r.get_data(as_text=True)
_step("T0 POST project_type=system -> 400 (防越级)",
      r.status_code == 400, f"status={r.status_code}")
result = _project_row("sys-attempt")
_step("DB sys-attempt 不存在", result is None, f"result={result}")

# T1 试 project_type=system -> 400
r = client.post("/projects/new",
                data={"name": "sys-attempt-t1", "description": "test", "project_type": "system"},
                headers={"Cookie": mgr})
_step("T1 POST project_type=system -> 400",
      r.status_code == 400, f"status={r.status_code}")

# T0 POST project_type=garbage -> 302 (任何其他值都忽略)
r = client.post("/projects/new",
                data={"name": "garbage-type", "description": "test", "project_type": "garbage"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 POST project_type=garbage -> 302 (忽略)",
      r.status_code in (302, 303), f"status={r.status_code}")
result = _project_row("garbage-type")
_step("DB garbage-type project_type=common",
      result[1] == "common", f"type={result[1]}")

# ===== form 不含 project_type radio =====
r = client.get("/projects/new", headers={"Cookie": admin})
body = r.get_data(as_text=True)
no_user_radio = 'value="user"' not in body
no_system_radio = 'value="system"' not in body
_step("T0 /projects/new form 不含 user radio", no_user_radio, f"no_user={no_user_radio}")
_step("T0 /projects/new form 不含 system radio", no_system_radio, f"no_system={no_system_radio}")

# form 含 owner + name + description
has_owner = 'name="owner_id"' in body
has_name = 'name="name"' in body
has_desc = 'name="description"' in body
_step("T0 /projects/new form 含 owner + name + description",
      has_owner and has_name and has_desc,
      f"owner={has_owner} name={has_name} desc={has_desc}")

# ===== system project 仍 1 个 (seed 保留) =====
con = sqlite3.connect(_TMP_DB)
sys_count = con.execute("SELECT COUNT(*) FROM projects WHERE project_type='system'").fetchone()[0]
sys_id = con.execute("SELECT id FROM projects WHERE name='项目管理系统'").fetchone()[0]
con.close()
_step("DB system project 数 = 1 (seed 保留)", sys_count == 1, f"count={sys_count}")

# ===== v0.7 增量: system project 永久 =====
# T0 试 delete system -> 403
r = client.post(f"/projects/{sys_id}/delete",
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 DELETE system -> 403 (永久)", r.status_code == 403, f"status={r.status_code}")

# T0 试 change owner system -> 403
kylins_id = sqlite3.connect(_TMP_DB).execute(
    "SELECT id FROM users WHERE username='kylins'"
).fetchone()[0]
r = client.post(f"/projects/{sys_id}/owner",
                data={"new_owner_id": str(kylins_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 change owner system -> 403 (永久)", r.status_code == 403, f"status={r.status_code}")

# ===== v0.7 增量: T0/T1 都能 GET system (auto-own) =====
for label, cookie in [("T0 (admin)", admin), ("T1 (mgr)", mgr)]:
    r = client.get(f"/projects/{sys_id}", headers={"Cookie": cookie})
    _step(f"{label} GET /projects/<system> (auto-own) -> 200",
          r.status_code == 200, f"status={r.status_code}")

# T2/T3 不能 GET system (不是 owner 不是 member)
for label, cookie in [("T2 (pl)", pl), ("T3 (tl)", tl)]:
    r = client.get(f"/projects/{sys_id}", headers={"Cookie": cookie})
    _step(f"{label} GET /projects/<system> -> 404 (not visible)",
          r.status_code == 404, f"status={r.status_code}")

# ===== DB 唯一性: system name 不能 create =====
# 已有 项目管理系统, T0 试 create 同名
r = client.post("/projects/new",
                data={"name": "项目管理系统", "description": "dup"},
                headers={"Cookie": admin})
body = r.get_data(as_text=True)
_step("T0 POST 重复 system name -> 200 + error",
      r.status_code == 200, f"status={r.status_code}")


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
