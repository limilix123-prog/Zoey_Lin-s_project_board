#!/usr/bin/env python3
'''code_cleanliness_check - 5-rule code cleanliness scanner for Python files.

Scans a directory (or single file) and reports five classes of violation:
  1. file_too_long        : total file line count > MAX_FILE_LINES
  2. function_too_long    : any function/method body lines > MAX_FUNC_BODY_LINES
  3. docstring_style_mixed: docstrings in one file use BOTH the triple-single
                            delimiter and the triple-double delimiter
  4. comment_block_too_long: more than MAX_CONSECUTIVE_COMMENTS consecutive
                             standalone '#' comment lines
  5. line_too_long        : any source line exceeds MAX_LINE_CHARS characters
                            (after rstrip); string literal lines are skipped

All thresholds are constants at the top of the module. The scanner uses
``ast`` for structural analysis (function bodies, docstring locations) and
``tokenize`` to mark string-literal line ranges. Plain line scanning is
used for comment runs, file length, and per-line character count.
Docstring *style* is inspected by looking at the first non-whitespace
character on the docstring's source line - AST gives the string value
but not the delimiter style. Rule 3 fires only when a file MIXES the two
styles; a file that uses exclusively one of them is fine.

Stdlib only: argparse, ast, io, json, logging, pathlib, sys, tokenize.
'''

from __future__ import annotations

import argparse
import ast
import io
import json
import logging
import sys
import tokenize
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MAX_FILE_LINES = 1000
MAX_FUNC_BODY_LINES = 200
MAX_CONSECUTIVE_COMMENTS = 5
MAX_LINE_CHARS = 128

TRIPLE_SINGLE = "'''"
TRIPLE_DOUBLE = '"""'


# ---------------------------------------------------------------------------
# File / source helpers
# ---------------------------------------------------------------------------

def iter_python_files(path: Path):
    '''Yield .py files at ``path`` (file or recursive directory).

    Directory yields are sorted so output is deterministic across runs.
    '''
    if path.is_file():
        if path.suffix == ".py":
            yield path
        return
    if path.is_dir():
        for p in sorted(path.rglob("*.py")):
            if p.is_file():
                yield p


def _read_source(path: Path) -> str:
    '''Read a file as utf-8; return ``""`` and warn on failure.'''
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        logger.warning("cannot read %s: %s", path, exc)
        return ""


def _parse_tree(path: Path, source: str):
    '''Parse source to AST; return ``None`` on syntax error.'''
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.warning("syntax error in %s: %s", path, exc)
        return None


def _line_count(text: str) -> int:
    '''Physical line count that handles trailing newline correctly.'''
    if not text:
        return 0
    return len(text.splitlines())


def _first_docstring_expr(body):
    '''Return the first ``Expr(Constant(str))`` statement in ``body`` else None.'''
    if not body:
        return None
    first = body[0]
    if not isinstance(first, ast.Expr):
        return None
    if not isinstance(first.value, ast.Constant):
        return None
    if not isinstance(first.value.value, str):
        return None
    return first


# ---------------------------------------------------------------------------
# Rule 1 - file too long
# ---------------------------------------------------------------------------

def check_file_length(path: Path, source: str) -> list:
    '''Return a violation dict if the file exceeds MAX_FILE_LINES.'''
    total = _line_count(source)
    if total > MAX_FILE_LINES:
        return [{
            "rule": "file_too_long",
            "path": str(path),
            "lines": total,
        }]
    return []


# ---------------------------------------------------------------------------
# Rule 2 - function body too long
# ---------------------------------------------------------------------------

def check_function_length(path: Path, tree) -> list:
    '''Return a violation for every function whose body is too long.'''
    if tree is None:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        body_lines = end - node.lineno
        if body_lines > MAX_FUNC_BODY_LINES:
            out.append({
                "rule": "function_too_long",
                "path": str(path),
                "start": node.lineno,
                "end": end,
                "name": node.name,
                "body_lines": body_lines,
            })
    return out


# ---------------------------------------------------------------------------
# Rule 3 - docstring form
# ---------------------------------------------------------------------------

def _classify_doc_form(source_lines, doc_node):
    '''Return the opening delimiter on the docstring's first line, or None.'''
    if doc_node.lineno < 1 or doc_node.lineno > len(source_lines):
        return None
    first = source_lines[doc_node.lineno - 1].lstrip()
    if first.startswith(TRIPLE_SINGLE):
        return TRIPLE_SINGLE
    if first.startswith(TRIPLE_DOUBLE):
        return TRIPLE_DOUBLE
    return None


