"""Project detail endpoint.

GET /projects/<int:project_id>  — show name / description / owner + manage links

Read-side RBAC is enforced via :func:`user_can_see_project` (server-side,
not the template). Viewers that fail the check get a 404, not a 403, so
the URL does not leak the existence of a project they cannot see.

If the viewer is the owner OR an admin, the template renders a Delete
button that POSTs to /projects/<id>/delete. Non-owners do not see the
button (and would get 403 if they hand-crafted the request).

v0.7.2a — T0/T1 auto-own
------------------------
``user_can_see_project`` already short-circuits to True for T0/T1
(auto-own) via :func:`_is_auto_own`, so admin (T0) and manager (T1)
see every project without being a row in ``project_members``. The
``is_admin`` boolean used by the ``viewer_role`` label and the
:func:`can_manage_members` gate is now sourced from
:func:`_is_auto_own` so the cosmetic label matches the actual
auto-own authority (manager no longer shows up as ``"member"``).

The GET handler branches on the project type. A system project
(a row with ``project_type='system'``) renders ``system_view.html``
which is a re-skin of the self-status dashboard — every module
+ feature under ``project_root/project_board/`` is scanned and
displayed with a per-file cleanliness probe. A user project renders
the simplified ``view.html`` (name / description / owner / manage
links). The branch is server-side; the template only sees the
context for its branch.

v0.9.1 sub-task 4 — Issue 2: view endpoint simplified to a
project-info + manage-links surface. The 6-level node tree moved to
``/board`` (it already had a writable tree; the read-only copy was
duplicate). The member list + change owner form moved to
``/members``. The 7/17 self-contained守门 is satisfied by URL
design: every per-project action is reachable in one click from
view via the Manage links. The danger-zone (Delete project) form
stays on view because delete is project-scoped, not member-scoped.
The scan helpers (``_line_count_of`` ... ``_summary``) only run for
the system-project branch and are unchanged.

v0.9.1 sub-task 4 — Issue 4: nav hookup. The base template now
renders a per-project Members link whenever the ``project``
context var is set. View sets ``project`` on the template context
so the link surfaces on the page. Read-side 7/22 RBAC stays
unchanged.
"""

from __future__ import annotations

import ast
import logging
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, g, render_template, request

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_require_auth import require_auth as _require_auth  # noqa: E402
from .feature_storage import ProjectStorage, can_manage_members, user_can_see_project
from .feature_storage_rbac import _is_auto_own

logger = logging.getLogger(__name__)

bp = Blueprint("project_view", __name__)

# ---------------------------------------------------------------------------
# scan helpers
# ---------------------------------------------------------------------------

# Module names explicitly excluded from the scan. ``app/`` is the
# factory / config / routes glue and ``tools/`` lives outside
# ``project_board/``; both are out of scope for the dashboard.
_EXCLUDED_TOP_DIRS: frozenset[str] = frozenset({"__pycache__", "data", "tools"})

# Substring / pattern knobs for the static scan.
_FEATURE_PREFIX: str = "feature_"
_FEATURE_SUFFIX: str = ".py"
_README_SUFFIX: str = ".readme.md"
_MODULE_README: str = "readme.md"

# ``Blueprint("xxx", __name__)`` — the only place a feature advertises
# its endpoint name without touching the running app. The pattern
# matches both single-line and multi-line forms because the comma +
# whitespace is forgiving.
_BLUEPRINT_NAME_RE: re.Pattern[str] = re.compile(
    r"""Blueprint\(\s*['"](?P<name>[A-Za-z_][A-Za-z0-9_]*)['"]"""
)

# Subprocess knobs for the cleanliness probe.
_CLEAN_TOOL_REL: str = "tools/code_cleanliness_check.py"
_CLEAN_TIMEOUT_S: float = 5.0
_CLEAN_OK_RC: int = 0

# Display labels.
_OK: str = "clean"
_DIRTY: str = "dirty"
_UNKNOWN: str = "unknown"


def _project_root() -> Path:
    """Return the absolute workspace root (parent of the ``project_board`` package).

    The view is colocated with the package it scans, so the workspace
    root is fixed at three levels up from this file. The call to
    ``current_app.config.get`` is intentionally avoided because
    ``PB_CONFIG["DB_PATH"]`` may be an absolute path to an unrelated
    directory (tests, ephemeral temp DBs), which would not point at
    the source tree.
    """
    return Path(__file__).resolve().parent.parent.parent


def _package_root(project_root: Path) -> Path:
    """Return the absolute ``project_board/`` package root under ``project_root``."""
    return project_root / "project_board"


