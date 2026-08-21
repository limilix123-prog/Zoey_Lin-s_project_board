"""v0.9.3 — Unified board endpoint (project_features 4 columns + project_nodes tree).

7 endpoints (5 server-side validated — 7/22 business-level lock):

* ``GET    /projects/<int:project_id>/board``                       — render unified page
* ``POST   /projects/<int:project_id>/nodes``                       — create node
* ``POST   /projects/<int:project_id>/nodes/<int:node_id>/edit``    — edit node
* ``POST   /projects/<int:project_id>/nodes/<int:node_id>/status``  — quick-change status
* ``POST   /projects/<int:project_id>/nodes/<int:node_id>/delete``  — delete node (CASCADE)
* ``GET    /projects/<int:project_id>/features``                    — REDIRECT to /board (retired)
* ``POST   /projects/<int:project_id>/features``                    — keep (legacy feature add)
* ``POST   /projects/<int:project_id>/features/<fid>/move``         — keep (legacy feature move)
* ``DELETE /projects/<int:project_id>/features/<fid>``              — keep (legacy feature delete)

UI design
---------
7/17 self-contained principle: single page contains project info
+ legacy 4-column kanban + 6-level tree + inline action buttons;
no cards / pop-ups / tab-switching. Indentation via
``padding-left: depth*20px`` (7/17 principle: do not use icons /
badges / card blocks). ``<details>`` progressive expansion is OK.

Permission model (v0.9.3)
---------------------------
* Read — :func:`user_can_see_project` (owner / member / T0/T1 auto-own)
* Write (per-project) — :func:`_can_write_board` (T0/T1 auto-own OR
  project owner). The v0.9.3 design keeps the 2-class project-level
  gate; the per-node write gate is the role-grant path
  (``user → project_members.custom_role_id → project_custom_role_permissions``)
  via :func:`project_board.projects.feature_role_v121._resolve_role`.
  v0.9.3 dropped the per-(user, node) grant surface (user 8/13
  19:34 拍板).

anti-cross-project
------------------
All POST / DELETE endpoints route through
:func:`_get_node_or_404` which checks
``node.project_id == project_id``; the storage layer's FK + ``AND
project_id = ?`` is the second line of defence. A hand-crafted
POST that pairs a project the actor owns with a node from a
different project returns 404.
"""

from __future__ import annotations

import logging
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

from ..rbac.feature_require_auth import require_auth
from .feature_storage import (
    ProjectStorage,
    _FEATURE_STATUSES,
    can_manage_members,
    user_can_see_project,
)
from .feature_storage_rbac import _is_auto_own
from .feature_storage_nodes import MAX_NODE_LEVEL as _MAX_NODE_LEVEL

logger = logging.getLogger(__name__)

bp = Blueprint("feature_board", __name__)

# 4-column board. Order is fixed (left-to-right in the template).
_STATUS_BACKLOG: str = "backlog"
_STATUS_IN_PROGRESS: str = "in_progress"
_STATUS_DONE: str = "done"
_STATUS_ARCHIVED: str = "archived"

# v0.9.3 6-level cap (top-level import, _MAX_NODE_LEVEL from feature_storage_nodes).
# Replaces the old lazy `_max_level()` helper — direct constant import
# eliminates silent-drift risk (one source of truth in feature_storage_nodes:54).
# v0.9.8 silent-drift fix (per verifier §2 #9 + explore §2 #9).

# Public-safe error strings. Surfaced to the form via the query string
# so the GET re-render can show the message without a separate session
# / flash mechanism (the rest of the project module follows the same
# pattern).
_ERR_FORBIDDEN: str = "you cannot manage the board of this project"
_ERR_NAME_REQUIRED: str = "name is required"
_ERR_FEATURE_NAME_REQUIRED: str = "feature name is required"
_ERR_STATUS_INVALID: str = "invalid status"
_ERR_FEATURE_NOT_FOUND: str = "feature not found"
_ERR_NODE_NOT_FOUND: str = "node not found"
_ERR_LEVEL_OUT_OF_RANGE: str = "level out of range"


