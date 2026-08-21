"""v0.7.3 mavis smoke: 新增项目限 T0/T1 (v0.7.2a revert)。

D-C create: T0 (admin) + T1 (manager) 才能 create project,
             T2 (project_leader) / T3 (team_leader) / T4 (user) = 403

8/7 02:31:09 user 拍 v0.7.2a revert: T2 拍板有风险, 老板/经理拍板才接受
"""

from __future__ import annotations

import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import sqlite3
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v055_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v055-mavis")

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


def _project_row(name):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT id, owner_id, project_type FROM projects WHERE name=?", (name,),
    ).fetchone()
    con.close()
    return row


# ===== T0-T4 login =====
admin = _login("kylins", "kylins123")
mgr   = _login("manager", "manager123")
pl    = _login("project_leader", "project_leader123")
tl    = _login("team_leader", "team_leader123")
_register("alice", "alice123")
alice = _login("alice", "alice123")
_step("T0-T4 login", all([admin, mgr, pl, tl, alice]))

# 备用 T2 (升到 project_leader, 作 owner 备选)
_register("pl1", "pl1123")
pl1_id = _user_row("pl1")[0]
client.post(f"/users/{pl1_id}/role", data={"new_role": "project_leader"},
            headers={"Cookie": admin}, follow_redirects=False)
pl1 = _login("pl1", "pl1123")
_step("pl1 升 T2", _user_row("pl1")[2] == 2)

# ===== D-C 新增项目矩阵 (T0/T1 = 302, T2/T3/T4 = 403) =====
# 5 role 创建矩阵
for who, cookie, name in [(admin, admin, "T0"),
                          (mgr, mgr, "T1"),
                          (pl, pl, "T2"),
                          (tl, tl, "T3"),
                          (alice, alice, "T4")]:
    r = client.post("/projects/new",
                    data={"name": f"new-{name}", "description": "test"},
                    headers={"Cookie": cookie}, follow_redirects=False)
    expected = 302 if name in ("T0", "T1") else 403
    _step(f"D-C: POST /projects/new {name} -> {expected}",
          r.status_code == expected, f"status={r.status_code}")

# ===== 备用 T2 升上来的 pl1 创建 -> 403 (v0.7.2a revert, T2 不行) =====
r = client.post("/projects/new",
                data={"name": "pl1-attempt", "description": "test"},
                headers={"Cookie": pl1}, follow_redirects=False)
_step("D-C: POST /projects/new pl1 (T2 升上来) -> 403 (T2 拒绝)",
      r.status_code == 403, f"status={r.status_code}")
_step("DB pl1-attempt 不存在", _project_row("pl1-attempt") is None,
      f"row={_project_row('pl1-attempt')}")

