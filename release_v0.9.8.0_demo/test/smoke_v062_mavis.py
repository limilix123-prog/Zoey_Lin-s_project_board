"""v0.7.3 mavis smoke: /team 端点 (retired + internal report chokepoint)。

v0.6.2: /team endpoints
  GET  /team                  — 任何登录 user 都能看 agent roster
  POST /team/_internal/report — copy-editor 通过 shared-secret 推 agent rows

v0.9.7 增量: GET /team 已退役 (302 → /projects)
  - 未登录 GET /team → 302 → /login
  - 登录 GET /team → 302 → /projects
  - nav 不再带 Team 链接 (5 rank nav 检查改成"无 Team 链接")
  - 5 分钟 cache 检查移除 (cache 已退役)
  - POST /team/_internal/report 行为不变 (copy-editor 上报路径完整)
agent_team_status 表内容不变 (mavis/architect/coder/verifier/general/copy-editor)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import time
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v062_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v062-mavis")
os.environ["COPY_EDITOR_SHARED_SECRET"] = "smoke-v062-shared-secret"

_WORKSPACE = Path(r"C:\Users\lying\.minimax-agent-cn\projects")
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from project_board.app.feature_app_factory import create_app  # noqa: E402

app = create_app(run_seed=True)
client = app.test_client(use_cookies=False)

COOKIE = "pb_sid"
SECRET = "smoke-v062-shared-secret"
PASS = 0
FAIL = 0

# 6 agents the copy-editor would report. Mix of statuses / task counts
# to exercise the badge mapping and the row count.
AGENT_REPORT = [
    {"agent_name": "mavis",       "description": "orchestrator + global RBAC gate",
     "status": "busy",    "task_count": 3},
    {"agent_name": "architect",   "description": "high-level system design",
     "status": "idle",    "task_count": 0},
    {"agent_name": "coder",       "description": "code implementation",
     "status": "busy",    "task_count": 2},
    {"agent_name": "verifier",    "description": "test case authoring + smoke harness",
     "status": "blocked", "task_count": 1},
    {"agent_name": "general",     "description": "fallback / unassigned work",
     "status": "idle",    "task_count": 0},
    {"agent_name": "copy-editor", "description": "docs + comments + team roster report",
     "status": "idle",    "task_count": 1},
]


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


def _agent_count():
    con = sqlite3.connect(_TMP_DB)
    n = con.execute("SELECT COUNT(*) FROM agent_team_status").fetchone()[0]
    con.close()
    return n


def _agent_row(name):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT agent_name, description, status, task_count, reported_by "
        "FROM agent_team_status WHERE agent_name=?",
        (name,),
    ).fetchone()
    con.close()
    return row


# ===== T0-T4 (5 rank) login =====
admin = _login("kylins", "kylins123")          # T0
mgr   = _login("manager", "manager123")        # T1
pl    = _login("project_leader", "project_leader123")  # T2
tl    = _login("team_leader", "team_leader123")        # T3
_register("alice", "alice123")
alice = _login("alice", "alice123")            # T4
_step("T0-T4 5 rank login", all([admin, mgr, pl, tl, alice]))

# 验证 rank 映射
T_RANK = {"kylins": 0, "manager": 1, "project_leader": 2, "team_leader": 3, "alice": 4}
for name, expected in T_RANK.items():
    _step(f"{name} rank={expected} (T{expected})",
          _user_row(name)[2] == expected, f"row={_user_row(name)}")

# ===== agent_team_status 表已建 =====
con = sqlite3.connect(_TMP_DB)
has_table = con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_team_status'"
).fetchone() is not None
con.close()
_step("DB agent_team_status 表存在 (init_schema 自动跑)",
      has_table, f"has_table={has_table}")

# ===== POST 401: 缺 secret =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps(AGENT_REPORT), content_type="application/json",
)
_step("POST 缺 X-Copy-Editor-Secret -> 401", r.status_code == 401, f"status={r.status_code}")

# ===== POST 401: 错 secret =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps(AGENT_REPORT), content_type="application/json",
    headers={"X-Copy-Editor-Secret": "wrong-secret"},
)
_step("POST 错 secret -> 401", r.status_code == 401, f"status={r.status_code}")

# ===== POST 401: env var 缺 =====
saved = os.environ.pop("COPY_EDITOR_SHARED_SECRET")
try:
    r = client.post(
        "/team/_internal/report",
        data=json.dumps(AGENT_REPORT), content_type="application/json",
        headers={"X-Copy-Editor-Secret": "anything"},
    )
    _step("env var 缺 -> 401", r.status_code == 401, f"status={r.status_code}")
finally:
    os.environ["COPY_EDITOR_SHARED_SECRET"] = saved

# ===== POST 400: payload 不是 array =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps({"agent_name": "mavis"}),
    content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
_step("POST payload 不是 array -> 400", r.status_code == 400, f"status={r.status_code}")

# ===== POST 400: 缺 agent_name =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps([{"description": "no name", "status": "idle", "task_count": 0}]),
    content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
_step("POST 缺 agent_name -> 400", r.status_code == 400, f"status={r.status_code}")

# ===== POST 400: 未知 status =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps([{"agent_name": "mavis", "status": "frozen", "task_count": 0}]),
    content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
_step("POST 未知 status -> 400", r.status_code == 400, f"status={r.status_code}")

# ===== POST 400: 负 task_count =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps([{"agent_name": "mavis", "status": "idle", "task_count": -1}]),
    content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
_step("POST 负 task_count -> 400", r.status_code == 400, f"status={r.status_code}")

# ===== POST 400: 非 int task_count =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps([{"agent_name": "mavis", "status": "idle", "task_count": "abc"}]),
    content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
_step("POST 非 int task_count -> 400", r.status_code == 400, f"status={r.status_code}")

# 验证上面 4 个 400 之后 DB 没被污染
_step("400 拒绝路径 DB 0 行", _agent_count() == 0, f"count={_agent_count()}")

# ===== POST 200: 6 agents 上报 =====
r = client.post(
    "/team/_internal/report",
    data=json.dumps(AGENT_REPORT), content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
body = r.get_json() or {}
_step("POST 6 agents -> 200", r.status_code == 200, f"status={r.status_code}")
_step("POST response count=6", body.get("count") == 6, f"body={body}")
_step("DB 6 行 agent_team_status", _agent_count() == 6, f"count={_agent_count()}")

# ===== 验证字段 =====
mavis_row = _agent_row("mavis")
_step("mavis status=busy", mavis_row[2] == "busy", f"status={mavis_row[2]}")
_step("mavis task_count=3", mavis_row[3] == 3, f"task_count={mavis_row[3]}")
_step("mavis reported_by=copy-editor", mavis_row[4] == "copy-editor",
      f"reported_by={mavis_row[4]}")
verifier_row = _agent_row("verifier")
_step("verifier status=blocked", verifier_row[2] == "blocked",
      f"status={verifier_row[2]}")

# ===== POST 200: 二次上报 UPSERT =====
updated = [
    {"agent_name": "mavis", "description": "updated", "status": "idle", "task_count": 5},
]
r = client.post(
    "/team/_internal/report",
    data=json.dumps(updated), content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
_step("二次上报 1 row -> 200", r.status_code == 200, f"status={r.status_code}")
mavis_row = _agent_row("mavis")
_step("mavis UPSERT 后 status=idle", mavis_row[2] == "idle", f"status={mavis_row[2]}")
_step("mavis UPSERT 后 task_count=5", mavis_row[3] == 5, f"task_count={mavis_row[3]}")
_step("mavis UPSERT 后 description=updated", mavis_row[1] == "updated",
      f"description={mavis_row[1]}")
_step("DB 仍 6 行 (UPSERT 不增)", _agent_count() == 6, f"count={_agent_count()}")

# ===== GET 302 / 未登录 → /login =====
r = client.get("/team", follow_redirects=False)
_step("GET 未登录 -> 302 (login or projects)",
      r.status_code in (302, 303),
      f"status={r.status_code}")

# ===== GET 302: T0 (admin) 登录 → /team 退役 → 302 → /projects =====
r = client.get("/team", headers={"Cookie": admin}, follow_redirects=False)
_step("T0 GET /team -> 302 (retired, -> /projects)",
      r.status_code in (302, 303), f"status={r.status_code}")
loc = r.headers.get("Location", "")
_step("T0 GET /team Location 指向 /projects", "/projects" in loc,
      f"location={loc}")

# ===== 5 rank GET /team 全部 302 (T0-T4 退役一致) =====
for label, ck in [("T0", admin), ("T1", mgr),
                  ("T2", pl), ("T3", tl), ("T4", alice)]:
    r = client.get("/team", headers={"Cookie": ck}, follow_redirects=False)
    _step(f"{label} GET /team -> 302 (retired)",
          r.status_code in (302, 303), f"status={r.status_code}")

# ===== 5 rank nav 不再有 Team 链接 (v0.9.7 nav 收尾) =====
for label, ck in [("T0", admin), ("T1", mgr),
                  ("T2", pl), ("T3", tl), ("T4", alice)]:
    r = client.get("/", headers={"Cookie": ck}, follow_redirects=True)
    body = r.get_data(as_text=True)
    has_link = 'href="/team"' in body
    _step(f"{label} nav 无 Team 链接 (v0.9.7 retired)",
          not has_link, f"has_link={has_link}")

# ===== 5 rank nav 仍保留 Projects / Users / Profile 链接 (sanity) =====
for label, ck in [("T0", admin), ("T1", mgr),
                  ("T2", pl), ("T3", tl), ("T4", alice)]:
    r = client.get("/", headers={"Cookie": ck}, follow_redirects=True)
    body = r.get_data(as_text=True)
    has_projects = 'href="/projects"' in body
    has_users = 'href="/users"' in body
    has_profile = 'href="/me"' in body
    _step(f"{label} nav 仍含 Projects / Users / Profile",
          has_projects and has_users and has_profile,
          f"projects={has_projects} users={has_users} profile={has_profile}")

# ===== POST /team/_internal/report 仍可写 (cache 退役后 upsert 行为不变) =====
client.post(
    "/team/_internal/report",
    data=json.dumps([{"agent_name": "mavis", "description": "updated",
                      "status": "busy", "task_count": 5}]),
    content_type="application/json",
    headers={"X-Copy-Editor-Secret": SECRET},
)
mavis_row = _agent_row("mavis")
_step("POST /team/_internal/report (cache retired 后) -> mavis status=busy",
      mavis_row[2] == "busy", f"status={mavis_row[2]}")
_step("POST /team/_internal/report -> mavis task_count=5",
      mavis_row[3] == 5, f"task_count={mavis_row[3]}")
_step("POST /team/_internal/report -> mavis description=updated",
      mavis_row[1] == "updated", f"description={mavis_row[1]}")

# ===== reported_by / description / reported_at 都进 DB =====
final = _agent_row("mavis")
_step("mavis final reported_by=copy-editor", final[4] == "copy-editor",
      f"reported_by={final[4]}")
_step("mavis final description=updated", final[1] == "updated",
      f"description={final[1]}")


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