# --- storage helper ---


def _project_storage() -> ProjectStorage:
    """Return a :class:`ProjectStorage` keyed on the app's ``PB_CONFIG.DB_PATH``.

    Mirrors the v0.9.1 / v0.9.2 helpers' "read from current_app config,
    raise if missing" pattern. The config is populated by
    :func:`project_board.app.feature_app_factory.create_app` at boot so
    a missing key indicates a misconfiguration, not a missing DB.
    """
    db_path = (current_app.config.get("PB_CONFIG") or {}).get("DB_PATH")
    if not db_path:
        raise RuntimeError("PB_CONFIG/DB_PATH not configured on Flask app")
    return ProjectStorage(db_path)


# --- RBAC helpers ---


def _can_write_board(user, project) -> bool:
    """v0.9.3 simplified write gate.

    Returns True iff the actor is

    * T0 / T1 (admin / manager — auto-own every project via
      :func:`_is_auto_own`), **or**
    * the project's owner (``project.owner_id == user.id``)

    Per-node write is the role-grant path
    (:func:`project_board.projects.feature_role_v121._resolve_role`
    returning ``role_grant``); this project-level gate is the
    pre-condition for the form / button visibility on the
    board view (the role-grant check then runs against the
    specific node when needed).

    False for ``None`` user / project so a defensive caller that
    forgot the upstream guard fails closed.
    """
    if user is None or project is None:
        return False
    if _is_auto_own(user):
        return True
    return int(user.id) == int(project.owner_id)


def _check_can_see(user, project) -> None:
    """Read-side RBAC; abort 404 if the actor cannot see the project.

    Mirrors the same gate as :mod:`project_view.show_project` —
    a viewer that fails the check gets 404, never 403, so the
    URL does not leak the existence of a project the actor
    cannot see.
    """
    is_admin = _is_auto_own(user)
    if not user_can_see_project(user, project, is_admin):
        logger.info(
            "board view denied user_id=%s project_id=%s (404 — not visible)",
            user.id, project.id,
        )
        abort(404)


def _check_can_write(user, project, action: str) -> None:
    """Project-level write gate.

    ``action`` is one of "board" / "label" / "node-create" / "node-edit" /
    "node-status" / "node-delete" / "feature-add" / "feature-move" /
    "feature-delete". The string lands in the log line so an operator
    chasing a 403 can disambiguate which endpoint rejected the
    request.
    """
    if _can_write_board(user, project):
        return
    logger.warning(
        "board %s denied actor_id=%s project_id=%s role=%s owner_id=%s "
        "(403 — not admin/manager and not owner)",
        action, user.id, project.id, user.role, project.owner_id,
    )
    abort(403, _ERR_FORBIDDEN)


def _get_node_or_404(storage: ProjectStorage, project_id: int, node_id: int):
    """Return the node row, or abort 404.

    Enforces the anti-cross-project guard at the route layer:
    a hand-crafted POST that pairs a project the actor owns
    with a node id from a different project gets 404, never a
    silent 200 with the wrong node mutated. The storage layer's
    FK + ``AND project_id = ?`` is the second line of defence.
    """
    node = storage.find_node_by_id(int(node_id))
    if node is None:
        abort(404, _ERR_NODE_NOT_FOUND)
    if int(node["project_id"]) != int(project_id):
        logger.info(
            "board node cross-project 404 actor requested project_id=%s "
            "but node_id=%s belongs to project_id=%s",
            int(project_id), int(node_id), int(node["project_id"]),
        )
        abort(404, _ERR_NODE_NOT_FOUND)
    return node


def _board_url(project_id: int) -> str:
    return url_for("feature_board.show_board", project_id=project_id)


def _features_url(project_id: int) -> str:
    """Legacy /features URL — kept so the old POST endpoints still
    have a redirect target after a /board-style retirement.
    """
    return url_for("feature_board.show_board", project_id=project_id)


