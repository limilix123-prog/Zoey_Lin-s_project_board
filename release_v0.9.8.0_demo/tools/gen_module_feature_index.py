'''Generate module × feature index markdown table for project_board/readme.md.

Scans project_board/<module>/ directories and emits a markdown table with one row
per module: name + responsibility + feature count + feature list.

Responsibility extraction priority:
    1. Second non-title paragraph in project_board/<module>/readme.md
       (i.e. the first non-blank line after the # <module> heading)
    2. Top docstring of project_board/<module>/__init__.py
    3. "(无职责描述)" literal fallback

Feature list: every file in project_board/<module>/ named feature_*.py,
sorted lexicographically by stem.

CLI:
    python tools/gen_module_feature_index.py                    # markdown table on stdout
    python tools/gen_module_feature_index.py --module projects  # filter to one module
    python tools/gen_module_feature_index.py --json             # JSON on stdout
    python tools/gen_module_feature_index.py --write            # write back to readme.md
    python tools/gen_module_feature_index.py --write --backup   # also copy readme to history/

Stdlib only: argparse, ast, json, re, sys, pathlib.
'''

import argparse
import ast
import json
import re
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT_ROOT = WORKSPACE / 'project_board'
DEFAULT_README = DEFAULT_PROJECT_ROOT / 'readme.md'
BACKUP_DIR = WORKSPACE / 'history' / 'project_board_v081_pre_readme'
BACKUP_FILE = BACKUP_DIR / 'readme.md'

# Match the heading we own: "## 模块结构" or "## 模块-特性目录".
# This is deliberately narrow so we never touch the v0.x.x(当前 milestone...) heading
# or any other section.
SECTION_HEADING_RE = re.compile(r'(?m)^## (?:模块结构|模块-特性目录)\s*$')


def configure_stdio():
    '''Force UTF-8 output so Chinese module names / responsibilities don't mojibake on Windows.'''
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            # Some embedded runners don't allow reconfigure; fall back to env var.
            pass


def extract_readme_responsibility(readme_path):
    '''Return the first non-blank line after the # <module> heading, or None.'''
    if not readme_path.is_file():
        return None
    try:
        text = readme_path.read_text(encoding='utf-8')
    except OSError as exc:
        print(f'WARN: read {readme_path} failed: {exc}', file=sys.stderr)
        return None
    lines = text.splitlines()
    seen_h1 = False
    for line in lines:
        stripped = line.strip()
        if not seen_h1:
            # accept "# foo" (h1) but not "## foo" (h2) as the module title
            if stripped.startswith('# ') and not stripped.startswith('## '):
                seen_h1 = True
            continue
        # any subsequent heading (h1/h2/...) ends the prose preamble
        if stripped.startswith('# '):
            return None
        if not stripped:
            continue
        return stripped
    return None


def extract_init_docstring(init_path):
    '''Return the first non-blank line of the module-level docstring, or None.'''
    if not init_path.is_file():
        return None
    try:
        src = init_path.read_text(encoding='utf-8')
    except OSError as exc:
        print(f'WARN: read {init_path} failed: {exc}', file=sys.stderr)
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    if not tree.body:
        return None
    first = tree.body[0]
    if not isinstance(first, ast.Expr):
        return None
    val = first.value
    if not isinstance(val, ast.Constant) or not isinstance(val.value, str):
        return None
    for line in val.value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def list_features(module_dir):
    '''Return sorted list of feature_*.py stems in module_dir.'''
    if not module_dir.is_dir():
        return []
    stems = []
    for p in module_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if not (name.startswith('feature_') and name.endswith('.py')):
            continue
        stems.append(name[:-3])  # drop ".py"
    return sorted(stems)


def scan_module(module_dir):
    '''Return (responsibility, features) for one module dir.'''
    readme = module_dir / 'readme.md'
    init = module_dir / '__init__.py'
    resp = extract_readme_responsibility(readme)
    if resp is None:
        resp = extract_init_docstring(init)
    if resp is None:
        if not readme.is_file() and not init.is_file():
            print(f'WARN: {module_dir.name}/ has no readme.md and no __init__.py', file=sys.stderr)
        resp = '(无职责描述)'
    return resp, list_features(module_dir)