# ===== form owner 字段 (T0) =====
# T0 创建指定 owner=pl1 (T2)
r = client.post("/projects/new",
                data={"name": "with-owner", "description": "test", "owner_id": str(pl1_id)},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 POST name=with-owner owner_id=pl1 -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("with-owner owner 真是 pl1",
      _project_row("with-owner")[1] == pl1_id, f"row={_project_row('with-owner')}")

# pl1 (新 owner) 看到 with-owner
with_owner_id = _project_row("with-owner")[0]
r = client.get(f"/projects/{with_owner_id}", headers={"Cookie": pl1})
_step("pl1 (owner) GET /projects/<with-owner> -> 200",
      r.status_code == 200, f"status={r.status_code}")

# T1 创建指定 owner=pl1
r = client.post("/projects/new",
                data={"name": "with-owner-t1", "description": "test", "owner_id": str(pl1_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("T1 POST name=with-owner-t1 owner_id=pl1 -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# ===== T0 POST owner_id=99999 -> 200 + 错误 (form re-render) =====
r = client.post("/projects/new",
                data={"name": "bad-owner", "description": "test", "owner_id": "99999"},
                headers={"Cookie": admin})
body = r.get_data(as_text=True)
rejected = r.status_code == 200 and ("owner" in body.lower() or "not found" in body.lower())
_step("T0 POST owner_id=99999 -> 200 + error", rejected, f"status={r.status_code}")
_step("DB bad-owner 不存在", _project_row("bad-owner") is None,
      f"row={_project_row('bad-owner')}")

# ===== T0 POST owner_id=non-int -> 200 + 错误 =====
r = client.post("/projects/new",
                data={"name": "bad-owner-2", "description": "test", "owner_id": "abc"},
                headers={"Cookie": admin})
body = r.get_data(as_text=True)
rejected = r.status_code == 200 and ("integer" in body.lower() or "owner" in body.lower())
_step("T0 POST owner_id=abc -> 200 + error", rejected, f"status={r.status_code}")

# ===== system type 拒绝 (T0 试) =====
r = client.post("/projects/new",
                data={"name": "sys-attempt", "description": "test", "project_type": "system"},
                headers={"Cookie": admin})
_step("T0 POST project_type=system -> 400 (system 不可新建)",
      r.status_code == 400, f"status={r.status_code}")
_step("DB sys-attempt 不存在", _project_row("sys-attempt") is None,
      f"row={_project_row('sys-attempt')}")

# T0 POST project_type=user -> 302 (server 端忽略, 落 common)
r = client.post("/projects/new",
                data={"name": "user-type", "description": "test", "project_type": "user"},
                headers={"Cookie": admin}, follow_redirects=False)
_step("T0 POST project_type=user -> 302 (server 忽略)",
      r.status_code in (302, 303), f"status={r.status_code}")
_step("DB user-type project_type=common",
      _project_row("user-type")[2] == "common", f"type={_project_row('user-type')[2]}")

# ===== form 校验: name 空 =====
r = client.post("/projects/new",
                data={"name": "", "description": "x"},
                headers={"Cookie": admin})
body = r.get_data(as_text=True)
_step("T0 POST name='' -> 200 + error", r.status_code == 200, f"status={r.status_code}")

# ===== form 校验: name 太长 =====
r = client.post("/projects/new",
                data={"name": "x" * 201, "description": "x"},
                headers={"Cookie": admin})
body = r.get_data(as_text=True)
_step("T0 POST name 太长 -> 200 + error", r.status_code == 200, f"status={r.status_code}")

# ===== 重复 name =====
r = client.post("/projects/new",
                data={"name": "new-T0", "description": "x"},
                headers={"Cookie": admin}, follow_redirects=False)
r = client.post("/projects/new",
                data={"name": "new-T0", "description": "x"},
                headers={"Cookie": admin})
body = r.get_data(as_text=True)
_step("T0 POST 重复 name -> 200 + error", r.status_code == 200, f"status={r.status_code}")

# ===== /projects/new form 渲染: T0/T1 200, T2/T3/T4 403 =====
for label, cookie, expected in [("T0", admin, 200), ("T1", mgr, 200),
                                ("T2", pl, 403), ("T3", tl, 403),
                                ("T4", alice, 403)]:
    r = client.get("/projects/new", headers={"Cookie": cookie})
    _step(f"GET /projects/new {label} -> {expected}",
          r.status_code == expected, f"status={r.status_code}")

# ===== form 不含 project_type radio (v0.7.1 system/common 二分后) =====
r = client.get("/projects/new", headers={"Cookie": admin})
body = r.get_data(as_text=True)
no_user_radio = 'value="user"' not in body
no_system_radio = 'value="system"' not in body
_step("admin /projects/new form 不含 user radio",
      no_user_radio, f"no_user={no_user_radio}")
_step("admin /projects/new form 不含 system radio",
      no_system_radio, f"no_system={no_system_radio}")

# form 含 owner + name + description
has_owner = 'name="owner_id"' in body
has_name = 'name="name"' in body
has_desc = 'name="description"' in body
_step("admin /projects/new form 含 owner + name + description",
      has_owner and has_name and has_desc,
      f"owner={has_owner} name={has_name} desc={has_desc}")

# ===== D-C 与 v0.7.2a verify D 段一致: T2/T3/T4 创建 = 403 (已测) =====


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