def _group_by_status(features) -> dict[str, list]:
    """Bucket ``features`` into the four status columns.

    Returns a dict keyed by the four status literals; missing keys
    default to an empty list so the template can iterate without a
    ``{% if %}`` guard per column. Order within a column follows the
    caller-provided ordering (storage sorts by created_at ASC).
    """
    columns: dict[str, list] = {
        _STATUS_BACKLOG: [],
        _STATUS_IN_PROGRESS: [],
        _STATUS_DONE: [],
        _STATUS_ARCHIVED: [],
    }
    for f in features:
        key = str(getattr(f, "status", _STATUS_BACKLOG) or _STATUS_BACKLOG)
        if key not in columns:
            # Defensive: an unknown status (shouldn't happen —
            # storage is the only writer) lands in backlog so the
            # row is still rendered and the operator can see it.
            key = _STATUS_BACKLOG
        columns[key].append(f)
    return columns


def _is_allowed_status(value: str) -> bool:
    return str(value or "").strip().lower() in _FEATURE_STATUSES


def _collect_user_role_node_perms(
    storage: ProjectStorage,
    project_id: int,
    user_id: int,
    node_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """Return ``{node_id: {can_write, granted_at}}`` for ``user_id``
    on every node in ``node_ids`` where the user's project role
    grants ``can_write = 1``, in a single SQL round-trip.

    v0.9.3 — replaces the v0.9.2 ``_collect_user_node_perms``
    (per-(user, node) grant lookup). The query joins the user →
    their project role (``project_members.custom_role_id``) →
    the role's per-(role, node) grant template
    (``project_custom_role_permissions``). Only ``can_write = 1``
    rows are returned; the per-node "what can the user write?"
    decision is now the role-grant path.

    Returns an empty dict for an empty ``node_ids`` (no SQL).
    The ``node_id IN (...)`` filter uses placeholders to keep
    the query safe under arbitrary node-id lists; the helper
    does no per-row RBAC because the caller (``_render_board``)
    already gated by ``_check_can_see``.

    Note: a user with no ``custom_role_id`` (``NULL``) is
    filtered out by the ``pm.custom_role_id = pcrp.custom_role_id``
    JOIN — the user's role-grant set is the empty set until
    they are assigned a role.
    """
    out: dict[int, dict[str, Any]] = {}
    if not node_ids:
        return out
    placeholders = ",".join("?" * len(node_ids))
    with storage._lock:
        conn = storage._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT pcrp.node_id, pcrp.can_write, pcrp.granted_at
                FROM project_custom_role_permissions pcrp
                JOIN project_members pm
                  ON pm.custom_role_id = pcrp.custom_role_id
                JOIN project_nodes pn ON pn.id = pcrp.node_id
                WHERE pn.project_id = ?
                  AND pm.user_id = ?
                  AND pcrp.can_write = 1
                  AND pcrp.node_id IN ({placeholders})
                """,
                [int(project_id), int(user_id)]
                + [int(nid) for nid in node_ids],
            ).fetchall()
        finally:
            conn.close()
    for r in rows:
        out[int(r["node_id"])] = {
            "can_write": int(r["can_write"] or 0),
            "granted_at": str(r["granted_at"]),
        }
    return out


# --- legacy /features 4-column board (kept for backward compat) ---


@bp.get("/projects/<int:project_id>/features")
@require_auth
def view_board(project_id: int):
    """Render the unified board (v0.9.3 retirement of /features as a separate page).

    v0.9.3 unifies the per-project kanban view into /board. The
    legacy /features URL is kept as a 200 render of the same
    template (rather than a 302 redirect) so the v0.9.0 smoke
    suite — which still probes /features for read access (200)
    and cross-project (404) — continues to work without
    rewriting its expectations. The page is the same
    self-contained board: features 4 columns + nodes tree,
    per 7/17 principles.

    The /board endpoint (:func:`show_board` below) renders the
    exact same page; the two routes are kept in sync by sharing
    the same handler body via a private helper. The :func:`show_board`
    endpoint is the preferred URL going forward; /features is
    legacy and may be retired in a future cleanup patch.
    """
    return _render_board(project_id)


@bp.post("/projects/<int:project_id>/features")
@require_auth
def add_feature(project_id: int):
    """Add a feature to ``project_id`` (legacy v0.6.1 endpoint, kept).

    The legacy 4-column board endpoint is preserved for backward
    compat with the existing smokes; the unified /board view in
    v0.9.3 still renders the same rows. The storage layer's
    chokepoint (:meth:`ProjectStorage.create_feature`) is the only
    writer so a hand-crafted POST cannot bypass validation.

    Form contract: ``name`` (required) + ``description`` (optional).
    The status defaults to ``backlog`` on the storage write so the
    actor does not have to pick a starting column. The form re-renders
    with the user's input preserved on validation failure.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "feature add 404 actor_id=%s project_id=%s",
            user.id, project_id,
        )
        abort(404)
    _check_can_write(user, project, "feature-add")

    name = str(request.form.get("name", "") or "").strip()
    description = str(request.form.get("description", "") or "").strip()
    if not name:
        logger.info(
            "feature add rejected actor_id=%s project_id=%s reason=missing-name",
            user.id, project.id,
        )
        return redirect(f"{_board_url(project_id)}?error={_ERR_FEATURE_NAME_REQUIRED}")
    try:
        storage.create_feature(
            project_id=project_id, name=name, description=description,
        )
    except ValueError as exc:
        # Storage raises ValueError for empty name (defence in depth
        # — the route handler already trimmed). Surface as a 400 so
        # the operator chasing a malformed POST gets a clear signal.
        logger.info(
            "feature add rejected actor_id=%s project_id=%s reason=%s",
            user.id, project.id, exc,
        )
        abort(400, str(exc))
    logger.info(
        "feature add project_id=%s actor_id=%s name=%s",
        project_id, user.id, name,
    )
    return redirect(_board_url(project_id))


