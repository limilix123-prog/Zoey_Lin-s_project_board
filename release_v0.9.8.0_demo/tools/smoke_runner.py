"""Run the workspace's smoke suite (test/smoke_v*_mavis.py).

Discovers every ``smoke_v*_mavis.py`` under ``test/`` and runs each one in a
fresh subprocess, capturing its ``TOTAL: pass=… fail=…`` summary line.

Design constraints (cross-project lessons from 2026-07-22):

- **subprocess, not import**: each smoke script boots its own Flask app
  and temp DB; importing would leak state between runs.
- **Windows GBK stdout**: child Python's stdout is encoded with the
  console code page; we read raw bytes and regex-match the summary
  rather than relying on UTF-8 decoding.
- **cwd must be str, not Path**: ``subprocess.run(cwd=Path(...))`` raises
  WinError 267 on Windows; always pass ``cwd=str(workspace_root)``.
- **stdlib only**: argparse, re, subprocess, sys, pathlib.

CLI:
    python tools/smoke_runner.py --all              # run every smoke
    python tools/smoke_runner.py --id v032          # run one smoke
    python tools/smoke_runner.py --id v053 --id v061 # run several
    python tools/smoke_runner.py --list             # print discovered ids
    python tools/smoke_runner.py --quiet            # suppress per-smoke logs

Exit code: 0 if every smoke reports FAIL=0, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# --- workspace resolution (mirror tools/code_cleanliness_check.py) --------

WORKSPACE = Path(__file__).resolve().parent.parent
TEST_DIR = WORKSPACE / "test"

# Match: "TOTAL: pass=49 fail=0" (allow extra whitespace / trailing chars).
# We intentionally accept any integer for pass/fail so the regex doesn't
# hardcode the v0.8 baseline.
TOTAL_RE = re.compile(rb"TOTAL:\s*pass=(\d+)\s+fail=(\d+)")

# Fallback: smoke script may legitimately crash before printing TOTAL. We
# also capture the "Traceback" head / "ERROR:" tail so the operator can
# see *why* without re-running.
SUMMARY_LINE_RE = re.compile(rb"TOTAL:\s*pass=\d+\s+fail=\d+")


# --- discovery -------------------------------------------------------------


def discover_smokes(test_dir: Path) -> list[Path]:
    """Return smoke_v*_mavis.py files under test_dir, sorted by id."""
    if not test_dir.is_dir():
        return []
    return sorted(test_dir.glob("smoke_v*_mavis.py"))


def smoke_id(smoke_path: Path) -> str:
    """Extract the 'vXXX' id from a smoke path stem (e.g. 'smoke_v032_mavis')."""
    stem = smoke_path.stem  # 'smoke_v032_mavis'
    parts = stem.split("_")
    for p in parts:
        if p.startswith("v") and p[1:].isdigit():
            return p
    return stem


# --- single-smoke runner ---------------------------------------------------


def run_one(smoke_path: Path, *, quiet: bool = False) -> tuple[int, int, int]:
    """Run one smoke script in a subprocess.

    Returns (returncode, pass_count, fail_count). If the summary line is
    missing (e.g. crash), pass=0, fail=0 and the caller treats returncode!=0
    as a failure.
    """
    cmd = [sys.executable, str(smoke_path)]
    # 7/22 lesson: cwd MUST be str, not Path, on Windows.
    proc = subprocess.run(
        cmd,
        cwd=str(WORKSPACE),
        capture_output=True,
    )

    # 7/22 lesson: Windows child stdout is GBK-encoded; regex over bytes.
    out_bytes = proc.stdout

    match = TOTAL_RE.search(out_bytes)
    if match:
        pass_n = int(match.group(1))
        fail_n = int(match.group(2))
    else:
        pass_n = 0
        fail_n = 0

    sid = smoke_id(smoke_path)
    if not quiet:
        if match:
            sys.stdout.write(
                f"  [{sid}] pass={pass_n} fail={fail_n} "
                f"returncode={proc.returncode}\n"
            )
        else:
            # No summary line — likely a crash. Echo last 30 stdout lines
            # + stderr so the operator can see what happened.
            tail = b"\n".join(out_bytes.splitlines()[-30:])
            sys.stdout.write(
                f"  [{sid}] NO SUMMARY (returncode={proc.returncode})\n"
            )
            if tail.strip():
                sys.stdout.write("  --- stdout tail ---\n")
                for line in tail.decode("utf-8", errors="replace").splitlines():
                    sys.stdout.write(f"    {line}\n")
            if proc.stderr:
                sys.stdout.write("  --- stderr ---\n")
                for line in proc.stderr.decode("utf-8", errors="replace").splitlines():
                    sys.stdout.write(f"    {line}\n")
    sys.stdout.flush()

    return proc.returncode, pass_n, fail_n


# --- multi-smoke runner ----------------------------------------------------


def run_many(smoke_paths: list[Path], *, quiet: bool = False) -> tuple[int, int, int]:
    """Run a list of smokes sequentially. Returns (total_pass, total_fail, bad_count)."""
    total_pass = 0
    total_fail = 0
    bad = 0
    for sp in smoke_paths:
        rc, p, f = run_one(sp, quiet=quiet)
        total_pass += p
        total_fail += f
        if rc != 0 or f != 0:
            bad += 1
    return total_pass, total_fail, bad


# --- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the workspace's smoke suite (test/smoke_v*_mavis.py).",
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true",
                   help="Run every smoke discovered under test/.")
    g.add_argument("--id", action="append", default=[],
                   help="Run smoke(s) with the given id (e.g. v032). Repeatable.")
    g.add_argument("--list", action="store_true",
                   help="Print discovered smoke ids and exit 0.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-smoke log lines (only print final total).")
    args = parser.parse_args(argv)

    discovered = discover_smokes(TEST_DIR)
    if not discovered:
        sys.stderr.write(f"smoke_runner: no smoke_v*_mavis.py under {TEST_DIR}\n")
        return 1

    if args.list:
        for sp in discovered:
            sys.stdout.write(f"{smoke_id(sp)}\t{sp.name}\n")
        return 0

    if args.all:
        targets = discovered
    else:
        # Resolve --id entries against discovered stems.
        by_id = {smoke_id(sp): sp for sp in discovered}
        targets = []
        missing = []
        for sid in args.id:
            if sid in by_id:
                targets.append(by_id[sid])
            else:
                missing.append(sid)
        if missing:
            sys.stderr.write(
                f"smoke_runner: unknown id(s): {', '.join(missing)}\n"
                f"  available: {', '.join(sorted(by_id))}\n"
            )
            return 1

    if not args.quiet:
        sys.stdout.write(f"smoke_runner: {len(targets)} smoke(s) under {TEST_DIR}\n")

    total_pass, total_fail, bad = run_many(targets, quiet=args.quiet)

    sys.stdout.write(
        f"\nTOTAL: pass={total_pass} fail={total_fail} bad_smokes={bad}\n"
    )
    sys.stdout.flush()
    return 0 if bad == 0 and total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
