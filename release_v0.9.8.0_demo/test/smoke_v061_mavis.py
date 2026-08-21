"""v0.7.3 mavis smoke: Feature Board + per-project role 检查。

v0.6.1: Feature Board (per-project kanban, 4 columns, 4-role CRUD)
v0.7.3 增量:
  - T0/T1 (auto-own) CRUD 任何 project
  - T2 (project_leader) 只 CRUD own project
  - T3 (team_leader) / T4 (user) 是 per-project role, 只能看 (read-only)
  - member 看见 board 但 CRUD = 403
"""

from __future__ import annotations

import os
import sqlite3
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v061_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v061-mavis")

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
        "SELECT id, project_type, owner_id FROM projects WHERE name=?", (name,),
    ).fetchone()
    con.close()
    return row


def _feature_row(project_id, name):
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT id, name, status FROM project_features "
        "WHERE project_id=? AND name=?",
        (project_id, name),
    ).fetchone()
    con.close()
    return row


def _create_project_via_form(cookie, name, owner_id):
    r = client.post(
        "/projects/new",
        data={"name": name, "description": "fb-test", "owner_id": str(owner_id)},
        headers={"Cookie": cookie},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), f"create {name} {r.status_code}"
    return int(r.headers.get("Location", "/").rsplit("/", 1)[-1])


# ===== T0-T4 login =====
admin = _login("kylins", "kylins123")
mgr   = _login("manager", "manager123")
pl    = _login("project_leader", "project_leader123")
tl    = _login("team_leader", "team_leader123")
_register("alice", "alice123")
alice = _login("alice", "alice123")
_register("bob", "bob123")
bob = _login("bob", "bob123")
_register("carol", "carol123")
carol_id = _user_row("carol")[0]
_step("T0-T4 + alice + bob + carol login",
      all([admin, mgr, pl, tl, alice, bob]))

# 备用 T2 (升到 project_leader 作 owner 备选)
_register("pl1", "pl1123")
pl1_id = _user_row("pl1")[0]
client.post(f"/users/{pl1_id}/role", data={"new_role": "project_leader"},
            headers={"Cookie": admin}, follow_redirects=False)
pl1 = _login("pl1", "pl1123")
_step("pl1 升 T2", _user_row("pl1")[2] == 2)

# 备用 T3
_register("tl1", "tl1123")
tl1_id = _user_row("tl1")[0]
client.post(f"/users/{tl1_id}/role", data={"new_role": "team_leader"},
            headers={"Cookie": admin}, follow_redirects=False)
tl1 = _login("tl1", "tl1123")
_step("tl1 升 T3", _user_row("tl1")[2] == 3)

# ===== setup: project_alpha owner=pl1 (T2), project_beta owner=carol (T4) =====
alpha_id = _create_project_via_form(mgr, "alpha", pl1_id)
beta_id = _create_project_via_form(mgr, "beta", carol_id)
_step("mgr 创建 alpha owner=pl1 (T2)", alpha_id is not None, f"alpha_id={alpha_id}")
_step("mgr 创建 beta owner=carol (T4)", beta_id is not None, f"beta_id={beta_id}")

# ===== project_features 表已建 =====
con = sqlite3.connect(_TMP_DB)
has_table = con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='project_features'"
).fetchone() is not None
con.close()
_step("DB project_features 表存在", has_table, f"has_table={has_table}")

# ===== T0 auto-own: 看 alpha features board (空) =====
r = client.get(f"/projects/{alpha_id}/features", headers={"Cookie": admin})
_step("T0 GET /projects/<alpha>/features (auto-own) -> 200",
      r.status_code == 200, f"status={r.status_code}")

# 4 列 kanban 砍掉后, 改成 6 层 sidebar 检查 (v0.9.1 sub-task 7+8).
# 旧 check: ">Backlog " / ">In progress " / ">Done " / ">Archived " 4 列 h3 header.
# 现 check: 6 层树 sidebar (board-layout + tree-nav + 项目树 + 节点详情),
# 且确保 4 列 kanban UI 不再渲染. 跨迭代必须清空/重审 v0.6.1 legacy
# (跟 7/31 "白名单是迭代级临时" 原则一致). 8/18 user 拍板 "按实际需求来"
# — board.html <h2> 是中文 "节点详情", smoke 期望从 "Node 详情" 改 "节点详情"
# 对齐 (7/17 self-contained UI 一致性).
body = r.get_data(as_text=True)
has_kanban_backlog = ">Backlog " in body
has_kanban_inprogress = ">In progress " in body
has_kanban_done = ">Done " in body
has_kanban_archived = ">Archived " in body
kanban_gone = not (has_kanban_backlog or has_kanban_inprogress or has_kanban_done or has_kanban_archived)
has_sidebar_class = 'class="board-layout"' in body
has_tree_nav_class = 'class="tree-nav"' in body
has_sidebar_title = "项目树" in body
has_main_title = "节点详情" in body
_step("4 列 kanban UI 不再渲染 (Backlog/In progress/Done/Archived 全 0)",
      kanban_gone,
      f"backlog_h3={has_kanban_backlog} inprogress_h3={has_kanban_inprogress} "
      f"done_h3={has_kanban_done} archived_h3={has_kanban_archived}")
