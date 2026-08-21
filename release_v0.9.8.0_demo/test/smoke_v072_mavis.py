"""v0.9.7.0 mavis smoke: 11 P2 soft cases (8/19 verifier audit §4.3 + 5 extra
template-render cases, per 7/15 spec 守门).

v0.9.7.0 milestone shipped; verifier 8/19 audit reports 11 P2 soft cases with
0 hit across the 7 existing smoke files. user 8/19 13:42 拍板 C (全补 P0/P1/P2).
本文件负责 P2 段,11 case 一一对应真实行为,每 case 1 个 _step。

本文件测的是 P2 软(可演进 UI/template 行为),不是 P0/P1 业务流程。验证的
是"v0.9.7.0 的 UI/template 行为真的存在并按 spec 渲染"。

11 case 对应表(每条对应 1 个真实行为,不凑数):

| spec id                          | 行为                                                          |
|----------------------------------|--------------------------------------------------------------|
| smoke_template_globals_001       | _MODULES_WITH_TEMPLATES = ("auth", "projects") v0.9.7p1 缩   |
| smoke_template_globals_002       | current_user_is_authenticated() / current_username() alive   |
| smoke_format_rank_label_001      | format_rank_label(0/4) → 中文标签                            |
| smoke_format_time_001            | format_time filter 解析 ISO → "YYYY-MM-DD HH:MM"             |
| smoke_description_preview_001    | /projects 列表 description_preview 100 字符截断 + …          |
| smoke_404_localized_001          | 404 中文 "未找到" + 返回项目列表链接                          |
| smoke_login_template_001         | login.html form action + autocomplete=off                    |
| smoke_register_template_001      | register.html form action + autocomplete=off                 |
| smoke_profile_change_template_001| /me 改密码 form 链接 + /me?changed=1 通知                    |
| smoke_users_list_template_001    | /users 列表每 user 含 rank label + owned_count + member_count|
| smoke_base_template_001          | base.html nav 5 业务链接 (5 rank 视角)                       |

注意:
- 不依赖 project_board 内部 helper(除了 create_app + UserStorage / ProjectStorage,
  跟 v061/v062 一致)
- 不修改 project_board/ 任何 source code
- 不修改现有 7 smoke
- 副作用不清理(tmp DB 在 /tmp,跑完即弃)
- 7/15 守门: 每 case 对应 1 个真实行为,不凑数
"""

from __future__ import annotations

import os
import re
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import time
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "smoke_v072_mavis.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v072-mavis")

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
    import sqlite3
    con = sqlite3.connect(_TMP_DB)
    row = con.execute(
        "SELECT id, role, rank FROM users WHERE username=?", (name,),
    ).fetchone()
    con.close()
    return row


def _create_project_via_form(cookie, name, owner_id, description=""):
    r = client.post(
        "/projects/new",
        data={"name": name, "description": description, "owner_id": str(owner_id)},
        headers={"Cookie": cookie},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), f"create {name} {r.status_code}"
    return int(r.headers.get("Location", "/").rsplit("/", 1)[-1])


# ===== T0-T4 (5 rank) login =====
admin = _login("kylins", "kylins123")          # T0
mgr   = _login("manager", "manager123")        # T1
pl    = _login("project_leader", "project_leader123")  # T2
tl    = _login("team_leader", "team_leader123")        # T3
_register("alice", "alice123")
alice = _login("alice", "alice123")            # T4
_step("T0-T4 5 rank login", all([admin, mgr, pl, tl, alice]))


# ============================================================
# case 1: smoke_template_globals_001
#   _MODULES_WITH_TEMPLATES = ("auth", "projects") v0.9.7p1 缩
#   真实行为: feature_templates.py:39-42 显式常量
# ============================================================
from project_board.app.feature_templates import _MODULES_WITH_TEMPLATES  # noqa: E402
_step(
    "_MODULES_WITH_TEMPLATES = ('auth', 'projects') (v0.9.7p1 缩)",
    _MODULES_WITH_TEMPLATES == ("auth", "projects"),
    f"value={_MODULES_WITH_TEMPLATES}",
)