def check_docstring_style_mixed(path: Path, source: str, tree) -> list:
    '''Return a violation when a file mixes triple-single and triple-double docstring forms.

    Rule 3 enforces per-file consistency of docstring delimiter style.
    Missing docstrings are not flagged here - the rule only cares about
    forms that are actually used. If the set of distinct forms seen in
    the file has size > 1, one violation is reported listing both forms
    and the count of each. Files with zero or one distinct form are clean
    regardless of which form they pick (triple-double or triple-single).
    '''
    if tree is None:
        return []
    source_lines = source.splitlines()
    observed = []  # preserve first-occurrence order of each form
    # Module-level docstring
    mod_doc = _first_docstring_expr(tree.body)
    if mod_doc is not None:
        form = _classify_doc_form(source_lines, mod_doc)
        if form is not None:
            observed.append(form)
    # Function / method docstrings
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = _first_docstring_expr(node.body)
        if doc is None:
            continue
        form = _classify_doc_form(source_lines, doc)
        if form is not None:
            observed.append(form)
    if len(set(observed)) <= 1:
        return []
    # Mixed: count occurrences and report the two forms in encounter order
    form_a = observed[0]
    form_b = next(f for f in observed if f != form_a)
    count_a = observed.count(form_a)
    count_b = observed.count(form_b)
    return [{
        "rule": "docstring_style_mixed",
        "path": str(path),
        "form_a": form_a,
        "count_a": count_a,
        "form_b": form_b,
        "count_b": count_b,
    }]


# ---------------------------------------------------------------------------
# Rule 4 - consecutive # comment blocks
# ---------------------------------------------------------------------------

def _docstring_line_set(tree):
    '''Return the set of 1-indexed line numbers that lie inside any docstring.'''
    in_doc = set()
    if tree is None:
        return in_doc
    mod_doc = _first_docstring_expr(tree.body)
    if mod_doc is not None and mod_doc.end_lineno is not None:
        for ln in range(mod_doc.lineno, mod_doc.end_lineno + 1):
            in_doc.add(ln)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        doc = _first_docstring_expr(node.body)
        if doc is None or doc.end_lineno is None:
            continue
        for ln in range(doc.lineno, doc.end_lineno + 1):
            in_doc.add(ln)
    return in_doc


def check_comment_blocks(path: Path, source: str, tree) -> list:
    '''Return violations for runs of consecutive ``#``-only lines that exceed the limit.

    Blank lines (or any non-comment line) break a run. Lines that fall
    inside a docstring are skipped - those ``#`` characters are docstring
    content, not source-level comments.
    '''
    out = []
    source_lines = source.splitlines()
    in_doc = _docstring_line_set(tree)
    run_start = None
    run_len = 0

    def _flush():
        if run_len > MAX_CONSECUTIVE_COMMENTS:
            out.append({
                "rule": "comment_block_too_long",
                "path": str(path),
                "start": run_start,
                "end": run_start + run_len - 1,
                "count": run_len,
            })

    for idx, line in enumerate(source_lines, start=1):
        if idx in in_doc:
            _flush()
            run_start = None
            run_len = 0
            continue
        if line.lstrip().startswith("#"):
            if run_start is None:
                run_start = idx
            run_len += 1
        else:
            _flush()
            run_start = None
            run_len = 0
    _flush()
    return out


# ---------------------------------------------------------------------------
# Rule 5 - per-line character count
# ---------------------------------------------------------------------------

def _string_line_set(source: str):
    '''Return the set of 1-indexed line numbers that fall inside any string literal.

    A STRING token spans one or more source lines; if ``start_row`` and
    ``end_row`` differ, every row in between belongs to the same literal
    (triple-quoted block or backslash-continued single-line string). The
    caller uses this set to skip author-written text when measuring line
    length. If the file cannot be tokenized, the empty set is returned -
    unparseable files produce no Rule 5 violations, matching the AST
    rules' behavior of yielding nothing for a broken tree.
    '''
    in_str = set()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenizeError, IndentationError, SyntaxError, OSError):
        return in_str
    for tok in tokens:
        if tok.type == tokenize.STRING:
            for ln in range(tok.start[0], tok.end[0] + 1):
                in_str.add(ln)
    return in_str