_step("6 层 sidebar UI 渲染 (board-layout + tree-nav + 项目树 + 节点详情)",
      all([has_sidebar_class, has_tree_nav_class, has_sidebar_title, has_main_title]),
      f"board-layout={has_sidebar_class} tree-nav={has_tree_nav_class} "
      f"项目树={has_sidebar_title} 节点详情={has_main_title}")

# ===== T0/T1/T2 owner CRUD 矩阵 =====
# T0 POST add (auto-own) -> 302
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "admin-feat", "description": "added by admin"},
    headers={"Cookie": admin}, follow_redirects=False,
)
_step("T0 POST add admin-feat (auto-own) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T1 POST add (auto-own) -> 302
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "mgr-feat", "description": "added by manager"},
    headers={"Cookie": mgr}, follow_redirects=False,
)
_step("T1 POST add mgr-feat (auto-own) -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T2 owner (pl1) POST add -> 302
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "pl1-feat", "description": "owner added"},
    headers={"Cookie": pl1}, follow_redirects=False,
)
_step("T2 owner (pl1) POST add pl1-feat -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# T2 not-owner (pl seed) add -> 403
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "pl-bad", "description": "should fail"},
    headers={"Cookie": pl}, follow_redirects=False,
)
_step("T2 not-owner (pl seed) POST add -> 403",
      r.status_code == 403, f"status={r.status_code}")

# T3 add -> 403
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "tl-bad", "description": "should fail"},
    headers={"Cookie": tl}, follow_redirects=False,
)
_step("T3 POST add -> 403", r.status_code == 403, f"status={r.status_code}")

# T4 (bob, not member) add -> 403
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "bob-bad", "description": "should fail"},
    headers={"Cookie": bob}, follow_redirects=False,
)
_step("T4 (bob, not member) POST add -> 403",
      r.status_code == 403, f"status={r.status_code}")

# ===== empty name -> 302 error redirect =====
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "", "description": "no name"},
    headers={"Cookie": admin}, follow_redirects=False,
)
_step("empty name POST -> 302 redirect with error",
      r.status_code in (302, 303) and "error=" in r.headers.get("Location", ""),
      f"status={r.status_code} loc={r.headers.get('Location', '')}")

# ===== 3 features 都在 DB, 默认 backlog =====
con = sqlite3.connect(_TMP_DB)
counts = con.execute(
    "SELECT status, COUNT(*) FROM project_features WHERE project_id=? GROUP BY status",
    (alpha_id,),
).fetchall()
con.close()
all_backlog = all(c[0] == "backlog" for c in counts)
_step("3 features 都在 backlog (default)",
      len(counts) == 1 and counts[0][0] == "backlog" and counts[0][1] == 3,
      f"counts={counts}")