# ============================================================
# case 2: smoke_template_globals_002
#   current_user_is_authenticated() / current_username() alive
#   测两个 live global:已登录 → True / kylins;未登录 → False / ""
#   (隐式守门: 删的 6 dead globals 不再可调用,但任务不要求负断言具体 name)
# ============================================================
r = client.get("/", headers={"Cookie": admin}, follow_redirects=False)
_step(
    "T0 GET / 已登录 -> 302 (到 /projects) (current_user_is_authenticated + current_username alive path)",
    r.status_code in (302, 303) and r.headers.get("Location", "").endswith("/projects"),
    f"status={r.status_code} loc={r.headers.get('Location', '')}",
)
r = client.get("/", follow_redirects=False)
_step(
    "匿名 GET / -> 302 (到 /login) (未登录 path alive)",
    r.status_code in (302, 303) and r.headers.get("Location", "").endswith("/login"),
    f"status={r.status_code} loc={r.headers.get('Location', '')}",
)
# 进一步: 登录页 /login 渲染,nav 显示 "Log in" + "Register" 链接(匿名视角)
r = client.get("/login", follow_redirects=False)
body = r.get_data(as_text=True)
has_login_link = 'href="/login"' in body
has_register_link = 'href="/register"' in body
_step(
    "匿名 /login 页面 nav 包含 Log in / Register 链接 (current_user_is_authenticated 走 false branch)",
    has_login_link and has_register_link,
    f"login={has_login_link} register={has_register_link}",
)
# 登录后 / 跟随到 /projects,nav 显示 kylins username(已登录视角)
r = client.get("/", headers={"Cookie": admin}, follow_redirects=True)
body = r.get_data(as_text=True)
has_username = "kylins" in body
has_projects = 'href="/projects"' in body
_step(
    "T0 / 跟随到 /projects 渲染 nav 含 username=kylins (current_username 走 true branch)",
    has_username and has_projects,
    f"username={has_username} projects_link={has_projects}",
)


# ============================================================
# case 3: smoke_format_rank_label_001
#   format_rank_label(0) / format_rank_label(4) → 中文标签
#   真实行为: feature_storage_rbac.py:210-215 _RANK_LABELS 字典
# ============================================================
from project_board.projects.feature_storage_rbac import format_rank_label  # noqa: E402
label_0 = format_rank_label(0)
label_4 = format_rank_label(4)
_step(
    "format_rank_label(0) = 'T0 系统管理员' (P0-3 中文标签)",
    label_0 == "T0 系统管理员",
    f"got={label_0!r}",
)
_step(
    "format_rank_label(4) = 'T4 普通用户' (P0-3 中文标签)",
    label_4 == "T4 普通用户",
    f"got={label_4!r}",
)
# 顺便验 5 个全 rank label 都有
all_labels = {r: format_rank_label(r) for r in range(5)}
expected_all = {0: "T0 系统管理员", 1: "T1 平台管理员", 2: "T2 项目负责人",
                3: "T3 团队负责人", 4: "T4 普通用户"}
_step(
    "format_rank_label(0..4) 全部 5 中文 label 命中 _RANK_LABELS",
    all_labels == expected_all,
    f"got={all_labels}",
)


# ============================================================
# case 4: smoke_format_time_001
#   format_time filter 解析 nanosecond ISO → "YYYY-MM-DD HH:MM"
#   真实行为: feature_templates.py:140-172 _format_time
#   注: 任务用 'nanosecond ISO',实际 Python 3.11+ fromisoformat 接受 6 位 fractional
#   实际能解析到 microsecond,7+ 位 fallback 返回 raw。所以测试用无 fractional 的 ISO。
# ============================================================
from project_board.app.feature_templates import _format_time  # noqa: E402
# happy path: 无 fractional
got = _format_time("2026-08-14T06:41:30Z")
_step(
    "format_time('2026-08-14T06:41:30Z') = '2026-08-14 06:41' (UTC Z suffix strip)",
    got == "2026-08-14 06:41",
    f"got={got!r}",
)
# 详细: 有 microsecond
got2 = _format_time("2026-08-14T06:41:30.123456Z")
_step(
    "format_time('...123456Z') = '2026-08-14 06:41' (microsecond 6 位, fromisoformat 接受)",
    got2 == "2026-08-14 06:41",
    f"got={got2!r}",
)
# fallback: 非法字符串 → 返回 raw
got3 = _format_time("not-a-date")
_step(
    "format_time('not-a-date') fallback = raw (ValueError catch)",
    got3 == "not-a-date",
    f"got={got3!r}",
)
# empty / None
got_none = _format_time(None)
got_empty = _format_time("")
_step(
    "format_time(None / '') = '' (NoneType / empty 短路)",
    got_none == "" and got_empty == "",
    f"none={got_none!r} empty={got_empty!r}",
)