@bp.post("/projects/<int:project_id>/features/<int:feature_id>/move")
@require_auth
def move_feature(project_id: int, feature_id: int):
    """Move a feature to a new status column (legacy v0.6.1 endpoint, kept).

    Form contract: ``status`` (one of the four allowed literals).
    The cross-project guard is enforced inside the storage layer —
    the row only updates when ``(id, project_id)`` matches.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "feature move 404 actor_id=%s project_id=%s feature_id=%s",
            user.id, project_id, feature_id,
        )
        abort(404)
    _check_can_write(user, project, "feature-move")

    raw_status = str(request.form.get("status", "") or "").strip().lower()
    if not _is_allowed_status(raw_status):
        logger.info(
            "feature move rejected actor_id=%s project_id=%s feature_id=%s "
            "raw=%r reason=invalid-status",
            user.id, project_id, feature_id, raw_status,
        )
        return redirect(f"{_board_url(project_id)}?error={_ERR_STATUS_INVALID}")

    changed = storage.move_feature(
        project_id=project_id, feature_id=feature_id, new_status=raw_status,
    )
    if not changed:
        logger.info(
            "feature move 404 actor_id=%s project_id=%s feature_id=%s "
            "reason=feature-not-found-or-wrong-project",
            user.id, project_id, feature_id,
        )
        abort(404, _ERR_FEATURE_NOT_FOUND)
    logger.info(
        "feature move project_id=%s feature_id=%s new_status=%s actor_id=%s",
        project_id, feature_id, raw_status, user.id,
    )
    return redirect(_board_url(project_id))


@bp.delete("/projects/<int:project_id>/features/<int:feature_id>")
@require_auth
def delete_feature(project_id: int, feature_id: int):
    """Delete a feature from ``project_id`` (legacy v0.6.1 endpoint, kept).

    The cross-project guard is enforced inside the storage layer —
    the row only deletes when ``(id, project_id)`` matches.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "feature delete 404 actor_id=%s project_id=%s feature_id=%s",
            user.id, project_id, feature_id,
        )
        abort(404)
    _check_can_write(user, project, "feature-delete")

    removed = storage.delete_feature(
        project_id=project_id, feature_id=feature_id,
    )
    if not removed:
        logger.info(
            "feature delete 404 actor_id=%s project_id=%s feature_id=%s "
            "reason=feature-not-found-or-wrong-project",
            user.id, project_id, feature_id,
        )
        abort(404, _ERR_FEATURE_NOT_FOUND)
    logger.info(
        "feature delete project_id=%s feature_id=%s actor_id=%s",
        project_id, feature_id, user.id,
    )
    return redirect(_board_url(project_id))