def check_line_length(path: Path, source: str, max_chars: int) -> list:
    '''Return a violation for every source line whose char count exceeds ``max_chars``.

    Trailing whitespace is not counted (``line.rstrip()`` before measuring).
    Blank / whitespace-only lines never violate. Lines inside a string
    literal (docstring, ordinary string, multi-line raw / f-string) are
    skipped - they are author-written text, not source code we want to
    measure against the line-length limit. The string-line set is built
    via ``tokenize`` so triple-quoted blocks and backslash continuations
    are handled correctly without ad-hoc heuristics.
    '''
    out = []
    in_str = _string_line_set(source)
    for idx, line in enumerate(source.splitlines(), start=1):
        if idx in in_str:
            continue
        n = len(line.rstrip())
        if n == 0:
            continue
        if n > max_chars:
            out.append({
                "rule": "line_too_long",
                "path": str(path),
                "line": idx,
                "chars": n,
            })
    return out


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def scan(path: Path, max_line_chars: int = MAX_LINE_CHARS) -> list:
    '''Run all five rules against every .py file found under ``path``.'''
    violations = []
    for py in iter_python_files(path):
        source = _read_source(py)
        if not source:
            continue
        tree = _parse_tree(py, source)
        violations.extend(check_file_length(py, source))
        violations.extend(check_function_length(py, tree))
        violations.extend(check_docstring_style_mixed(py, source, tree))
        violations.extend(check_comment_blocks(py, source, tree))
        violations.extend(check_line_length(py, source, max_line_chars))
    return violations


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_human(violations) -> str:
    '''Format the violation list as a human-readable report.'''
    if not violations:
        return "No violations found."
    lines = []
    for v in violations:
        rule = v["rule"]
        if rule == "file_too_long":
            lines.append(
                f"[FAIL] file_too_long: {v['path']} {v['lines']} lines"
            )
        elif rule == "function_too_long":
            lines.append(
                f"[FAIL] function_too_long: {v['path']}:{v['start']}-{v['end']} "
                f"name={v['name']} body={v['body_lines']} lines"
            )
        elif rule == "docstring_style_mixed":
            lines.append(
                f"[FAIL] docstring_style_mixed: {v['path']} "
                f"form_a={v['form_a']} count_a={v['count_a']} "
                f"form_b={v['form_b']} count_b={v['count_b']}"
            )
        elif rule == "comment_block_too_long":
            lines.append(
                f"[FAIL] comment_block_too_long: {v['path']}:{v['start']}-{v['end']} "
                f"{v['count']} consecutive"
            )
        elif rule == "line_too_long":
            lines.append(
                f"[FAIL] line_too_long: {v['path']}:{v['line']} {v['chars']} chars"
            )
    files = {v["path"] for v in violations}
    lines.append("")
    lines.append(f"TOTAL: {len(violations)} violations in {len(files)} files")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_default_path() -> Path:
    '''Default --path = ``<workspace>/project_board``.

    The tool lives at ``<workspace>/tools/code_cleanliness_check.py`` so
    ``__file__.parent.parent`` resolves to the workspace root.
    '''
    return Path(__file__).resolve().parent.parent / "project_board"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code_cleanliness_check",
        description=(
            "Scan Python files for 5 code-cleanliness rules: file length, "
            "function body length, docstring style consistency, "
            "consecutive # comment blocks, per-line character count."
        ),
    )
    parser.add_argument(
        "--path", type=Path, default=None,
        help="File or directory to scan (default: <workspace>/project_board/).",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 1 if any violation is found (CI / pre-commit).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit one JSON object per violation instead of human text.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Print only the total violation count.",
    )
    parser.add_argument(
        "--max-line-chars", type=int, default=MAX_LINE_CHARS,
        help="Rule 5 threshold: max chars per source line (default: %(default)s).",
    )
    return parser


def main(argv=None) -> int:
    '''CLI entry point. Returns the process exit code.'''
    args = _build_parser().parse_args(argv)
    target = args.path if args.path is not None else _resolve_default_path()

    violations = scan(target, args.max_line_chars)

    if args.quiet:
        print(len(violations))
    elif args.json:
        print(json.dumps(violations, indent=2, ensure_ascii=False))
    else:
        print(_format_human(violations))

    return 1 if (args.strict and violations) else 0


if __name__ == "__main__":
    sys.exit(main())