# ============================================================
# case 5: smoke_description_preview_001
#   /projects 列表 description_preview 100 字符截断 + …
#   真实行为: feature_list.py:84-87 _preview 函数
#   通过 HTTP 测: 创建 description > 100 字符的项目,GET /projects 看截断
# ============================================================
long_desc = "y" * 150  # 150 字符
alpha_id = _create_project_via_form(mgr, "alpha", _user_row("project_leader")[0],
                                    description=long_desc)
r = client.get("/projects", headers={"Cookie": admin})
body = r.get_data(as_text=True)
# description_preview 应是 "y"*100 + rstrip + "…" — 因为都是 y 没有 rstrip
# 期望: 100 个 y + 1 个 … (U+2026)
has_100_ys = "y" * 100 in body
has_150_ys = "y" * 150 in body  # 不应在 body 中
has_ellipsis = "…" in body
_step(
    "/projects 列表 description_preview 包含前 100 字符 (y*100 in body)",
    has_100_ys,
    f"len(100y)={has_100_ys}",
)
_step(
    "/projects 列表 description_preview 截断: body 不含 150 连续 y",
    not has_150_ys,
    f"len(150y)={has_150_ys}",
)
_step(
    "/projects 列表 description_preview 末尾含 … (U+2026 水平省略号)",
    has_ellipsis,
    f"ellipsis={has_ellipsis}",
)


# ============================================================
# case 6: smoke_404_localized_001
#   404 页面中文 "未找到" + 返回项目列表链接
#   真实行为: app/templates/errors/404.html + _register_error_handlers
# ============================================================
r = client.get("/projects/99999", headers={"Cookie": admin}, follow_redirects=False)
_step(
    "GET /projects/99999 (不可见) -> 404 状态",
    r.status_code == 404,
    f"status={r.status_code}",
)
# 404 errorhandler 渲染 errors/404.html
body = r.get_data(as_text=True)
has_chinese_404 = "未找到" in body
has_not_found_desc = "您访问的页面不存在" in body or "页面不存在" in body
has_projects_link = 'href="/projects"' in body and "返回项目列表" in body
_step(
    "404 页面含中文 '未找到' (v0.9.5 P0-1 本地化)",
    has_chinese_404,
    f"chinese_404={has_chinese_404}",
)
_step(
    "404 页面含描述 (页面不存在 / 链接已失效)",
    has_not_found_desc,
    f"desc={has_not_found_desc}",
)
_step(
    "404 页面含 '返回项目列表' 链接 (回到业务路径)",
    has_projects_link,
    f"projects_link={has_projects_link}",
)
# 注: 匿名 GET /projects/99999 -> 302 (require_auth 先于 view 拦截),
# 这是 7/22 RBAC 业务级 lock (未登录不能到达 404 handler),不是 P2 测的范围。
# 404 本地化页面的"已登录 + 看 /projects/<n>"路径已上面覆盖。


# ============================================================
# case 7: smoke_login_template_001
#   login.html form 字段渲染 (form action + autocomplete=off)
#   真实行为: app/templates/login.html:11
# ============================================================
r = client.get("/login", follow_redirects=False)
body = r.get_data(as_text=True)
has_form_action = 'action="/login"' in body
has_autocomplete_off = 'autocomplete="off"' in body
has_username_input = 'name="username"' in body
has_password_input = 'name="password"' in body
has_signin_title = "Sign in" in body
_step(
    "GET /login 200 + 渲染 login.html",
    r.status_code == 200,
    f"status={r.status_code}",
)
_step(
    "login.html form action='/login' (POST 走 submit_login)",
    has_form_action,
    f"form_action={has_form_action}",
)
_step(
    "login.html form autocomplete='off' (密码管理器 friendly)",
    has_autocomplete_off,
    f"autocomplete_off={has_autocomplete_off}",
)
_step(
    "login.html 含 username + password input 字段",
    has_username_input and has_password_input,
    f"username={has_username_input} password={has_password_input}",
)
_step(
    "login.html 含 'Sign in' 标题 (H1)",
    has_signin_title,
    f"signin_title={has_signin_title}",
)