# --- v0.9.3 unified /board endpoint ---


def _render_board(project_id: int):
    """Shared render body for the unified /features and /board endpoints.

    Both :func:`view_board` (legacy /features) and :func:`show_board`
    (new /board) call this helper so the page shape is identical
    regardless of which URL the actor reached. The 200 render is the
    v0.9.3 contract — both endpoints return the same
    ``projects/board.html`` template with the same context.

    Read access follows :func:`user_can_see_project` (owner / member /
    admin / manager). A viewer that fails the check gets 404, never
    403, so the URL does not leak the existence of a project the
    actor cannot see.

    v0.9.1 sub-task 10 (board.html 移植 v4): the v4 board uses
    hidden radio buttons + CSS sibling selectors to render one
    node's detail at a time. The ``selected_node_id`` URL
    parameter (set by :func:`create_node` after a v4 quick-add)
    tells the template which node's ``<article>`` is the
    ``checked`` radio. When the parameter is missing the helper
    defaults to the first top-level node in the project; when
    it points to a node that no longer exists the helper falls
    back to the same default so the page never lands on a
    blank main pane.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "board view 404 actor_id=%s project_id=%s",
            user.id, project_id,
        )
        abort(404)
    _check_can_see(user, project)

    features = storage.list_features(project_id)
    columns = _group_by_status(features)
    tree = storage.get_tree(project_id)
    can_write = _can_write_board(user, project)
    # v0.9.3 — N+1 → 1 query for per-node role grants. v0.9.2
    # was one _list_grants_for_node call per tree node (29
    # round-trips on the test project); _collect_user_role_node_perms
    # is exactly 1 round-trip. v0.9.3 walks user → role → role-grant
    # (the only node-scoped write surface; per-(user, node) dropped).
    my_grants: list[dict] = []
    if not can_write:
        # T0 / T1 / project owners have project-wide write; the
        # role-grant list is only interesting for read-only
        # viewers (T3 / T4 not owner) so the template can show
        # "You have write access to: X, Y" via the role path.
        all_node_ids = [
            int(n.get("id", 0))
            for n in _flatten_tree(tree)
            if n.get("id") is not None
        ]
        perms_map = _collect_user_role_node_perms(
            storage, int(project_id), int(user.id), all_node_ids,
        )

        def _emit(n: dict) -> None:
            nid = int(n.get("id", 0))
            if nid in perms_map:
                my_grants.append(
                    {
                        "node_id": nid,
                        "node_name": str(n.get("name", "")),
                        "node_level": int(n.get("level", 0) or 0),
                    }
                )
            for c in n.get("children", []) or []:
                _emit(c)
        for n in tree:
            _emit(n)
    # v0.9.1 sub-task 10 — selected_node_id drives the v4 board's
    # single-node detail view. The helper walks the tree depth-first
    # to find a matching id; a missing / unknown id falls back to
    # the first id encountered so the radio never lands on "none
    # checked" (which would leave the main pane blank).
    selected_node_id: int | None = _resolve_selected_node_id(
        request.args.get("selected"), tree,
    )
    # v0.9.1 sub-task 10 — flat list of every node in the project.
    # The v4 board renders one <article> per node + one hidden radio
    # per node, so a single DFS pass produces the iteration source
    # for both loops. Default selected id is the first entry in the
    # flat list (matches the sidebar's first visible row).
    all_nodes_flat: list[dict] = _flatten_tree(tree)
    notice = str(request.args.get("notice", "") or "")
    error = str(request.args.get("error", "") or "")
    logger.info(
        "board view project_id=%s by user_id=%s role=%s "
        "features=%d root_nodes=%d can_write=%s grants=%d selected=%s",
        project.id, user.id, user.role,
        len(features), len(tree), can_write, len(my_grants),
        selected_node_id,
    )
    return render_template(
        "projects/board.html",
        project=project,
        columns=columns,
        tree=tree,
        can_write=can_write,
        my_grants=my_grants,
        notice=notice,
        error=error,
        max_level=_MAX_NODE_LEVEL,
        selected_node_id=selected_node_id,
        all_nodes_flat=all_nodes_flat,
    )


def _flatten_tree(nodes) -> list[dict]:
    """Return a depth-first flat list of every node in ``nodes``.

    The v0.9.1 sub-task 10 board view needs both the nested
    tree (sidebar) and a flat list (the v4 hidden radios +
    ``<article>`` loop, which require same-level siblings for
    the CSS sibling selector). The walk preserves the storage
    order so the default selected id matches the sidebar's
    first visible row.
    """
    out: list[dict] = []
    for n in nodes or []:
        out.append(n)
        out.extend(_flatten_tree(n.get("children")))
    return out


def _walk_first_id(nodes) -> int | None:
    """Depth-first walk returning the first node id, or None.

    Mirrors the order the board template renders so the default
    selected radio matches the first row the eye sees. An empty
    tree returns ``None`` so the template can show the "no
    node yet" hint without crashing.
    """
    for n in nodes or []:
        nid = n.get("id")
        if nid is not None:
            return int(nid)
        inner = _walk_first_id(n.get("children"))
        if inner is not None:
            return inner
    return None


def _resolve_selected_node_id(raw_selected, tree) -> int | None:
    """Return the node id to mark as ``checked`` in the v4 board.

    The helper is forgiving on purpose: an unparseable or unknown
    id silently falls back to the first id in the tree (or
    ``None`` for an empty project) so a stale bookmark never
    lands on a blank main pane.
    """
    if raw_selected:
        try:
            wanted = int(str(raw_selected).strip())
        except (TypeError, ValueError):
            return _walk_first_id(tree)
        if _tree_contains_id(tree, wanted):
            return wanted
    return _walk_first_id(tree)


def _tree_contains_id(nodes, wanted: int) -> bool:
    """Return True iff ``wanted`` appears anywhere in the tree."""
    for n in nodes or []:
        try:
            if int(n.get("id")) == int(wanted):
                return True
        except (TypeError, ValueError):
            continue
        if _tree_contains_id(n.get("children"), wanted):
            return True
    return False


@bp.get("/projects/<int:project_id>/board")
@require_auth
def show_board(project_id: int):
    """Render the unified board (features 4 columns + nodes tree).

    The preferred URL going forward; the legacy /features URL
    (:func:`view_board` above) renders the same page so the
    v0.9.0 smoke suite continues to work without rewriting its
    expectations.
    """
    return _render_board(project_id)


# --- v0.9.3 node CRUD endpoints (5 server-side validated) ---


@bp.post("/projects/<int:project_id>/nodes")
@require_auth
def create_node(project_id: int):
    """Create a node (top-level or child of an existing node).

    Form contract: ``parent_id`` (optional — empty = top-level),
    ``name`` (optional — defaults to ``"未命名"`` for the v4
    sidebar quick-add form), ``description`` (optional, ≤ 4000
    chars), ``status`` (optional — defaults to ``backlog``).

    v0.9.1 sub-task 10 (board.html 移植 v4): the v4 sidebar's
    ``[+ 加子节点]`` form is a single-button form that only ships
    ``parent_id`` + ``name="未命名"`` + ``status="backlog"`` as
    hidden inputs. The route no longer rejects an empty ``name``
    — it fills in ``"未命名"`` so the quick-add path lands a row
    the user can rename in-place via the new-node form. The
    resulting node is then 302-redirected to with
    ``?selected=<new_id>`` so the board opens the new node's
    detail page (where the name input is auto-focused).

    The storage layer computes the level from ``parent.level + 1``
    (or 1 for top-level). A child of a level-6 node raises
    ``ValueError`` which the route maps to a 302 error
    redirect. The status whitelist raises ``ValueError`` for
    unknown literals.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "node create 404 actor_id=%s project_id=%s",
            user.id, project_id,
        )
        abort(404)
    _check_can_write(user, project, "node-create")

    raw_parent = str(request.form.get("parent_id", "") or "").strip()
    name = str(request.form.get("name", "") or "").strip()
    description = str(request.form.get("description", "") or "").strip()
    status = str(request.form.get("status", "backlog") or "backlog").strip().lower()

    if not name:
        # v4 sidebar quick-add path: hidden input "name=未命名" is
        # the user's intent. Older forms that landed here with a
        # blank name (e.g. a JS-disabled browser) also get the
        # default — better than a 302 error round-trip.
        name = "未命名"

    parent_id: int | None = None
    level: int = 1
    if raw_parent:
        try:
            parent_id = int(raw_parent)
        except ValueError:
            abort(400, "parent_id must be an integer")
        parent = _get_node_or_404(storage, project_id, parent_id)
        level = int(parent["level"]) + 1
        if level > _MAX_NODE_LEVEL:
            return redirect(
                f"{_board_url(project_id)}?error={_ERR_LEVEL_OUT_OF_RANGE}"
            )

    try:
        new_id = storage.create_node(
            project_id=project_id,
            parent_id=parent_id,
            level=level,
            name=name,
            description=description,
            status=status,
        )
    except ValueError as exc:
        logger.info(
            "node create rejected actor_id=%s project_id=%s reason=%s",
            user.id, project.id, exc,
        )
        abort(400, str(exc))

    logger.info(
        "node create project_id=%s node_id=%s parent_id=%s level=%s "
        "actor_id=%s",
        project_id, new_id, parent_id, level, user.id,
    )
    return redirect(f"{_board_url(project_id)}?selected={int(new_id)}")