def _line_count_of(path: Path) -> int:
    """Physical line count, ``0`` when the file is empty / unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("system-view scan: cannot read %s: %s", path, exc)
        return 0
    if not text:
        return 0
    return len(text.splitlines())


def _extract_endpoint(path: Path) -> str:
    """Return the primary Flask endpoint (``<bp>.<view>``) for ``path``.

    Parses the file with ``ast`` to avoid executing it. Walks module
    assignments looking for the ``Blueprint("xxx", __name__)`` literal
    to get the blueprint name, then walks function definitions whose
    decorators reference that blueprint's ``.get`` / ``.post`` /
    ``.route`` / ``.put`` / ``.delete`` / ``.patch`` shortcut. Returns
    the first such view name as ``"<bp>.<view>"``. Falls back to the
    regex scan (returning only the blueprint name) when the AST has no
    usable structure. Returns ``""`` when no Blueprint is present so
    the template can render a non-link placeholder.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        tree = None
    bp_name = _bp_name_from_ast(tree) if tree is not None else ""
    if not bp_name:
        match = _BLUEPRINT_NAME_RE.search(text)
        bp_name = match.group("name") if match else ""
    if not bp_name or tree is None:
        return bp_name
    view_name = _first_view_name(tree, bp_name)
    if view_name:
        return f"{bp_name}.{view_name}"
    return bp_name


def _bp_name_from_ast(tree: ast.AST | None) -> str:
    """Return the blueprint name from a top-level ``bp = Blueprint("x", ...)``."""
    if tree is None:
        return ""
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != "bp":
            continue
        if not isinstance(node.value, ast.Call):
            continue
        first = node.value.args[0] if node.value.args else None
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
        ):
            return first.value
    return ""


def _first_view_name(tree: ast.AST, bp_name: str) -> str:
    """Return the name of the first function decorated with ``@bp.<verb>``.

    Walks every top-level function in the module looking for a
    decorator that calls ``bp.<verb>(...)`` where ``verb`` is one of
    Flask's route shortcut methods. Returns ``""`` when no such
    decorator exists. Module-level only — nested functions and class
    methods are skipped because none of the project's view functions
    are nested.
    """
    if tree is None or not isinstance(tree, ast.Module):
        return ""
    shortcuts = {"get", "post", "put", "delete", "patch", "route"}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            func = deco.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "bp"
                and func.attr in shortcuts
            ):
                return node.name
    return ""


