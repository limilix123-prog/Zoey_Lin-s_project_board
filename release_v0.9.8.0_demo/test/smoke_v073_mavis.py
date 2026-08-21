"""v0.9.8 experiment — /api/v1/system/status smoke (sub-agent worker trial).

1 case 1 行为: GET /api/v1/system/status 返回 200 + 6-field JSON + 字段值合理。

Matches the 7 existing smokes' ``app.test_client`` + temp-DB pattern so
no external server is required and the smoke is self-contained.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# temp DB so the smoke does not pollute the real data/project_board.db.
# Matches the convention used by smoke_v032 / v061 / v070 etc.
_TMP_DB = Path(r"C:\Users\lying\temp\smoke_v073_mavis.db")
_TMP_DB.parent.mkdir(parents=True, exist_ok=True)
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["PROJECT_BOARD_DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("PROJECT_BOARD_SECRET_KEY", "smoke-v073-mavis")

# workspace on sys.path so ``import project_board`` resolves regardless of
# where the harness invokes the smoke from.
_WORKSPACE = Path(r"C:\Users\lying\.minimax-agent-cn\projects")
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from project_board.app.feature_app_factory import create_app  # noqa: E402

# run_seed=False: the new endpoint is read-only and does not depend on
# the bootstrap admin / manager / project_leader / team_leader /
# system-project seed. Skipping the seed keeps the smoke focused on
# the new behaviour and avoids touching the v0.9.7.0 init contract.
app = create_app(run_seed=False)
client = app.test_client(use_cookies=False)

PASS = 0
FAIL = 0


def _step(label, ok, detail=""):
    global PASS, FAIL
    tag = "OK" if ok else "FAIL"
    print(f"  [{tag}] {label}" + (f"  -- {detail}" if detail else ""), flush=True)
    PASS += 1 if ok else 0
    FAIL += 0 if ok else 1


# ===== Case 1: GET 200 + 6-field JSON + 字段值合理 =====
r = client.get("/api/v1/system/status")
ok_status = r.status_code == 200
data = r.get_json(silent=True) or {}
fields = (
    "version", "db_schema", "users_count", "projects_count",
    "uptime_seconds", "timestamp",
)
ok_fields = all(f in data for f in fields)
ok_version = data.get("version") == "0.9.7.0"
ok_schema = data.get("db_schema") in ("ok", "error")
ok_users = isinstance(data.get("users_count"), int) and data.get("users_count") >= 0
ok_projects = isinstance(data.get("projects_count"), int) and data.get("projects_count") >= 0
ok_uptime = isinstance(data.get("uptime_seconds"), int) and data.get("uptime_seconds") >= 0
ok_timestamp = isinstance(data.get("timestamp"), str) and "T" in data.get("timestamp", "")

all_ok = (
    ok_status
    and ok_fields
    and ok_version
    and ok_schema
    and ok_users
    and ok_projects
    and ok_uptime
    and ok_timestamp
)
detail = (
    f"status={r.status_code} fields={len(data)} "
    f"version={data.get('version')} db_schema={data.get('db_schema')} "
    f"users={data.get('users_count')} projects={data.get('projects_count')} "
    f"uptime={data.get('uptime_seconds')} ts={data.get('timestamp')}"
)
_step(
    "smoke_api_v1_status_001: GET 200 + 6-field JSON + 字段值合理",
    all_ok,
    detail,
)

print(f"\nTOTAL: pass={PASS} fail={FAIL}", flush=True)
raise SystemExit(0 if FAIL == 0 else 1)