@bp.post("/projects/<int:project_id>/nodes/<int:node_id>/edit")
@require_auth
def edit_node(project_id: int, node_id: int):
    """Edit a node's name / description / status.

    Form contract: ``name`` (required), ``description`` (optional),
    ``status`` (one of the four allowed literals). The level /
    parent_id are not editable from the v0.9.3 UI (use the
    "delete + re-create" pattern for re-parenting).
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "node edit 404 actor_id=%s project_id=%s node_id=%s",
            user.id, project_id, node_id,
        )
        abort(404)
    _check_can_write(user, project, "node-edit")

    node = _get_node_or_404(storage, project_id, node_id)

    name = str(request.form.get("name", "") or "").strip()
    description = str(request.form.get("description", "") or "").strip()
    status = str(request.form.get("status", "backlog") or "backlog").strip().lower()

    if not name:
        return redirect(f"{_board_url(project_id)}?error={_ERR_NAME_REQUIRED}")
    if not _is_allowed_status(status):
        return redirect(f"{_board_url(project_id)}?error={_ERR_STATUS_INVALID}")

    try:
        changed = storage.update_node(
            node_id=int(node_id),
            name=name,
            description=description,
            status=status,
        )
    except ValueError as exc:
        logger.info(
            "node edit rejected actor_id=%s project_id=%s node_id=%s reason=%s",
            user.id, project.id, node_id, exc,
        )
        abort(400, str(exc))

    logger.info(
        "node edit project_id=%s node_id=%s actor_id=%s changed=%s",
        project.id, node_id, user.id, changed,
    )
    return redirect(_board_url(project_id))


@bp.post("/projects/<int:project_id>/nodes/<int:node_id>/status")
@require_auth
def change_node_status(project_id: int, node_id: int):
    """Quick-change a node's status (no name / description edit).

    Form contract: ``status`` (one of the four allowed literals).
    Used by the inline ``<select> + set button`` on the board view
    so the actor can move a node between columns without opening
    a separate form. The full ``/edit`` endpoint is preserved for
    the case where the actor wants to change name / description
    in the same round-trip.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "node status 404 actor_id=%s project_id=%s node_id=%s",
            user.id, project_id, node_id,
        )
        abort(404)
    _check_can_write(user, project, "node-status")

    node = _get_node_or_404(storage, project_id, node_id)

    raw_status = str(request.form.get("status", "") or "").strip().lower()
    if not _is_allowed_status(raw_status):
        return redirect(f"{_board_url(project_id)}?error={_ERR_STATUS_INVALID}")

    try:
        # Read the existing row's name + description to keep them
        # intact (the storage layer's update_node overwrites all
        # three, so we re-read first).
        name = str(node["name"])
        description = str(node["description"] or "")
        changed = storage.update_node(
            node_id=int(node_id),
            name=name,
            description=description,
            status=raw_status,
        )
    except ValueError as exc:
        logger.info(
            "node status rejected actor_id=%s project_id=%s node_id=%s reason=%s",
            user.id, project.id, node_id, exc,
        )
        abort(400, str(exc))

    logger.info(
        "node status project_id=%s node_id=%s new_status=%s actor_id=%s "
        "changed=%s",
        project.id, node_id, raw_status, user.id, changed,
    )
    return redirect(_board_url(project_id))