def _clean_status(path: Path, workspace: Path) -> str:
    """Probe ``code_cleanliness_check.py --path <file> --quiet`` for one file.

    Returns ``clean`` (rc=0), ``dirty`` (rc!=0), or ``unknown`` on any
    subprocess / filesystem exception. The 5-second timeout keeps one
    pathological file from hanging the page; the dashboard stays
    responsive even when the tool itself fails.
    """
    cmd = [
        sys.executable,
        _CLEAN_TOOL_REL,
        "--path", str(path),
        "--quiet",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=_CLEAN_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as exc:
        logger.info("system-view clean probe timeout/err %s: %s", path, exc)
        return _UNKNOWN
    return _OK if proc.returncode == _CLEAN_OK_RC else _DIRTY


def _module_readme_status(module_dir: Path) -> bool:
    return (module_dir / _MODULE_README).is_file()


def _feature_readme_status(feature_py: Path) -> bool:
    return feature_py.with_name(feature_py.stem + _README_SUFFIX).is_file()


@lru_cache(maxsize=1)
def _scan_project(project_root: Path) -> list[dict[str, Any]]:
    """Walk ``project_root/project_board/`` and return per-module dicts.

    Each module dict carries:

    * ``name`` — directory name
    * ``path`` — absolute path string
    * ``readme_present`` — whether ``<module>/readme.md`` exists
    * ``features`` — list of feature dicts (possibly empty)

    v0.9.1 sub-task 6 — performance P0: the function is wrapped with
    ``@lru_cache(maxsize=1)`` so the per-feature ``code_cleanliness``
    subprocess (44 features × ~85ms = ~3.8s) runs at most once per
    process. ``_project_root()`` is stable for the lifetime of the
    process (it is anchored to this file's location, not
    ``current_app.config``), so the cache key is effectively a
    constant. Process restart is the documented way to force a
    refresh after a deploy that adds a new feature file.
    """
    pkg = _package_root(project_root)
    if not pkg.is_dir():
        return []
    modules: list[dict[str, Any]] = []
    for module_dir in sorted(p for p in pkg.iterdir() if p.is_dir()):
        if module_dir.name in _EXCLUDED_TOP_DIRS:
            continue
        if module_dir.name.startswith("__"):
            continue
        feature_rows: list[dict[str, Any]] = []
        for py in sorted(module_dir.glob(_FEATURE_PREFIX + "*" + _FEATURE_SUFFIX)):
            if not py.is_file():
                continue
            feature_rows.append(
                {
                    "name": py.stem[len(_FEATURE_PREFIX):],
                    "path": str(py),
                    "line_count": _line_count_of(py),
                    "readme_present": _feature_readme_status(py),
                    "endpoint": _extract_endpoint(py),
                    "clean_status": _clean_status(py, project_root),
                }
            )
        modules.append(
            {
                "name": module_dir.name,
                "path": str(module_dir),
                "readme_present": _module_readme_status(module_dir),
                "features": feature_rows,
            }
        )
    return modules


# v0.9.1 sub-task 6 — pre-warm the scan cache at module load so the
# first ``/projects/<id>`` request is a cache hit (gate target: trial
# 1 < 500ms). The scan only walks files under ``project_root`` and
# never mutates anything; failures are best-effort and only logged.
try:
    _scan_project(_project_root())
except Exception as _scan_warmup_exc:  # pragma: no cover - pre-warm best effort
    logger.warning(
        "system-view scan pre-warm failed: %s", _scan_warmup_exc,
    )


def _summary(modules: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the dashboard headline numbers from the module list."""
    feature_count = sum(len(m["features"]) for m in modules)
    total_lines = sum(f["line_count"] for m in modules for f in m["features"])
    clean_count = 0
    dirty_count = 0
    for m in modules:
        for f in m["features"]:
            status = f["clean_status"]
            if status == _OK:
                clean_count += 1
            elif status == _DIRTY:
                dirty_count += 1
    avg_lines = (total_lines / feature_count) if feature_count else 0
    return {
        "module_count": len(modules),
        "feature_count": feature_count,
        "total_lines": total_lines,
        "avg_lines": avg_lines,
        "clean_count": clean_count,
        "dirty_count": dirty_count,
    }


# ---------------------------------------------------------------------------
# project member-management context
# ---------------------------------------------------------------------------


def _filter_auto_own_members(
    members: list[tuple[int, str, str, str]],
) -> list[tuple[int, str, str, str]]:
    """Drop T0/T1 (auto-own) rows from a member list.

    v0.7.2a: ``project_members`` may still carry T0/T1 rows from a
    v0.7.0 deployment because the v0.7.1 migration preserved them
    (the add/remove endpoints now reject new T0/T1 inserts; the
    existing rows are filtered at render time). The lookup uses the
    same :class:`UserStorage` instance the rest of the view uses
    so a stale row gets the same auto-own answer every time.
    Returns a new list; the input is not mutated.
    """
    if not members:
        return []
    storage = _user_storage()
    out: list[tuple[int, str, str, str]] = []
    for m in members:
        target = storage.find_by_id(int(m[0]))
        if target is not None and _is_auto_own(target):
            continue
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# project member-management context
# ---------------------------------------------------------------------------


def _build_member_context(
    user,
    project,
    members: list[tuple[int, str, str, str]],
) -> dict[str, Any]:
    """Compute the member-management context for the two templates.

    Returns a dict the templates can splat into ``render_template``:

    * ``can_manage_members`` — True iff the actor is admin / manager
      (auto-own) or the project owner. Owner-based gate: mirrors the
      server-side
      :func:`project_board.projects.feature_storage.can_manage_members`
      check used by the ``add/remove`` endpoints. project_leader
      cannot render the forms on projects they do not own.
    * ``members_with_self`` — same rows as ``members`` plus a 5th
      element ``is_self`` so the template can hide the Remove button
      on the actor's own row. T0/T1 (auto-own) rows are filtered
      out before this list is built so the UI never displays an
      auto-own user as a member.
    * ``addable_users`` — every user that is not yet a member, is
      not the project owner, and is not T0/T1. Sorted by username so
      the dropdown is stable across requests. Empty for actors that
      cannot manage members or for projects whose roster already
      covers every user.
    """
    can_manage = can_manage_members(user, project)
    actor_id = int(user.id)
    member_ids = {int(m[0]) for m in members}
    members_with_self: list[tuple[int, str, str, str, bool]] = []
    for m in members:
        mid = int(m[0])
        members_with_self.append(
            (mid, str(m[1]), str(m[2]), str(m[3]), mid == actor_id)
        )
    addable: list[dict[str, Any]] = []
    if can_manage:
        all_users = _user_storage().list_all_users()
        for u in all_users:
            # v0.7.2a — T0/T1 (auto-own) are not addable; the add
            # endpoint rejects them with 400 anyway, so the dropdown
            # must not offer them. Filters at the row level rather
            # than at the SQL level because ``_user_storage()`` is
            # the single read-side entry point for the users table.
            if _is_auto_own(u):
                continue
            if int(u.id) == int(project.owner_id):
                continue
            if int(u.id) in member_ids:
                continue
            if int(u.id) == actor_id:
                continue
            addable.append(
                {
                    "id": int(u.id),
                    "username": str(u.username),
                    "role": str(u.role),
                }
            )
        addable.sort(key=lambda row: row["username"])
    return {
        "can_manage_members": bool(can_manage),
        "members_with_self": members_with_self,
        "addable_users": addable,
    }


# v0.9.1 sub-task 4 — Issue 2 / Issue 3: ``_build_owner_context`` and
# the lazy ``_max_node_level`` were retired. The owner-change form
# moved to ``/members``; the 6-level node tree moved to ``/board``.
# View no longer needs either helper, and the unused imports
# (``ADMIN`` / ``MANAGER`` / ``PROJECT_LEADER``) were dropped.


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def _project_storage() -> ProjectStorage:
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


def _user_storage() -> UserStorage:
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return UserStorage(db_path)


@bp.get("/projects/<int:project_id>")
@_require_auth
def show_project(project_id: int):
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    # v0.7.2a — use ``_is_auto_own`` (rank-based) instead of the
    # legacy ``user.role == "admin"`` string so manager (T1) joins
    # admin (T0) in the auto-own short-circuit. The boolean is
    # belt-and-braces for the read-side gate below (which also
    # calls ``_is_auto_own``) and drives the ``viewer_role`` label.
    is_admin = _is_auto_own(user)
    if not user_can_see_project(user, project, is_admin):
        logger.info(
            "project view denied user_id=%s project_id=%s (404 — not visible)",
            user.id, project_id,
        )
        abort(404)

    # system-project branch — dashboard view. Only an admin can reach
    # this branch because ``user_can_see_project`` already short-circuits
    # to True for admin and False for everyone else. The scan runs
    # once per request (sub-second on the project tree).
    if project.is_system:
        project_root = _project_root()
        modules = _scan_project(project_root)
        summary = _summary(modules)
        raw_members = storage.list_members(project_id)
        # v0.7.2a — drop T0/T1 (auto-own) rows from the rendered
        # member list. T0/T1 are not supposed to be project_members
        # rows; any v0.7.0 leftover row is filtered here so the UI
        # never displays an auto-own user as a member.
        members = _filter_auto_own_members(raw_members)
        # system projects accept member management from anyone with
        # rank >= project_leader (admin / manager / project_leader).
        # The system project is permanent and has no delete button
        # (``can_delete=False``), but the member add/remove forms are
        # still rendered.
        member_ctx = _build_member_context(user, project, members)
        logger.info(
            "system project view id=%s by user_id=%s role=%s modules=%s features=%s",
            project.id, user.id, user.role, summary["module_count"], summary["feature_count"],
        )
        return render_template(
            "projects/system_view.html",
            project=project,
            modules=modules,
            summary=summary,
            members=members,
            can_delete=False,
            notice=str(request.args.get("notice", "") or ""),
            error=str(request.args.get("error", "") or ""),
            **member_ctx,
        )

    owner_row = _user_storage().find_by_id(project.owner_id)
    owner_username = owner_row.username if owner_row is not None else "(deleted)"
    viewer_role = (
        "owner" if project.owner_id == user.id
        else ("admin" if is_admin else "member")
    )
    # v0.9.5 P0-3 — single source of truth for the T-scale label.
    # v0.9.7p1 dropped the redundant viewer_rank_label pre-format
    # pass; view.html now calls format_rank_label(viewer_user_rank)
    # directly. viewer_role stays as the project-relative string;
    # the rank label surfaces as a tooltip.
    can_delete = _is_auto_own(user)
    can_manage_members_flag = can_manage_members(user, project)
    # v0.9.1 sub-task 4 — Issue 2 / Issue 3: the read-only node tree
    # moved to /board; the member list + change owner form moved to
    # /members. View now renders only project info + manage links.
    logger.info(
        "project view id=%s by user_id=%s role=%s (simplified: tree → board, members → members page)",
        project.id, user.id, viewer_role,
    )
    return render_template(
        "projects/view.html",
        project=project,
        owner_username=owner_username,
        viewer_role=viewer_role,
        viewer_user_rank=int(user.rank),
        can_delete=can_delete,
        can_manage_members=can_manage_members_flag,
        notice=str(request.args.get("notice", "") or ""),
        error=str(request.args.get("error", "") or ""),
    )


__all__ = ["bp"]
