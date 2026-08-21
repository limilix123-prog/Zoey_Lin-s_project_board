"""v0.9.0 — :class:`ProjectStorage` Feature Board methods split-out.

The four ``project_features`` methods — ``create_feature``,
``list_features``, ``move_feature``, ``delete_feature`` — live
here rather than in :mod:`project_board.projects.feature_storage`
so the latter stays under the 1000-line cleancode cap.

The methods are attached to :class:`ProjectStorage` at import
time via :func:`install_feature_methods` below so the public
API (``storage.create_feature(...)`` etc.) is unchanged when
called from the legacy v0.6.1 feature_board route layer or
the v0.9.3 unified board view.

The DDL for ``project_features`` stays in
:mod:`feature_storage._SCHEMA_SQL` so :meth:`ProjectStorage.init_schema`
remains the single source of table creation.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _do_create_feature(
    self,
    project_id: int,
    name: str,
    description: str,
    status: str = "backlog",
) -> int:
    """Insert a feature row. Returns the new id.

    Server-side chokepoint for the "Add feature" endpoint (7/22
    RBAC business-lock principle). The route handler is the only
    caller; rank-based RBAC lives in the ``can_manage_members``
    helper which the route layer checks before reaching this
    method so the storage layer stays policy-agnostic and
    trivially unit-testable.

    ``status`` defaults to ``"backlog"`` so a freshly-added
    feature lands at the start of the board. ``position`` is
    always ``0`` because the current UI does not expose an
    ordering control — features are sorted by ``created_at``
    inside each column. The whitelist check raises ``ValueError``
    so the route can surface a 400 instead of planting a row the
    template cannot render.
    """
    # Local import keeps the cycle soft: this module is imported
    # by feature_storage at module-body level, so a module-level
    # import would resolve before the constants exist. A
    # function-body import resolves lazily on the first call.
    from .feature_storage import _FEATURE_STATUSES, _now_iso

    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("feature name is required")
    clean_status = str(status or "backlog").strip().lower()
    if clean_status not in _FEATURE_STATUSES:
        raise ValueError(f"invalid status: {clean_status!r}")
    now = _now_iso()
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO project_features "
                "(project_id, name, description, status, "
                "position, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(project_id),
                    clean_name,
                    str(description or ""),
                    clean_status,
                    0,
                    now,
                    now,
                ),
            )
            new_id = int(cur.lastrowid)
        finally:
            conn.close()
    logger.info(
        "project feature created id=%s project_id=%s status=%s",
        new_id, int(project_id), clean_status,
    )
    return new_id


def _do_list_features(self, project_id: int) -> list[FeatureRow]:
    """Return every feature belonging to ``project_id``.

    The result is sorted by ``(status, created_at ASC)`` so the
    template can iterate the four columns in column order; the
    secondary ``created_at`` sort keeps the insertion order
    within each column stable across requests. The composite
    index ``idx_features_project_status`` covers the leading
    ``project_id, status`` columns so the query is a single
    index scan on the project subtree.
    """
    from .feature_storage import FeatureRow

    with self._lock:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, project_id, name, description, status, "
                "position, created_at, updated_at "
                "FROM project_features "
                "WHERE project_id = ? "
                "ORDER BY status ASC, created_at ASC",
                (int(project_id),),
            ).fetchall()
            return [FeatureRow.from_row(r) for r in rows]
        finally:
            conn.close()


def _do_move_feature(
    self,
    project_id: int,
    feature_id: int,
    new_status: str,
) -> bool:
    """Reassign a feature's status. Returns True iff a row was changed.

    The cross-project guard is enforced by the ``AND project_id = ?``
    clause in the UPDATE — a hand-crafted POST that pairs a
    project the actor owns with a feature id from a different
    project changes zero rows and returns False, which the route
    layer maps to 404. The whitelist check raises ``ValueError``
    for unknown statuses so the route surfaces a 400 instead of
    planting an unrenderable row.
    """
    from .feature_storage import _FEATURE_STATUSES, _now_iso

    clean_status = str(new_status or "").strip().lower()
    if clean_status not in _FEATURE_STATUSES:
        raise ValueError(f"invalid status: {clean_status!r}")
    now = _now_iso()
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE project_features "
                "SET status = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                (clean_status, now, int(feature_id), int(project_id)),
            )
            changed = cur.rowcount > 0
        finally:
            conn.close()
    if changed:
        logger.info(
            "project feature moved project_id=%s feature_id=%s "
            "new_status=%s",
            int(project_id), int(feature_id), clean_status,
        )
    return changed


def _do_delete_feature(self, project_id: int, feature_id: int) -> bool:
    """Delete a feature row. Returns True iff a row was removed.

    The cross-project guard is enforced by the ``AND project_id = ?``
    clause in the DELETE — a hand-crafted DELETE that pairs a
    project the actor owns with a feature id from a different
    project removes zero rows and returns False, which the route
    layer maps to 404.
    """
    with self._lock:
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM project_features "
                "WHERE id = ? AND project_id = ?",
                (int(feature_id), int(project_id)),
            )
            removed = cur.rowcount > 0
        finally:
            conn.close()
    if removed:
        logger.info(
            "project feature deleted project_id=%s feature_id=%s",
            int(project_id), int(feature_id),
        )
    return removed


def install_feature_methods() -> None:
    """Attach the four feature methods to :class:`ProjectStorage`.

    Called by :mod:`feature_storage` at the bottom of the module
    (after :class:`ProjectStorage` is fully defined). The
    function is a no-op for any method that is already installed
    (idempotent re-import).
    """
    from .feature_storage import ProjectStorage

    _FEATURE_METHODS = {
        "create_feature": _do_create_feature,
        "list_features": _do_list_features,
        "move_feature": _do_move_feature,
        "delete_feature": _do_delete_feature,
    }
    for _name, _method in _FEATURE_METHODS.items():
        if _name not in ProjectStorage.__dict__:
            setattr(ProjectStorage, _name, _method)


# Install on import. The bottom of feature_storage.py also calls
# this defensively; running it twice is a no-op.
install_feature_methods()


__all__ = ["install_feature_methods"]