@bp.post("/projects/<int:project_id>/nodes/<int:node_id>/delete")
@require_auth
def delete_node(project_id: int, node_id: int):
    """Physically delete a node and its entire subtree.

    v0.9.1 sub-task 11 — 8/12 17:45 user 拍: 撤回 sub-task 10 的
    soft delete, **真删**. The 7/22 RBAC business-level lock still
    guards the operation (server auth via @require_auth +
    can_manage_members role check + 二次确认 via the v4 sidebar
    inline <details> confirm block) — the lock is about *who* can
    invoke this, not about whether the row should survive. Soft
    delete turned every "delete" into a permanent archive row,
    which piled up in the DB and polluted the sidebar — the user
    wants pen-and-paper semantics: confirm, then it's gone.

    The storage helper :meth:`ProjectStorage.delete_subtree` does
    a BFS walk + single bulk DELETE on the root + every descendant.

    Returns 302 to the board on success, 404 when the node is
    missing or the cross-project guard in :func:`_get_node_or_404`
    rejects it.
    """
    user = g.current_user
    storage = _project_storage()
    project = storage.find_by_id(project_id)
    if project is None:
        logger.info(
            "node delete 404 actor_id=%s project_id=%s node_id=%s",
            user.id, project_id, node_id,
        )
        abort(404)
    _check_can_write(user, project, "node-delete")

    _get_node_or_404(storage, project_id, node_id)  # anti-cross-project

    deleted = storage.delete_subtree(int(node_id))
    if deleted <= 0:
        logger.info(
            "node delete 404 actor_id=%s project_id=%s node_id=%s "
            "reason=node-not-found-or-wrong-project",
            user.id, project_id, node_id,
        )
        abort(404, _ERR_NODE_NOT_FOUND)

    logger.info(
        "node physical-delete project_id=%s node_id=%s actor_id=%s "
        "rows_deleted=%s",
        project.id, node_id, user.id, deleted,
    )
    return redirect(_board_url(project_id))


__all__ = ["bp"]
