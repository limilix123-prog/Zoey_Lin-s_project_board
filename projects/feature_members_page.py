"""v0.9.1 + v0.9.3 — Members management + per-(role, node) permission UI.

v0.9.1 sub-task 2 (完整权限设计) added the **page-level** UI
for member management. v0.9.3 (user 8/13 19:34 拍板) **dropped**
the per-(user, node) grant surface; only the role-grant path
remains. The existing
``feature_project_members.add_project_member`` /
``feature_project_members.remove_project_member`` POST
endpoints stay untouched (the new form's "Add member" button
POSTs to the existing endpoint URL — see ``members.html``).

v0.9.1 sub-task 4 — Issue 3 adds the **change owner** form +
``POST /projects/<int:project_id>/members/change-owner``
endpoint. The chokepoint is :func:`change_owner_action`
(already implemented in :mod:`feature_role_v121`); the new
route is a thin wrapper that maps the form's
``new_owner_id`` field through the chokepoint. The legacy
``POST /projects/<int:project_id>/owner`` endpoint in
:mod:`feature_project_owner` stays untouched (sub-task 3
retired the nav entry; v0.7.4 smoke ``v054`` still probes
the legacy URL — both endpoints coexist and the
``/members/change-owner`` form is the v0.9.1 default).

Endpoints
---------
``GET  /projects/<int:project_id>/members``
    Render the members management page. Owner-based gate
    (auto-own / project owner); the form is hidden for
    everyone else. The page is **self-contained** (7/17):
    member list, add-member form, and change owner form
    all live on the same page. (v0.9.3 dropped the
    per-(user, node) permissions table that v0.9.1 had
    on the same page.)

``POST /projects/<int:project_id>/members/change-owner``
    Reassign the project's owner. Form contract:
    ``new_owner_id`` (select with project_leader users).
    Chokepoint: :func:`change_owner_action` (T0 / T1 only +
    non-system project + target rank 2). 7/22 RBAC
    business-lock principle: hand-crafted POSTs that bypass
    the dropdown are rejected at the chokepoint.

``POST /projects/<int:project_id>/roles`` / ``GET .../roles``
    Create / list custom roles for the project. The 3
    baseline roles (project_leader / team_leader / user)
    are pre-seeded; user-created custom roles show up
    alongside them.

``GET  /projects/<int:project_id>/roles/<int:role_id>``
    Render the per-(role, node) grant table for a custom
    role. Member list + per-(role, node) form (HTML
    select + checkbox).

``POST /projects/<int:project_id>/roles/<int:role_id>/permissions``
    Grant / revoke a per-(role, node) write grant. Form
    contract: ``node_id`` (select) + ``can_write`` (1=grant,
    0=revoke). RBAC lives at the route layer (auto-own /
    owner bucket) — there is no per-(user, node) chokepoint
    in v0.9.3.

``POST /projects/<int:project_id>/roles/<int:role_id>/delete``
    Delete a custom role (FK CASCADE clears member
    assignments + grants).

``POST /projects/<int:project_id>/members/<int:user_id>/role``
    Set (or clear) the member's custom role.

(v0.9.3 — removed)
``GET  /projects/<int:project_id>/members/<int:user_id>/permissions``
``POST /projects/<int:project_id>/members/<int:user_id>/permissions``
    The per-(user, node) grant / revoke surface is gone.
    The role-grant endpoint above is the new chokepoint.

HTML form contract (7/17 self-contained)
----------------------------------------
Every page is a **single self-contained view**: member list,
add-member form, change owner form, role management links,
and the per-(role, node) form are all rendered on the same
URL with **HTML form fields** (input / select / checkbox).
No JSON textarea, no nested card / pill / badge primitives,
no client-side state machine. The 7/17 self-contained守门
principle is enforced by URL design: a project_leader that
lands on the page can complete every common action without
clicking through to another URL.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from ..accounts.feature_storage import UserStorage
from ..rbac.feature_role import PROJECT_LEADER
from ..rbac.feature_require_auth import require_auth
from .feature_role_v121 import (
    _BUCKET_AUTO_OWN,
    _BUCKET_OWNER,
    _resolve_role,
    change_owner_action,
)
from .feature_storage import ProjectStorage, user_can_see_project
from .feature_storage_rbac import _is_auto_own

logger = logging.getLogger(__name__)

bp = Blueprint("project_members_page", __name__)

# Form field names. Kept in sync with the ``members.html`` /
# ``custom_role.html`` templates.
_FIELD_USER_ID: str = "user_id"
_FIELD_NODE_ID: str = "node_id"
_FIELD_CAN_WRITE: str = "can_write"

# Flash-style notices. The strings are short and stable so a
# future grep for ``_NOTICE_`` finds every site that surfaces
# a settings / permission flash message.
_NOTICE_GRANTED: str = "Permission granted"
_NOTICE_REVOKED: str = "Permission revoked"
_NOTICE_NOOP: str = "No change (already in requested state)"


def _project_storage() -> ProjectStorage:
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


def _user_storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _build_members_context(user, project) -> dict[str, Any]:
    """Compute the members page context.

    Returns a dict the template can splat into ``render_template``:

    * ``can_manage_members`` — owner-based gate (auto-own /
      project owner). Mirrors the v0.7.x ``can_manage_members`
      so the rule is consistent across the project surface.
    * ``members_with_self`` — every ``project_members`` row
      joined with the user's username + rank, plus a
      ``is_self`` flag. T0 / T1 (auto-own) rows are filtered
      out so the UI never displays an auto-own user as a
      member (matches the v0.7.2a invariant).
    * ``addable_users`` — every non-member, non-owner,
      non-self, non-auto-own user, sorted by username.
    * ``per_user_permissions`` — per-user ``[(node_id, can_write)]``
      list. Pre-fetched so the template can render the
      existing grant state without a second SQL round-trip.
    * ``bucket`` — the actor's resolved RBAC bucket
      (informational).
    """
    storage = _project_storage()
    bucket = _resolve_role(storage, user, project)
    can_manage = bucket in (_BUCKET_AUTO_OWN, _BUCKET_OWNER)
    raw_members = storage.list_members(int(project.id))
    actor_id = int(user.id)
    members_with_self: list[dict[str, Any]] = []
    member_user_ids: list[int] = []
    # v0.9.2 sub-task 7 — fetch every custom role for the
    # project once so the per-row dropdown can render the
    # option list without an N+1 round-trip. Sorted by name
    # for stable UI.
    custom_roles: list[dict[str, Any]] = (
        storage.list_roles(int(project.id)) if can_manage else []
    )
    custom_role_by_id: dict[int, dict[str, Any]] = {
        int(r["id"]): r for r in custom_roles
    }
    for m in raw_members:
        mid = int(m[0])
        member_user_ids.append(mid)
        target = _user_storage().find_by_id(mid)
        if target is not None and _is_auto_own(target):
            continue
        custom_role_id: int | None = (
            int(m[4]) if len(m) > 4 and m[4] is not None else None
        )
        # v0.9.3 (8/14 user 拍板 — 2-section role column) — per-member
        # row needs the role's display name + description so the
        # "current" line can show description as muted helper text.
        # list_roles ships both fields in the same dict; the cached
        # custom_role_by_id lookup is reused here (no N+1 round-trip).
        custom_role_name: str = (
            custom_role_by_id[custom_role_id]["name"]
            if custom_role_id is not None and custom_role_id in custom_role_by_id
            else ""
        )
        custom_role_description: str = (
            custom_role_by_id[custom_role_id]["description"]
            if custom_role_id is not None and custom_role_id in custom_role_by_id
            else ""
        )
        members_with_self.append(
            {
                "user_id": mid,
                "username": str(m[1]),
                "role_in_project": str(m[2]),
                "added_at": str(m[3]),
                "is_self": mid == actor_id,
                "rank": int(getattr(target, "rank", 4) or 4),
                # v0.9.2 sub-task 7 — per-row can-change flag drives
                # the inline role dropdown. Owner / T0 / T1 can
                # change role for everyone but themselves; non-self
                # is the anti-self RBAC rule (matching the
                # :func:`submit_member_role` server-side check).
                "can_change_role": bool(can_manage) and (mid != actor_id),
                # Custom role assignment + the actor's authority
                # to set it. Same anti-self / can_manage rule as
                # the baseline role dropdown. ``custom_role_name``
                # is the rendered name (or empty string when no
                # assignment); the template uses the boolean

                # ``custom_role_id is none`` to render the
                # ``(none)`` placeholder.
                "custom_role_id": custom_role_id,
                "custom_role_name": custom_role_name,
                # v0.9.3 (8/14 user 拍板) — 2-section role column reads
                # custom_role_description for the muted helper text
                # under the current role. Empty when no role assigned;
                # template uses {% if m.custom_role_description %} so the
                # helper line is omitted for roles without a description.
                "custom_role_description": custom_role_description,
                "can_change_custom_role": bool(can_manage) and (mid != actor_id),
            }
        )
    addable: list[dict[str, Any]] = []
    if can_manage:
        member_ids = set(member_user_ids)
        for u in _user_storage().list_all_users():
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
                    "rank": int(u.rank),
                    # role kept for any legacy reader; not used by the
                    # v0.9.1 rank-based UI.
                    "role": str(u.role),
                }
            )
        addable.sort(key=lambda row: row["username"])
    # v0.9.3 — per-(user, node) permissions table is gone. The page
    # no longer renders a per-user permissions section; the per-(role,
    # node) detail page (Manage roles link) is the single place to
    # configure per-(role, node) grants. The v0.9.2 per_user_permissions
    # context field is removed (was an N+1→1 batch SELECT).

    return {
        "can_manage_members": bool(can_manage),
        "members_with_self": members_with_self,
        "addable_users": addable,
        # v0.9.2 sub-task 7 — role list for the per-row
        # dropdown. The 3 baseline roles are pre-seeded so the
        # list always has at least 3 entries; the template's
        # ``{% for r in custom_roles %}`` iterates them all.
        "custom_roles": custom_roles,
        "bucket": bucket or "",
    }


def _flatten_node_for_select(
    node: dict[str, Any],
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Flatten a tree node into a flat list of ``{id, label, level}``.

    v0.9.2 sub-task 8 (perf 9 ops) — walks the tree once, returning a flat
    list shaped for the role-permission grant form. The ``label``
    field prepends non-breaking spaces to ``name`` so the
    indentation reads in the dropdown (matches the v0.9.3 board
    sidebar style). Recurses into ``node["children"]`` to keep
    the depth counter accurate; the result is a depth-first
    pre-order list.
    """
    out: list[dict[str, Any]] = [{
        "id": int(node.get("id", 0)),
        "label": ("\u00a0\u00a0\u00a0\u00a0" * depth) + str(node.get("name", "")),
        "level": int(node.get("level", 0)),
    }]
    for child in node.get("children", []) or []:
        out.extend(_flatten_node_for_select(child, depth + 1))
    return out


# ---------------------------------------------------------------------------
# v0.9.1 sub-task 4 — Issue 3: change owner (relocated to /members).
# ---------------------------------------------------------------------------


def _build_change_owner_context(user, project) -> dict[str, Any]:
    """Compute the change-owner context for ``members.html``.

    Mirrors the v0.7.2b / v0.9.1 settings page gate so the
    rule is consistent across the project surface.

    * ``can_change_owner`` — True iff the actor is T0 / T1
      (rank-based) AND the project is not a system project.
      System projects are permanent; the template falls
      back to a ``(system project owner is permanent)``
      placeholder.
    * ``owner_candidates`` — every ``project_leader`` user
      except the project's current owner, sorted by
      username so the ``<select>`` is stable across
      requests. Empty for actors that cannot change owner,
      for projects whose owner is the only
      ``project_leader``, or for system projects.
    """
    is_admin_or_manager = _is_auto_own(user)
    can_change = bool(is_admin_or_manager) and not bool(project.is_system)
    candidates: list[dict[str, Any]] = []
    if can_change:
        for u in _user_storage().list_all_users():
            # v0.9.2 sub-task 3 — rank-based filter; T2 = project_leader.
            if int(u.rank) != 2:
                continue
            if int(u.id) == int(project.owner_id):
                continue
            candidates.append(
                {
                    "id": int(u.id),
                    "username": str(u.username),
                    "rank": int(u.rank),
                    "role": str(u.role),
                }
            )
        candidates.sort(key=lambda row: row["username"])
    return {
        "can_change_owner": bool(can_change),
        "owner_candidates": candidates,
    }


# Form field for the change-owner form. Kept in sync with the
# ``members.html`` template — a future grep for ``_FIELD_NEW_OWNER``
# finds every site that reads / writes the new owner field.
_FIELD_NEW_OWNER: str = "new_owner_id"

# Flash-style notices for the change-owner form.
_NOTICE_OWNER_CHANGED: str = "Owner updated"
_NOTICE_OWNER_UNCHANGED: str = "Owner unchanged"


@bp.get("/projects/<int:project_id>/members")
@require_auth
def show_members(project_id: int):
    """Render the members management page.

    Read-side gate via :func:`user_can_see_project`; the
    forms are hidden for non-editors. A user that cannot
    see the project gets a 404 (never leak existence).

    v0.9.1 sub-task 4 — Issue 3: the page also renders the
    change-owner form (when the actor is T0 / T1 + non-system
    project) so members management is the single
    self-contained place to manage a project's members AND
    owner. The chokepoint is :func:`change_owner_action`;
    the route layer is the only caller of the chokepoint
    for this UI.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    ctx = _build_members_context(user, project)
    owner_ctx = _build_change_owner_context(user, project)
    return render_template(
        "projects/members.html",
        project=project,
        notice=request.args.get("notice", ""),
        error=request.args.get("error", ""),
        **ctx,
        **owner_ctx,
    )


@bp.post("/projects/<int:project_id>/members/change-owner")
@require_auth
def submit_change_owner(project_id: int):
    """Reassign the project's owner (v0.9.1 sub-task 4 — Issue 3).

    The endpoint is the per-project form's POST target on
    ``members.html``. The chokepoint is
    :func:`change_owner_action` (rank-based T0 / T1 only +
    non-system project + target rank 2 + target exists). The
    7/22 RBAC business-lock principle keeps every check in
    the chokepoint — the route is a thin wrapper that maps
    the form's ``new_owner_id`` field through.

    The legacy ``POST /projects/<int:project_id>/owner``
    endpoint (sub-task 3 retired the nav entry) stays
    untouched for the v0.7.4 smoke ``v054`` contract.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    raw = str(request.form.get(_FIELD_NEW_OWNER, "") or "").strip()
    if not raw:
        return redirect(
            url_for("project_members_page.show_members", project_id=project_id)
            + f"?error={_FIELD_NEW_OWNER} is required"
        )
    try:
        new_owner_id = int(raw)
    except ValueError:
        return redirect(
            url_for("project_members_page.show_members", project_id=project_id)
            + f"?error={_FIELD_NEW_OWNER} must be an integer"
        )
    try:
        changed = change_owner_action(
            storage=storage,
            project=project,
            new_owner_id=new_owner_id,
            actor=user,
        )
    except PermissionError as exc:
        return redirect(
            url_for("project_members_page.show_members", project_id=project_id)
            + f"?error={exc}"
        )
    except ValueError as exc:
        return redirect(
            url_for("project_members_page.show_members", project_id=project_id)
            + f"?error={exc}"
        )
    notice = _NOTICE_OWNER_CHANGED if changed else _NOTICE_OWNER_UNCHANGED
    return redirect(
        url_for("project_members_page.show_members", project_id=project_id)
        + f"?notice={notice}"
    )


# ---------- v0.9.2 sub-task 7 role endpoints ----------
# The endpoints implement the
# "create role → assign permissions → assign to member"
# flow the user asked for. Each endpoint is a thin wrapper
# around the storage chokepoints; the bucket / project-

# membership decisions live here, the policy-free writes
# live in :mod:`feature_storage_node_permissions` /
# :mod:`feature_storage`.



# The endpoints implement the
# "create role → assign permissions → assign to member"
# flow the user asked for. Each endpoint is a thin wrapper
# around the storage chokepoints; the bucket / project-
# membership decisions live here, the policy-free writes

# live in :mod:`feature_storage_node_permissions` /
# :mod:`feature_storage`.


@bp.post("/projects/<int:project_id>/roles")
@require_auth
def submit_create_role(project_id: int):
    """Create a custom role for ``project_id`` (step 1 of the flow)."""
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    bucket = _resolve_role(storage, user, project)
    if bucket not in (_BUCKET_AUTO_OWN, _BUCKET_OWNER):
        abort(403, "you cannot manage this project's roles")
    name = str(request.form.get("name", "") or "").strip()
    description = str(request.form.get("description", "") or "").strip()
    try:
        new_id = storage.create_role(
            int(project.id), name, description,
        )
    except ValueError as exc:
        return redirect(
            url_for("project_members_page.list_roles_page", project_id=project_id)
            + f"?error={exc}"
        )
    except sqlite3.IntegrityError:
        return redirect(
            url_for("project_members_page.list_roles_page", project_id=project_id)
            + f"?error=role+name+already+taken"
        )
    logger.info(
        "v0.9.1 custom role create project_id=%s role_id=%s actor_id=%s",
        int(project.id), new_id, int(user.id),
    )
    return redirect(
        url_for("project_members_page.show_role", project_id=project_id, role_id=new_id)
        + "?notice=role+created"
    )


@bp.get("/projects/<int:project_id>/roles")
@require_auth
def list_roles_page(project_id: int):
    """List every custom role for ``project_id`` + a create form."""
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    bucket = _resolve_role(storage, user, project)
    can_manage = bucket in (_BUCKET_AUTO_OWN, _BUCKET_OWNER)
    roles = storage.list_roles(int(project.id)) if can_manage else []
    return render_template(
        "projects/custom_roles.html",
        project=project,
        roles=roles,
        can_manage=can_manage,
        notice=str(request.args.get("notice", "") or ""),
        error=str(request.args.get("error", "") or ""),
    )


@bp.get("/projects/<int:project_id>/roles/<int:role_id>")
@require_auth
def show_role(project_id: int, role_id: int):
    """Custom role detail: members + per-node grant table."""
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    bucket = _resolve_role(storage, user, project)
    can_manage = bucket in (_BUCKET_AUTO_OWN, _BUCKET_OWNER)
    role: dict[str, Any] | None = None
    for r in storage.list_roles(int(project.id)):
        if int(r["id"]) == int(role_id):
            role = r
            break
    if role is None:
        abort(404)
    grants = (
        storage.list_role_node_permissions(int(project.id), int(role_id))
        if can_manage else []
    )
    # All project's nodes for the grant form dropdown
    all_nodes: list[dict[str, Any]] = []
    if can_manage:
        for n in storage.list_tree(int(project.id)):
            all_nodes.extend(_flatten_node_for_select(n))
    return render_template(
        "projects/custom_role.html",
        project=project,
        role=role,
        grants=grants,
        all_nodes=all_nodes,
        can_manage=can_manage,
        notice=str(request.args.get("notice", "") or ""),
        error=str(request.args.get("error", "") or ""),
    )


@bp.post("/projects/<int:project_id>/roles/<int:role_id>/delete")
@require_auth
def submit_delete_role(project_id: int, role_id: int):
    """Delete a custom role (FK cascade clears member assignments + grants)."""
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    bucket = _resolve_role(storage, user, project)
    if bucket not in (_BUCKET_AUTO_OWN, _BUCKET_OWNER):
        abort(403, "you cannot manage this project's roles")
    removed = storage.delete_role(int(project.id), int(role_id))
    if not removed:
        return redirect(
            url_for("project_members_page.list_roles_page", project_id=project_id)
            + "?error=role+not+found"
        )
    logger.info(
        "v0.9.1 custom role delete project_id=%s role_id=%s actor_id=%s",
        int(project.id), int(role_id), int(user.id),
    )
    return redirect(
        url_for("project_members_page.list_roles_page", project_id=project_id)
        + "?notice=role+deleted"
    )


@bp.post("/projects/<int:project_id>/roles/<int:role_id>/permissions")
@require_auth
def submit_role_node_permission(project_id: int, role_id: int):
    """Grant / revoke a per-(role, node) write grant.

    v0.9.2 sub-task 7 — the per-(role, node) grant
    targets the ``project_custom_role_permissions`` table
    (the single role-permission table for all roles,
    including the 3 baseline ones). The 3 baseline roles
    are auto-granted at migration time; this endpoint
    is for user-created custom roles (and for the
    project_leader to override the baseline grants on
    individual nodes).

    Form contract: ``node_id`` (select) + ``can_write``
    (1 = grant, 0 = revoke). The cross-project guard
    is the JOIN against ``project_custom_roles`` in
    :meth:`set_role_node_permission` (chokepoint).
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    bucket = _resolve_role(storage, user, project)
    if bucket not in (_BUCKET_AUTO_OWN, _BUCKET_OWNER):
        abort(403, "you cannot manage this project's roles")
    node_id_raw = request.form.get("node_id", "")
    try:
        node_id = int(str(node_id_raw).strip())
    except (TypeError, ValueError):
        return redirect(
            url_for("project_members_page.show_role", project_id=project_id, role_id=role_id)
            + "?error=node_id+must+be+an+integer"
        )
    can_write = str(request.form.get("can_write", "0")).strip() == "1"
    try:
        if can_write:
            changed = storage.set_role_node_permission(
                int(project.id), int(role_id), int(node_id), True,
            )
        else:
            changed = storage.clear_role_node_permission(
                int(project.id), int(role_id), int(node_id),
            )
    except ValueError as exc:
        return redirect(
            url_for("project_members_page.show_role", project_id=project_id, role_id=role_id)
            + f"?error={exc}"
        )
    if not changed:
        return redirect(
            url_for("project_members_page.show_role", project_id=project_id, role_id=role_id)
            + "?error=node+or+role+not+in+this+project"
        )
    state = "granted" if can_write else "revoked"
    logger.info(
        "v0.9.1 role permission project_id=%s role_id=%s node_id=%s "
        "can_write=%s actor_id=%s",
        int(project.id), int(role_id), int(node_id),
        bool(can_write), int(user.id),
    )
    return redirect(
        url_for("project_members_page.show_role", project_id=project_id, role_id=role_id)
        + f"?notice=node+{state}"
    )


@bp.post("/projects/<int:project_id>/members/<int:user_id>/role")
@require_auth
def submit_member_role(project_id: int, user_id: int):
    """Set (or clear) the member's custom role (step 3 of the flow)."""
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        abort(404)
    if not user_can_see_project(user, project, _is_auto_own(user)):
        abort(404)
    bucket = _resolve_role(storage, user, project)
    if bucket not in (_BUCKET_AUTO_OWN, _BUCKET_OWNER):
        abort(403, "you cannot manage this project's members")
    target = _user_storage().find_by_id(int(user_id))
    if target is None:
        abort(404, "user not found")
    if not storage.is_member(int(project.id), int(target.id)):
        abort(404, "user is not a member of this project")
    raw = str(request.form.get("custom_role_id", "") or "").strip()
    if not raw:
        new_id: int | None = None
    else:
        try:
            new_id = int(raw)
        except ValueError:
            return redirect(
                url_for("project_members_page.show_members", project_id=project_id)
                + "?error=custom_role_id+must+be+an+integer"
            )
    storage.set_member_role(
        int(project.id), int(target.id), new_id,
    )
    logger.info(
        "v0.9.1 member custom_role set project_id=%s user_id=%s "
        "custom_role_id=%s actor_id=%s",
        int(project.id), int(target.id), new_id, int(user.id),
    )
    return redirect(
        url_for("project_members_page.show_members", project_id=project_id)
        + "?notice=custom+role+updated"
    )


@bp.get("/projects/<int:project_id>/members/<int:user_id>/permissions")
@require_auth
def show_user_permissions(project_id: int, user_id: int):
    """v0.9.3 — endpoint removed.

    The per-(user, node) grant surface is gone (user 8/13 19:34 拍板).
    A request to the old URL returns 404 so any stale bookmark
    / external link surfaces the "this no longer exists" signal
    rather than silently rendering an empty form.
    """
    abort(404)


@bp.post("/projects/<int:project_id>/members/<int:user_id>/permissions")
@require_auth
def submit_user_permissions(project_id: int, user_id: int):
    """v0.9.3 — endpoint removed.

    The per-(user, node) grant surface is gone. POST to the
    old URL returns 404 so a hand-crafted client cannot smuggle
    a grant through the dropped chokepoint (7/22 RBAC
    business-lock — the endpoint is the only server-side
    chokepoint; without the endpoint, the policy-free
    ``ProjectStorage.grant_node_permission`` writer has no
    caller and the user-level table cannot be mutated from
    the route layer).
    """
    abort(404)


__all__ = ["bp"]