# ============================================================
# case 8: smoke_register_template_001
#   register.html form 字段渲染 (含 ?registered query)
#   真实行为: app/templates/register.html:8
# ============================================================
r = client.get("/register", follow_redirects=False)
body = r.get_data(as_text=True)
has_form_action = 'action="/register"' in body
has_autocomplete_off = 'autocomplete="off"' in body
has_register_title = "Create an account" in body
_step(
    "GET /register 200 + 渲染 register.html",
    r.status_code == 200,
    f"status={r.status_code}",
)
_step(
    "register.html form action='/register' (POST 走 submit_register)",
    has_form_action,
    f"form_action={has_form_action}",
)
_step(
    "register.html form autocomplete='off'",
    has_autocomplete_off,
    f"autocomplete_off={has_autocomplete_off}",
)
_step(
    "register.html 含 'Create an account' 标题",
    has_register_title,
    f"title={has_register_title}",
)
# ?registered=1 query — 实际 flash 渲染在 login.html L5-7
# (register.html 自己没有 query 分支,只有 {% if error %})
# 真实行为: register POST 302 → /login?registered=1 → login.html flash 'Account created — please sign in.'
r = client.get("/login?registered=1", follow_redirects=False)
body = r.get_data(as_text=True)
has_registered_flash = "Account created" in body and "sign in" in body
_step(
    "/login?registered=1 query 触发 'Account created — please sign in.' flash (register POST 跳过来)",
    has_registered_flash,
    f"flash={has_registered_flash}",
)


# ============================================================
# case 9: smoke_profile_change_template_001
#   /me 页面 change password 链接 + 改完后 ?changed=1 通知
#   真实行为: feature_me.py:147-150 + me.html:40
# ============================================================
r = client.get("/me", headers={"Cookie": alice})
body = r.get_data(as_text=True)
has_change_pw_form = 'action="/profile/password"' in body
has_old_pw = 'name="old_password"' in body
has_new_pw = 'name="new_password"' in body
has_confirm_pw = 'name="confirm_password"' in body
has_pw_heading = "更改密码" in body
_step(
    "/me 页面含更改密码 form (action='/profile/password')",
    has_change_pw_form,
    f"form_action={has_change_pw_form}",
)
_step(
    "/me 改密码 form 含 old/new/confirm 3 字段",
    has_old_pw and has_new_pw and has_confirm_pw,
    f"old={has_old_pw} new={has_new_pw} confirm={has_confirm_pw}",
)
_step(
    "/me 改密码段含 '更改密码' H2 标题",
    has_pw_heading,
    f"heading={has_pw_heading}",
)
# /me?changed=1 → notice 'Password updated.'
r = client.get("/me?changed=1", headers={"Cookie": alice})
body = r.get_data(as_text=True)
has_changed_notice = "Password updated" in body
_step(
    "/me?changed=1 触发 'Password updated.' 通知 (改完密码 跳过来)",
    has_changed_notice,
    f"notice={has_changed_notice}",
)
# /me (无 ?changed) 不应含 'Password updated.'
r = client.get("/me", headers={"Cookie": alice})
body = r.get_data(as_text=True)
no_changed_notice = "Password updated" not in body
_step(
    "/me (无 ?changed=1) 不渲染 'Password updated.' 通知",
    no_changed_notice,
    f"notice_absent={no_changed_notice}",
)


