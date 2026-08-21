"""Flask application factory.

Wires together: config loading → Flask init → storage schema → admin seed
→ template loader → session config → route registration.

Run with: ``flask --app project_board.app.feature_app_factory:create_app run``
or via ``python -m project_board`` (when the top-level entry point lands).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from flask import Flask, render_template

from ..accounts.feature_storage import UserStorage
from ..projects.feature_storage import ProjectStorage
from ..rbac.feature_create_admin import (
    ensure_admin_exists,
    ensure_manager_exists,
    ensure_project_leader_exists,
    ensure_team_leader_exists,
)
from .feature_config import load_config
from .feature_routes import register_routes
from .feature_templates import init_templates
from .feature_api_v1 import bp as api_v1_bp
from ..auth.feature_session import SESSION_COOKIE_NAME

logger = logging.getLogger(__name__)

# Default location of config.yaml — the project root, two levels above this
# file (project_board/app/feature_app_factory.py → project_board/).
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Storage key the rest of the app reads via current_app.config["PB_STORAGE"].
_STORAGE_CONFIG_KEY = "PB_STORAGE"
_CONFIG_KEY = "PB_CONFIG"


def create_app(
    config_path: str | Path | None = None,
    *,
    run_seed: bool = True,
) -> Flask:
    """Build and return a fully-wired Flask app instance.

    Parameters
    ----------
    config_path:
        Path to the YAML config. Defaults to ``<project_root>/config.yaml``.
    run_seed:
        When True, call :func:`ensure_admin_exists`,
        :func:`ensure_manager_exists`,
        :func:`ensure_project_leader_exists`,
        :func:`ensure_team_leader_exists` and
        :func:`_ensure_system_project_exists` so the bootstrap
        admin / manager / project_leader / team_leader users and the
        platform self-status project are created on first launch.
        Tests pass ``False`` to skip the side effects.
    """
    path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
    cfg = load_config(path)

    # Resolve a relative DB_PATH against the config file's directory, not the
    # current working directory — so "data/project_board.db" always lands next
    # to the config file, regardless of which directory the operator launches
    # the app from.
    db_path = Path(cfg["DB_PATH"])
    if not db_path.is_absolute():
        cfg["DB_PATH"] = str((path.resolve().parent / db_path).resolve())

    app = Flask(
        import_name=__package__ or "project_board",
        instance_relative_config=False,
    )
    _configure_app(app, cfg)

    storage = UserStorage(cfg["DB_PATH"])
    storage.init_schema()
    project_storage = ProjectStorage(cfg["DB_PATH"])
    project_storage.init_schema()
    # v0.7.1 — run the data migration after both init_schema calls so
    # the new ``users.rank`` column exists (added by UserStorage) and
    # the ``project_members`` CHECK constraint is installed (added by
    # ProjectStorage) before the row-level migration tries to read or
    # rewrite any rows. The migration is idempotent.
    from ..accounts.feature_migrate_v071 import run_migration
    run_migration(cfg["DB_PATH"])
    # v0.9.2 — install ``project_nodes`` + ``project_node_permissions``.
    # DDL is idempotent; the migration is a no-op on a fresh install
    # where init_schema already created the tables. Runs after the
    # v0.7.1 migration so any v0.7.1-rewritten rows are in place before
    # v0.9.2 reads them.
    from ..projects.feature_migrate_v092 import run_migration as run_migration_v092
    run_migration_v092(cfg["DB_PATH"])
    app.config[_STORAGE_CONFIG_KEY] = storage
    app.config[_CONFIG_KEY] = cfg

    init_templates(app, Path(__file__).resolve().parent)

    if run_seed:
        ensure_admin_exists(
            storage=storage,
            admin_username=cfg["ADMIN_USERNAME"],
            admin_password=cfg["ADMIN_PASSWORD"],
        )
        # seed the manager (rank 4 — full system, below admin). The
        # seeder falls through to the "leader" username and renames it
        # via set_username when upgrading an older deployment that
        # still has that row.
        ensure_manager_exists(
            storage=storage,
            manager_username=str(cfg.get("ADMIN_MANAGER_USERNAME", "") or ""),
            manager_password=str(cfg.get("ADMIN_MANAGER_PASSWORD", "") or ""),
        )
        # seed the project_leader (rank 3 — project super admin, below
        # manager). The seeder falls through to the "mavis" username
        # and renames it on upgrade.
        ensure_project_leader_exists(
            storage=storage,
            project_leader_username=str(
                cfg.get("ADMIN_PROJECT_LEADER_USERNAME", "") or ""
            ),
            project_leader_password=str(
                cfg.get("ADMIN_PROJECT_LEADER_PASSWORD", "") or ""
            ),
        )
        # seed the team_leader (rank 2 — middle tier, below
        # project_leader). No older-deployment fallback; the role was
        # added in a later rollout.
        ensure_team_leader_exists(
            storage=storage,
            team_leader_username=str(cfg.get("ADMIN_TEAM_LEADER_USERNAME", "") or ""),
            team_leader_password=str(cfg.get("ADMIN_TEAM_LEADER_PASSWORD", "") or ""),
        )
        # seed the platform self-status project. The project is owned
        # by the bootstrap admin and is the only place the kanban-style
        # module + feature scan is reachable. The seed is idempotent —
        # re-running create_app on a DB that already has the row is a
        # no-op.
        _ensure_system_project_exists(
            project_storage=project_storage,
            user_storage=storage,
            admin_username=str(cfg.get("ADMIN_USERNAME", "") or ""),
        )

    register_routes(app)

    # v0.9.5 P0-1/2 — localise 404 / 405 / 403 to Chinese HTML
    # templates. Registered AFTER register_routes so any route's
    # ``abort(404)`` is captured. 7/22 RBAC 业务级 lock preserved:
    # server still returns 404 for hidden projects; only the
    # body is localised.
    _register_error_handlers(app)

    # v0.9.8 experiment — /api/v1/system/status JSON endpoint
    # (sub-agent worker trial, bounded read-only, no auth). Mounted
    # after the error handlers so any 404 / 405 / 403 raised by the
    # api_v1 blueprint is captured by the localised handlers rather
    # than the legacy English Flask page. The endpoint is a
    # 6-field JSON probe (version / db_schema / users_count /
    # projects_count / uptime_seconds / timestamp); no side-effects.
    app.register_blueprint(api_v1_bp)

    logger.info(
        "app created db=%s admins=%s users=%s",
        cfg["DB_PATH"],
        storage.count_admins(),
        storage.count_users(),
    )
    return app


# bootstrap the platform self-status project. The admin user is
# looked up by config username; a missing / blank admin short-circuits
# the call to a no-op so the smoke harness can still build the app
# without an admin user.
_SYSTEM_PROJECT_NAME: str = "项目管理系统"


def _ensure_system_project_exists(
    project_storage: ProjectStorage,
    user_storage: UserStorage,
    admin_username: str,
) -> int | None:
    """Create the platform self-status project if it does not exist.

    Returns the project id (newly created or pre-existing) or ``None``
    when the admin user could not be resolved (no admin_username, no
    matching row, or the user table is unseeded). The function is
    private to the app factory — callers outside this module have no
    reason to invoke it directly because the only entry point is the
    ``run_seed`` branch of :func:`create_app`.
    """
    if not admin_username:
        logger.info("system project seed skipped — empty admin username")
        return None
    admin_row = user_storage.find_by_username(admin_username)
    if admin_row is None:
        logger.info(
            "system project seed skipped — admin user %s not found", admin_username,
        )
        return None
    project_id = project_storage.create_system_project_if_missing(
        name=_SYSTEM_PROJECT_NAME,
        owner_id=int(admin_row.id),
    )
    logger.info(
        "system project seed ensured name=%s id=%s owner_id=%s",
        _SYSTEM_PROJECT_NAME, project_id, int(admin_row.id),
    )
    return project_id


def _configure_app(app: Flask, cfg: dict[str, Any]) -> None:
    lifetime_hours = int(cfg["SESSION_LIFETIME_HOURS"])
    lifetime = timedelta(hours=lifetime_hours)
    app.config.update(
        SECRET_KEY=cfg["SECRET_KEY"],
        SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
        SESSION_COOKIE_HTTPONLY=bool(cfg["SESSION_COOKIE_HTTPONLY"]),
        SESSION_COOKIE_SECURE=bool(cfg["SESSION_COOKIE_SECURE"]),
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=lifetime,
        JSON_AS_ASCII=False,
    )
    # Use a server-side session keyed by an opaque sid cookie. The cookie's
    # MAX_AGE mirrors the DB row's expires_at; expiry checks live in storage.
    app.config.setdefault("SESSION_REFRESH_EACH_REQUEST", False)
    app.permanent_session_lifetime = lifetime
    logger.info(
        "flask config applied secret_set=%s lifetime_hours=%s secure=%s httponly=%s",
        bool(cfg["SECRET_KEY"]),
        lifetime_hours,
        bool(cfg["SESSION_COOKIE_SECURE"]),
        bool(cfg["SESSION_COOKIE_HTTPONLY"]),
    )


# v0.9.5 P0-1/2 — Chinese error pages. Three small HTML templates
# under ``app/templates/errors/`` replace Flask's default English
# 404/405/403 pages. The 404 page also carries a P0-8 UI hint for
# signed-in visitors hitting a /projects/<n> 404 (UI-only; the
# server-side 404 is unchanged per the 7/22 RBAC 业务级 lock).
_ERROR_TEMPLATES: dict[int, str] = {
    403: "errors/403.html",
    404: "errors/404.html",
    405: "errors/405.html",
}


def _register_error_handlers(app: Flask) -> None:
    """Bind localised HTML responses to HTTP 403 / 404 / 405.

    Each handler returns ``render_template(<path>)`` with the
    matching status code so the page renders the same chrome as
    the rest of the app (nav + footer + footer year) and the
    HTTP status stays correct. JSON clients still get JSON
    because ``wants_json`` is honoured: a curl ``Accept:
    application/json`` request keeps the legacy JSON body, a
    browser navigation gets the localised HTML.
    """
    for code, template_name in _ERROR_TEMPLATES.items():
        app.register_error_handler(code, _make_handler(code, template_name))
    logger.info(
        "error handlers registered: codes=%s templates=%s",
        sorted(_ERROR_TEMPLATES),
        sorted(_ERROR_TEMPLATES.values()),
    )


def _make_handler(code: int, template_name: str):
    """Build a Flask error handler closure for ``code`` → ``template_name``.

    Captures ``code`` and ``template_name`` so the registered handler
    can be a free function (Flask refuses a decorator-factory inside
    a comprehension otherwise). Honours ``wants_json`` so JSON
    clients keep their JSON response; browser navigations get HTML.
    """
    from flask import request

    def _handler(_exc):
        # v0.9.5 P0-1/2 — JSON-aware. ``wants_json`` was on
        # ``flask.Request`` in older Flask but lives on
        # ``werkzeug.wrappers.Request`` in Flask 3.x. The public
        # contract: ``accept_mimetypes`` + check for
        # ``application/json``. Browsers get HTML.
        accepts = request.accept_mimetypes
        if accepts and "application/json" in accepts:
            from flask import jsonify
            return jsonify({"error": _STATUS_LABELS.get(code, "error")}), code
        return render_template(template_name), code

    return _handler


_STATUS_LABELS: dict[int, str] = {
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}


__all__ = ["create_app"]
