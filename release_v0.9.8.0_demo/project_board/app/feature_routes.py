"""Route registration for the app factory.

Mounts endpoints from feature modules onto the Flask app.

- health blueprint (``/healthz``) and the landing ``/`` redirect.
- auth (register / login / logout) and a session-aware ``/``
  redirect: signed-in users land on ``/projects``, anonymous
  visitors are sent to ``/login``.
- profile (change password) — the standalone ``profile.view`` page is
  retired in favour of the consolidated ``me.show_me`` page. The
  ``/profile/password`` endpoint stays put because the change-password
  form on ``/me`` still POSTs there. Any lingering ``/profile``
  bookmark is rewritten to ``/me`` via a 302 redirect at the bottom of
  :func:`register_routes`.
- projects (list / create / view / delete) and the project member
  add/remove + owner reassignment endpoints.
- /team retired in v0.9.7 (302 → /projects); /team/_internal/report
  shared-secret write stays for the copy-editor agent.
- the self-status dashboard is reachable through the seeded system
  project — the ``project_view.show_project`` handler renders
  ``projects/system_view.html`` when the project row has
  ``project_type='system'``. No top-level route is added; the URL is
  the same ``/projects/<id>`` the rest of the project module uses.

The session cookie name is owned by :mod:`project_board.auth.feature_session`
so this module just reads the public constant instead of duplicating the
string literal.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Flask, current_app, jsonify, redirect, request, url_for

from ..accounts.feature_storage import UserStorage
from ..auth.feature_logout import bp as auth_logout_bp
from ..auth.feature_login import bp as auth_login_bp
from ..auth.feature_register import bp as auth_register_bp
from ..auth.feature_session import SESSION_COOKIE_NAME, get_session
from .feature_help import bp as help_bp
from ..profile.feature_change_password import bp as profile_change_password_bp
from ..projects.feature_create import bp as project_create_bp
from ..projects.feature_delete import bp as project_delete_bp
from ..projects.feature_edit import bp as project_edit_bp
from ..projects.feature_list import bp as projects_list_bp
from ..projects.feature_me import bp as me_bp
from ..projects.feature_board import bp as feature_board_bp
from ..projects.feature_members_page import bp as project_members_page_bp
from ..projects.feature_project_members import bp as project_members_bp
from ..projects.feature_project_owner import bp as project_owner_bp
from ..projects.feature_settings import bp as project_settings_bp
from ..projects.feature_user_view import bp as user_view_bp
from ..projects.feature_users_list import bp as users_list_bp
from ..projects.feature_user_role import bp as user_role_bp
from ..projects.feature_view import bp as project_view_bp
from ..team.feature_team import bp as team_bp

logger = logging.getLogger(__name__)

# A blueprint that always exists — gives the app a non-empty route table
# so smoke tests can probe a known-good endpoint.
_health_bp = Blueprint("health", __name__)


@_health_bp.get("/healthz")
def healthz() -> Any:
    return jsonify({"status": "ok"})


def _storage() -> UserStorage:
    storage = current_app.config.get("PB_STORAGE")
    if storage is None or not isinstance(storage, UserStorage):
        raise RuntimeError("PB_STORAGE not configured on Flask app")
    return storage


def _resolve_user_from_session():
    """Return the User for the request's ``pb_sid`` cookie, or None.

    Mirrors the lookup in :mod:`project_board.rbac.feature_require_auth`
    but as a public, non-decorator entry point so the bare ``/`` redirect
    can branch on "logged in or not" without going through ``@require_auth``.
    """
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        return None
    user_id = get_session(sid)
    if user_id is None:
        return None
    return _storage().find_by_id(user_id)


def register_routes(app: Flask) -> None:
    """Mount all routes onto ``app``."""
    app.register_blueprint(_health_bp)
    app.register_blueprint(auth_register_bp)
    app.register_blueprint(auth_login_bp)
    app.register_blueprint(auth_logout_bp)
    app.register_blueprint(me_bp)
    app.register_blueprint(profile_change_password_bp)
    app.register_blueprint(projects_list_bp)
    app.register_blueprint(project_create_bp)
    app.register_blueprint(project_view_bp)
    app.register_blueprint(project_delete_bp)
    # v0.9.1 — project-level name + description edit. The write goes
    # through ProjectStorage.update() (7/22 business-lock chokepoint);
    # owner / admin / manager gate via can_manage_members. System
    # projects are gated separately inside the endpoint.
    app.register_blueprint(project_edit_bp)
    # user directory + per-user detail. Both routes are gated by
    # ``@require_auth`` so any signed-in user can reach them; the
    # "Change role" form is rendered for actors that can change some
    # role and hidden with a ``(read-only)`` placeholder otherwise.
    app.register_blueprint(users_list_bp)
    app.register_blueprint(user_view_bp)
    # POST /users/<id>/role — change another user's role per the RBAC
    # matrix. Rank-gated at TEAM_LEADER so team_leader (rank 2) and
    # above can call it; the form is hidden for plain users.
    app.register_blueprint(user_role_bp)
    # project member add/remove endpoints. Gated by ``@require_auth``
    # plus the owner-based :func:`can_manage_members` helper so
    # admin / manager / project owner can manage membership; everyone
    # else gets 403.
    app.register_blueprint(project_members_bp)
    # project owner reassignment. The decorator is
    # @require_role(MANAGER) so only admin / manager pass; the route
    # handler additionally enforces the system-permanent rule and the
    # "target must be a project_leader" check before reaching the
    # storage write.
    app.register_blueprint(project_owner_bp)
    # per-project Feature Board (kanban). Owner-based gate via
    # can_manage_members — admin / manager / project owner can write;
    # team_leader and plain user (member) are read-only. The GET
    # endpoint follows user_can_see_project so any viewer reaches the
    # board.
    app.register_blueprint(feature_board_bp)
    # v0.9.1 — project settings page. Combines name + description
    # edit + owner reassignment into a single self-contained form
    # (7/17). The blueprint's POST endpoint delegates to the
    # existing ProjectStorage chokepoints; the nav entry is added
    # in sub-task 3.
    app.register_blueprint(project_settings_bp)
    # v0.9.1 — members management page; per-(user, node) grant UI
    # is gone (v0.9.3 retired the user-level grant surface). The
    # per-user permission endpoints stay as 404 stubs (v0.9.3
    # user拍板保留) so stale bookmarks get a real signal. The
    # legacy project_members blueprint stays for add/remove POST.
    app.register_blueprint(project_members_page_bp)
    # /team retired in v0.9.7 (302 → /projects); the auth-gated
    # show_team handler stays mounted so a stale bookmark still
    # lands on /projects rather than 404 (7/17 self-contained).
    # /team/_internal/report (copy-editor shared-secret write)
    # also stays on the same blueprint.
    app.register_blueprint(team_bp)
    # v0.9.5 P0-4 — /help/glossary. Public (no @require_auth)
    # so a visitor who hit a 404 / 403 can still reach the
    # glossary. The route is mounted after the auth-gated
    # blueprints so the URL ``/help/glossary`` is unambiguous
    # (no overlap with any existing route).
    app.register_blueprint(help_bp)

    @app.get("/")
    def index():
        user = _resolve_user_from_session()
        if user is not None:
            return redirect(url_for("projects_list.show_projects"))
        return redirect(url_for("auth_login.show_login_form"))

    # keep the old /profile URL alive as a 302 redirect to /me so
    # any bookmark or external link lands on the consolidated page.
    # The query string is forwarded so a /profile?changed=1 hit still shows
    # the password-updated notice on /me.
    @app.get("/profile")
    def redirect_profile_to_me():
        target = url_for("me.show_me")
        if request.query_string:
            target += "?" + request.query_string.decode("ascii")
        return redirect(target)

    logger.info(
        "routes registered: count=%d",
        len(list(app.url_map.iter_rules())),
    )


__all__ = ["register_routes"]