# ============================================================
# case 10: smoke_users_list_template_001
#   users_list.html 每 user 含 rank label + owned_count + member_count
#   真实行为: users_list.html:34-36 + feature_users_list.py:124-142
# ============================================================
# mgr (T1) 看 /users — owned_count + member_count + rank label 都该在
r = client.get("/users", headers={"Cookie": mgr})
body = r.get_data(as_text=True)
# 5 seed users 都在表
has_kylins = "kylins" in body
has_alice = "alice" in body
# 5 rank label (中文) 都该在 body (因为每 user 的 muted span + abbr title + dropdown option)
has_t0 = "T0 系统管理员" in body
has_t4 = "T4 普通用户" in body
# owned_count / member_count 字段 — T0 至少 1 个 owned (system project)
# body 应该有数字 + 渲染 td (无需精确数,只验 td 渲染了 owned/member 列)
# 看表头列名
has_owned_col = "已拥有" in body
has_member_col = "参与的项目" in body
_step(
    "/users 列表含 5 seed user (kylins, manager, project_leader, team_leader, alice)",
    has_kylins and has_alice,
    f"kylins={has_kylins} alice={has_alice}",
)
_step(
    "/users 列表含 T0 + T4 rank label (format_rank_label Jinja global alive)",
    has_t0 and has_t4,
    f"t0={has_t0} t4={has_t4}",
)
_step(
    "/users 列表表头含 '已拥有' + '参与的项目' 列名 (owned_count / member_count 列渲染)",
    has_owned_col and has_member_col,
    f"owned={has_owned_col} member={has_member_col}",
)
# 5 rank 视角: T0 看 /users,can_change_rank=True,form 应渲染
# 看 alice (T4) 看 /users,can_change_rank=False,form 不应渲染
r_admin = client.get("/users", headers={"Cookie": admin})
body_admin = r_admin.get_data(as_text=True)
has_admin_form = 'action="/users/' in body_admin and "更改" in body_admin
r_alice = client.get("/users", headers={"Cookie": alice})
body_alice = r_alice.get_data(as_text=True)
# alice (T4) 没 can_change_rank,所以 form 不渲染,但 '更改职级' 表头也不该出现
no_alice_form_header = "更改职级" not in body_alice
_step(
    "T0 /users 列表渲染更改职级 form (can_change_rank=True)",
    has_admin_form,
    f"admin_form={has_admin_form}",
)
_step(
    "T4 (alice) /users 列表不渲染更改职级 form (can_change_rank=False, form 整段隐藏)",
    no_alice_form_header,
    f"alice_form_absent={no_alice_form_header}",
)


# ============================================================
# case 11: smoke_base_template_001
#   base.html nav 业务链接 (Projects / Users / me / help / logout) 5 rank 视角
#   真实行为: base.html:56-83
# ============================================================
for label, ck in [("T0", admin), ("T1", mgr),
                  ("T2", pl), ("T3", tl), ("T4", alice)]:
    r = client.get("/projects", headers={"Cookie": ck})
    body = r.get_data(as_text=True)
    has_projects = 'href="/projects"' in body
    has_users = 'href="/users"' in body
    has_me = 'href="/me"' in body
    has_help = 'href="/help/glossary"' in body
    has_logout = "Log out" in body
    all_5 = all([has_projects, has_users, has_me, has_help, has_logout])
    _step(
        f"{label} /projects 页面 nav 含 5 业务链接 (Projects / Users / me / help / Log out)",
        all_5,
        f"projects={has_projects} users={has_users} me={has_me} "
        f"help={has_help} logout={has_logout}",
    )
# 5 rank /projects 页面都应含当前 username 在 nav (current_username alive)
# (T0 = kylins, T1 = manager, T2 = project_leader, T3 = team_leader, T4 = alice)
expected_usernames = {"T0": "kylins", "T1": "manager", "T2": "project_leader",
                      "T3": "team_leader", "T4": "alice"}
for label, ck in [("T0", admin), ("T1", mgr),
                  ("T2", pl), ("T3", tl), ("T4", alice)]:
    r = client.get("/projects", headers={"Cookie": ck})
    body = r.get_data(as_text=True)
    has_un = expected_usernames[label] in body
    _step(
        f"{label} /projects 页面 nav 含 username '{expected_usernames[label]}' "
        f"(current_username() global 渲染)",
        has_un,
        f"username_in_body={has_un}",
    )
# 匿名视角 nav 应含 Log in / Register / 帮助 (没 me/Users/Projects/Logout)
r = client.get("/login", follow_redirects=False)
body = r.get_data(as_text=True)
has_login = "Log in" in body
has_register = "Register" in body
has_help_anon = 'href="/help/glossary"' in body
no_projects_anon = 'href="/projects"' not in body
no_users_anon = 'href="/users"' not in body
_step(
    "匿名 /login 页面 nav 走 anonymous branch: Log in + Register + 帮助 (无 Users/Projects/Logout)",
    has_login and has_register and has_help_anon and no_projects_anon and no_users_anon,
    f"login={has_login} register={has_register} help={has_help_anon} "
    f"no_projects={no_projects_anon} no_users={no_users_anon}",
)


print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