# ===== add alice (T4) to alpha as member =====
alice_id = _user_row("alice")[0]
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(alice_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("mgr add alice (T4) to alpha as member -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# add tl1 (T3) to alpha as member
r = client.post(f"/projects/{alpha_id}/members",
                data={"user_id": str(tl1_id)},
                headers={"Cookie": mgr}, follow_redirects=False)
_step("mgr add tl1 (T3) to alpha as member -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# ===== v0.7 增量: T3/T4 member GET board (read-only) =====
# alice (T4, member) GET board -> 200
r = client.get(f"/projects/{alpha_id}/features", headers={"Cookie": alice})
_step("T4 (alice, member) GET /projects/<alpha>/features -> 200 (read-only)",
      r.status_code == 200, f"status={r.status_code}")

# tl1 (T3, member) GET board -> 200
r = client.get(f"/projects/{alpha_id}/features", headers={"Cookie": tl1})
_step("T3 (tl1, member) GET /projects/<alpha>/features -> 200 (read-only)",
      r.status_code == 200, f"status={r.status_code}")

# 但 T3/T4 member 不能 add features
r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "alice-feat-bad", "description": "should fail"},
    headers={"Cookie": alice}, follow_redirects=False,
)
_step("T4 member (alice) POST add -> 403 (read-only)",
      r.status_code == 403, f"status={r.status_code}")

r = client.post(
    f"/projects/{alpha_id}/features",
    data={"name": "tl1-feat-bad", "description": "should fail"},
    headers={"Cookie": tl1}, follow_redirects=False,
)
_step("T3 member (tl1) POST add -> 403 (read-only)",
      r.status_code == 403, f"status={r.status_code}")

# bob (T4, not member) GET -> 404
r = client.get(f"/projects/{alpha_id}/features", headers={"Cookie": bob})
_step("T4 not-member (bob) GET /features -> 404",
      r.status_code == 404, f"status={r.status_code}")

# T2 not-owner (pl seed) GET -> 404
r = client.get(f"/projects/{alpha_id}/features", headers={"Cookie": pl})
_step("T2 not-owner (pl seed) GET /features -> 404",
      r.status_code == 404, f"status={r.status_code}")

# ===== 4 角色 GET 200 (T0/T1/T2 owner + T3/T4 member) =====
for label, ck in [("T0 (admin)", admin), ("T1 (mgr)", mgr),
                  ("T2 owner (pl1)", pl1), ("T3 member (tl1)", tl1),
                  ("T4 member (alice)", alice)]:
    r = client.get(f"/projects/{alpha_id}/features", headers={"Cookie": ck})
    _step(f"{label} GET /projects/<alpha>/features -> 200",
          r.status_code == 200, f"status={r.status_code}")

# ===== move: T0 move admin-feat to in_progress =====
admin_feat_id = _feature_row(alpha_id, "admin-feat")[0]
r = client.post(
    f"/projects/{alpha_id}/features/{admin_feat_id}/move",
    data={"status": "in_progress"},
    headers={"Cookie": admin}, follow_redirects=False,
)
_step("T0 POST move admin-feat -> in_progress -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
row = _feature_row(alpha_id, "admin-feat")
_step("DB admin-feat status=in_progress",
      row[2] == "in_progress", f"status={row[2]}")

# T3 member move -> 403
r = client.post(
    f"/projects/{alpha_id}/features/{admin_feat_id}/move",
    data={"status": "done"},
    headers={"Cookie": tl1}, follow_redirects=False,
)
_step("T3 member (tl1) POST move -> 403 (read-only)",
      r.status_code == 403, f"status={r.status_code}")

# T4 member move -> 403
r = client.post(
    f"/projects/{alpha_id}/features/{admin_feat_id}/move",
    data={"status": "done"},
    headers={"Cookie": alice}, follow_redirects=False,
)
_step("T4 member (alice) POST move -> 403 (read-only)",
      r.status_code == 403, f"status={r.status_code}")

# ===== invalid status -> 302 error redirect =====
r = client.post(
    f"/projects/{alpha_id}/features/{admin_feat_id}/move",
    data={"status": "garbage"},
    headers={"Cookie": admin}, follow_redirects=False,
)
_step("invalid status POST -> 302 redirect with error",
      r.status_code in (302, 303) and "error=" in r.headers.get("Location", ""),
      f"status={r.status_code} loc={r.headers.get('Location', '')}")

# ===== cross-project: move alpha's feature via beta's URL -> 404 =====
mgr_feat_id = _feature_row(alpha_id, "mgr-feat")[0]
r = client.post(
    f"/projects/{beta_id}/features/{mgr_feat_id}/move",
    data={"status": "done"},
    headers={"Cookie": mgr}, follow_redirects=False,
)
_step("cross-project move (alpha feature via beta URL) -> 404",
      r.status_code == 404, f"status={r.status_code}")

# ===== delete: T0 delete admin-feat -> 302 =====
r = client.delete(
    f"/projects/{alpha_id}/features/{admin_feat_id}",
    headers={"Cookie": admin}, follow_redirects=False,
)
_step("T0 DELETE admin-feat -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
row = _feature_row(alpha_id, "admin-feat")
_step("DB admin-feat 不存在 (deleted)", row is None, f"row={row}")

# T3 member delete -> 403
r = client.delete(
    f"/projects/{alpha_id}/features/{mgr_feat_id}",
    headers={"Cookie": tl1}, follow_redirects=False,
)
_step("T3 member (tl1) DELETE -> 403 (read-only)",
      r.status_code == 403, f"status={r.status_code}")

# T4 member delete -> 403
r = client.delete(
    f"/projects/{alpha_id}/features/{mgr_feat_id}",
    headers={"Cookie": alice}, follow_redirects=False,
)
_step("T4 member (alice) DELETE -> 403 (read-only)",
      r.status_code == 403, f"status={r.status_code}")

# T2 owner (pl1) delete -> 302
r = client.delete(
    f"/projects/{alpha_id}/features/{mgr_feat_id}",
    headers={"Cookie": pl1}, follow_redirects=False,
)
_step("T2 owner (pl1) DELETE mgr-feat -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")

# ===== CASCADE: delete alpha -> features 一起消失 =====
r = client.post(f"/projects/{alpha_id}/delete", headers={"Cookie": mgr},
                follow_redirects=False)
_step("T1 DELETE alpha project -> 302",
      r.status_code in (302, 303), f"status={r.status_code}")
con = sqlite3.connect(_TMP_DB)
remaining = con.execute(
    "SELECT COUNT(*) FROM project_features WHERE project_id=?", (alpha_id,),
).fetchone()[0]
con.close()
_step("CASCADE: alpha 删除后 features 一起消失",
      remaining == 0, f"remaining={remaining}")


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