def scan_project(project_root):
    '''Return list of (module_name, responsibility, features) sorted by name.

    Includes every immediate subdir of project_root (including data/ which has no
    __init__.py). Hidden / dunder / non-dir entries are skipped.
    '''
    if not project_root.is_dir():
        return []
    out = []
    for child in sorted(project_root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name.startswith('.') or child.name.startswith('__'):
            continue
        resp, features = scan_module(child)
        out.append((child.name, resp, features))
    return out


def render_markdown_table(rows):
    '''Return markdown table string for the given rows.'''
    lines = ['| 模块 | 职责 | 特性数 | 特性列表 |', '|---|---|---|---|']
    for name, resp, features in rows:
        feat_list = ', '.join(features) if features else '(无特性)'
        # escape pipe inside responsibility (rare, but safe)
        resp_esc = resp.replace('|', '\\|')
        lines.append(f'| {name} | {resp_esc} | {len(features)} | {feat_list} |')
    return '\n'.join(lines) + '\n'


def render_json(rows):
    '''Return JSON array string for the given rows.'''
    payload = [
        {
            'module': name,
            'responsibility': resp,
            'feature_count': len(features),
            'features': features,
        }
        for name, resp, features in rows
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'


def find_section_end(text, after_heading_pos):
    '''Return absolute index of the next '## ' heading at column 0, or len(text).'''
    rest = text[after_heading_pos:]
    m = re.search(r'(?m)^## ', rest)
    if m is None:
        return len(text)
    return after_heading_pos + m.start()


def build_new_section(table_md):
    '''Wrap the table in a full section block, with a trailing blank line so the
    next ## heading is visually separated (matches the original readme style).'''
    if not table_md.endswith('\n'):
        table_md = table_md + '\n'
    return '## 模块-特性目录\n\n' + table_md + '\n'


def update_readme(readme_path, new_section, backup):
    '''Replace the ## 模块-特性目录 (or ## 模块结构) section in readme_path.

    Preserves all other sections untouched. If no matching section exists, appends
    the new section to the end of the file.
    '''
    if not readme_path.is_file():
        print(f'ERROR: readme not found: {readme_path}', file=sys.stderr)
        return False
    text = readme_path.read_text(encoding='utf-8')
    match = SECTION_HEADING_RE.search(text)
    if match is None:
        # No existing section — append at the end of the file.
        new_text = text.rstrip() + '\n\n' + new_section
    else:
        section_start = match.start()
        section_end = find_section_end(text, match.end())
        new_text = text[:section_start] + new_section + text[section_end:]
    if backup:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_FILE.write_text(text, encoding='utf-8')
        print(f'[BACKUP] {BACKUP_FILE}', file=sys.stderr)
    readme_path.write_text(new_text, encoding='utf-8')
    print(f'[WROTE] {readme_path}', file=sys.stderr)
    return True


def main(argv=None):
    configure_stdio()
    parser = argparse.ArgumentParser(
        description='Generate module × feature index for project_board/readme.md.',
    )
    parser.add_argument(
        '--project-root',
        default=str(DEFAULT_PROJECT_ROOT),
        help=f'Project root dir (default: {DEFAULT_PROJECT_ROOT})',
    )
    parser.add_argument(
        '--module',
        default=None,
        help='Filter output to a single module name (still scans all modules).',
    )
    parser.add_argument(
        '--json',
        dest='as_json',
        action='store_true',
        help='Emit JSON instead of markdown table.',
    )
    parser.add_argument(
        '--write',
        action='store_true',
        help='Write the full (un-filtered) table into project_board/readme.md '
             '## 模块-特性目录 section. Replaces ## 模块结构 if present.',
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        help='When used with --write, copy the original readme.md to '
             f'{BACKUP_FILE} before overwriting.',
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root)
    rows = scan_project(project_root)

    if args.as_json:
        filtered = rows if args.module is None else [r for r in rows if r[0] == args.module]
        sys.stdout.write(render_json(filtered))
    else:
        filtered = rows if args.module is None else [r for r in rows if r[0] == args.module]
        sys.stdout.write(render_markdown_table(filtered))

    if args.write:
        # --write always uses the full table so the readme reflects the whole project.
        # Module filter applies only to stdout preview.
        table_md = render_markdown_table(rows)
        new_section = build_new_section(table_md)
        if not update_readme(DEFAULT_README, new_section, backup=args.backup):
            return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
