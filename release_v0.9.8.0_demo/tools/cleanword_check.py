#!/usr/bin/env python3
'''cleanword_check - 7-rule self-reference / jargon scanner for text/code.

Scans a file or directory and reports seven classes of verbal bloat:

  1. tautology         : "X = X" / "X 即 X" / "X means X" / "X 就是 X"
  2. empty_template    : "X -> Y" where X and Y are both ALL_CAPS placeholders
  3. word_spam         : any non-trivial word repeats 3+ times in one text line
  4. cliche_prefix     : text line opens with a Chinese filler phrase and
                         is short enough to carry no payload after it
  5. formulaic_opener  : text line opens with a structural phrase
                         ("首先"/"其次"/"最后"/...) and is short
  6. repeated_sentence : two adjacent text lines are >= 85% character-identical
  7. filler_words      : a text line's share of high-frequency function words
                         (的/了/和/是/在 / the/is/of/a/and/to/in) exceeds 30%

Most rules apply only to TEXT lines (lines covered by STRING or COMMENT
tokens). A Python signature like ``def is_user(user: Optional[User]) -> bool:``
(with ``user`` three times) is never flagged as word_spam because tokenize
classifies it as code, not text. Tautology and empty_template also run on
code lines because ``X = X`` and ``FOO -> BAR`` make no more sense in code
than in prose, and short bare-variable assignments are not a noise source.

The DELETE flag, paired with BACKUP, removes offending text/code lines
from the target file: remaining lines are joined back with ``\\n`` and
the original is renamed to ``<file>.bak`` so a human can recover. The
tool never rewrites in place without an explicit opt-in.

Stdlib only: argparse, difflib, io, json, logging, pathlib, re, sys, tokenize.
'''

from __future__ import annotations

import argparse
import ast
import difflib
import io
import json
import logging
import re
import sys
import tokenize
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Rule 3: a single word appearing 4+ times on a text line. The
# threshold sits above the natural "the" / "a" / "X" density of a
# well-written English comment or docstring, so a normal 12-word
# sentence with 3 occurrences of "the" stays clean.
WORD_SPAM_MIN_COUNT = 4
# Rule 3: minimum word length to consider. Set to 1 so single-char
# Chinese particles (的/了/和) participate - 1 unicode char is the
# natural unit of CJK text. The count threshold is the spam signal,
# not the length threshold.
WORD_SPAM_MIN_LEN = 1

# Rule 4 / 5: text lines longer than this are assumed to carry enough
# real content after the opener to be useful, so we don't flag them.
CLICHE_PREFIX_MAX_CHARS = 30
FORMULAIC_OPENER_MAX_CHARS = 30

# Rule 6: char-level similarity threshold for two adjacent text lines
REPEATED_SENTENCE_RATIO = 0.85
# Rule 6: a line must be at least this long to count as a "sentence"
REPEATED_SENTENCE_MIN_CHARS = 6

# Rule 7: filler ratio > 0.50 AND total words >= 8 (high threshold +
# word floor combine to ignore short rule-description docstrings).
FILLER_WORD_RATIO = 0.50
FILLER_WORD_MIN_WORDS = 8


# ---------------------------------------------------------------------------
# File / source helpers
# ---------------------------------------------------------------------------

def iter_python_files(path: Path):
    '''Yield .py files at ``path`` (file or recursive directory).

    Yields are sorted so output is deterministic across runs.
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


def _string_expr_line_set(tree):
    '''Return the set of 1-indexed line numbers that are part of a STRING expression.

    Two flavours are both considered author-written text and are
    included here:

    * a docstring (``body[0]`` of a module / function / class body
      that is an ``Expr(Constant(str))``) - the conventional location.
    * a standalone string expression statement
      (``Expr(Constant(str))`` at any other position in a body).
      Two adjacent bare string statements are common in tests
      (``def f(): "a"; "b"``) and the second one is NOT a docstring
      but is still text the author meant the reader to see.

    Ordinary string literals in other syntactic positions
    (``foo = "x"``, ``print("hi")``, tuple members like
    ``_CLICHE_PREFIXES = ("重要的是", ...)``, ``return "..."``) are
    NOT included - they are code positions where a string happens to
    appear, not author-written prose. Including them would false-positive
    on the tool's own source where a constant tuple contains a rule
    phrase like "重要的是".

    The set includes every line from each string expression's opening
    delimiter to its closing one.
    '''
    in_set: set[int] = set()
    if tree is None:
        return in_set
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", None) or start
        for ln in range(start, end + 1):
            in_set.add(ln)
    return in_set


def _is_docstring_node(tree, node) -> bool:
    '''True iff ``node`` is the docstring of its enclosing scope.

    A docstring is the ``body[0]`` Expr(Constant(str)) of a module,
    function, async function, or class. Any other Expr(Constant(str))
    - even if it appears in a function body - is a standalone string
    statement, NOT a docstring. Distinguishing the two matters because
    multi-line docstrings get the "report once on start line" treatment
    while standalone string statements are treated as ordinary text
    lines (no merging).
    '''
    if not isinstance(node, ast.Expr):
        return False
    if not isinstance(node.value, ast.Constant):
        return False
    if not isinstance(node.value.value, str):
        return False
    parent_body = _parent_body(tree, node)
    return parent_body is not None and parent_body[0] is node


def _parent_body(tree, target):
    '''Return the body list that directly contains ``target`` AST node, or None.

    Used to check whether an ``Expr(Constant(str))`` is the first
    statement of a module / function / class body (i.e. a docstring)
    or just another statement inside one. Returns the parent body
    list so the caller can compare ``body[0] is target``.
    '''
    if tree is None:
        return None
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for child in body:
            if child is target:
                return body
    return None


def _text_units(source: str):
    '''Classify docstring + standalone-string + comment lines.

    Only the following are treated as text:
    * docstring lines (AST: body[0] Expr(Constant(str)) of module /
      function / class - any span in any body[0] docstring)
    * standalone string-expression statement lines
      (AST: any other Expr(Constant(str)) in a body)
    * comment lines (tokenize: COMMENT tokens)

    Ordinary string literals in other positions
    (``foo = "..."``, ``print("hi")``, tuple members of
    ``_CLICHE_PREFIXES = ("重要的是", ...)``) are NOT text. Including
    them would false-positive on the tool's own source where a
    constant tuple contains a rule phrase.

    The return tuple is ``(in_text, spans_by_line, internal_text_lines)``:

    * ``in_text`` - set of 1-indexed line numbers covered by any
      text unit. Text-only rules skip every other line.
    * ``spans_by_line`` - per-line list of ``(start_col, end_col, text)``
      so the word extractor can rebuild each line's STRING/COMMENT
      text without re-tokenizing.
    * ``internal_text_lines`` - set of line numbers that fall INSIDE
      a text unit (not the first or last line). Two flavours of
      internal:
      - lines inside a multi-line docstring (token spans > 1 line)
      - lines inside a run of consecutive ``#`` comments
      All text-only rules skip them so a 30-line docstring or a
      100-line ``# filler line 1..100`` block does not produce 30+
      reports. ``word_spam`` also skips them and reports once on the
      first line of the unit (its span covers the whole token, or
      the comment is small enough that a per-line analysis would
      double-count).
    '''
    in_text: set[int] = set()
    spans_by_line: dict[int, list[tuple[int, int, str]]] = {}
    internal_text_lines: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.warning("ast parse failed: %s", exc)
        tree = None
    string_expr_lines = _string_expr_line_set(tree)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, OSError) as exc:
        logger.warning("tokenize failed: %s", exc)
        return in_text, spans_by_line, internal_text_lines
    comment_lines: list[int] = []
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            in_text.add(tok.start[0])
            spans_by_line.setdefault(tok.start[0], []).append(
                (tok.start[1], tok.end[1], tok.string)
            )
            comment_lines.append(tok.start[0])
            continue
        if tok.type != tokenize.STRING:
            continue
        start_ln, start_col = tok.start
        end_ln, end_col = tok.end
        is_text_string = any(
            ln in string_expr_lines for ln in range(start_ln, end_ln + 1)
        )
        if not is_text_string:
            continue
        is_multi = end_ln > start_ln
        is_docstring = is_multi and _is_docstring_node(
            tree,
            _string_expr_at_line(tree, start_ln),
        )
        for ln in range(start_ln, end_ln + 1):
            in_text.add(ln)
            if is_multi and is_docstring and start_ln < ln < end_ln:
                internal_text_lines.add(ln)
            if ln == start_ln == end_ln:
                spans_by_line.setdefault(ln, []).append(
                    (start_col, end_col, tok.string)
                )
            elif ln == start_ln:
                spans_by_line.setdefault(ln, []).append(
                    (start_col, len(tok.string), tok.string)
                )
            elif ln == end_ln:
                spans_by_line.setdefault(ln, []).append(
                    (0, end_col, tok.string)
                )
            else:
                spans_by_line.setdefault(ln, []).append(
                    (0, len(tok.string), tok.string)
                )
    # Mark internal lines of consecutive comment blocks. A block is
    # a maximal run of comment lines with no gaps; lines other than
    # the first and last are skipped by every text-only rule so
    # ``# filler line 1`` / ``# filler line 2`` / ... does not
    # produce N-1 repeated_sentence reports.
    i = 0
    while i < len(comment_lines):
        j = i
        while j + 1 < len(comment_lines) and comment_lines[j + 1] == comment_lines[j] + 1:
            j += 1
        if j - i >= 1:
            for ln in comment_lines[i + 1:j]:
                internal_text_lines.add(ln)
        i = j + 1
    return in_text, spans_by_line, internal_text_lines


def _string_expr_at_line(tree, lineno):
    '''Return the AST node of the string expression starting at ``lineno``.

    Helper used by ``_text_units`` to decide whether a multi-line
    STRING token corresponds to a docstring (multi-line merging
    applies) or a standalone string statement (treat each line as
    ordinary text). Returns None if no matching node is found.
    '''
    if tree is None:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        if node.lineno == lineno:
            return node
    return None


def _words_in_text_line(lineno, source_lines, spans_by_line):
    '''Return the lowercase word tokens on a text line (string + comment parts).

    Two token flavours are emitted:
    * ASCII words - runs of ``[A-Za-z0-9_]+`` matched with the
      standard word-boundary convention (whitespace / punctuation
      break a run).
    * CJK characters - each ``[一-鿿]`` is emitted individually. CJK
      text has no spaces between characters, so matching
      ``[一-鿿]+`` would glue 17 ``的`` into a single "word" and
      miss the spam / filler signal. Per-character emission makes
      ``的的的的的...`` register 17 individual ``的`` tokens.

    Each span's column range is sliced against the source line
    itself, not the STRING token's full text - a multi-line STRING's
    start line is a span like ``(start_col, len(token_text))``; the
    clip to ``len(source_lines[lineno-1])`` keeps a docstring's
    content on its own lines instead of pulling the whole token onto
    the opening line.
    '''
    if lineno < 1 or lineno > len(source_lines):
        return []
    raw = source_lines[lineno - 1]
    spans = spans_by_line.get(lineno)
    if not spans:
        return []
    parts = []
    line_len = len(raw)
    for start_col, end_col, _text in spans:
        end_col = min(end_col, line_len)
        if end_col <= start_col:
            continue
        parts.append(raw[start_col:end_col])
    if not parts:
        return []
    blob = "\n".join(parts)
    blob = re.sub(r"```[^`]*```", " ", blob)
    blob = re.sub(r"``[^`]*``", " ", blob)
    blob = re.sub(r"`[^`]*`", " ", blob)
    ascii_words = re.findall(r"[A-Za-z0-9_]+", blob.lower())
    cjk_chars = re.findall(r"[一-鿿]", blob)
    return ascii_words + cjk_chars


# ---------------------------------------------------------------------------
# Rule 1 - tautology ("X is X" / "name is name" / "Y is Y" forms)
# ---------------------------------------------------------------------------

# Backref demands both sides of the operator be the same identifier.
# Trailing-punct class excludes ``,`` so kwargs calls
# (``render_template("x.html", storage=storage,)``) do not match.
# Bare ``    foo = foo`` and ``"""foo = foo"""`` match because
# they end bare or with one of ``.``, ``;``, ``:`` or ``)``.
_TAUTOLOGY_SENTINEL = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_一-鿿]*)"
    r"\s*(?:=|即|就是|means|is)"
    r"\s*\1"
    r"\s*[:.;)]?$"
)


def _violation_body(line: str) -> str:
    '''Return the violation-relevant content of a source line.

    A line like ``    foo = foo  # rule 1`` has its trailing comment
    stripped so the rule regex can match. A line like
    ``    """foo = foo"""  # example`` has both the docstring
    delimiters AND the trailing comment stripped, exposing the bare
    violation ``foo = foo``. All other lines are returned as the
    leading/trailing whitespace-stripped raw line. This helper is
    used by the two structural rules (tautology, empty_template)
    that should match either a code line, a one-line docstring, or
    a one-line comment.
    '''
    body = line.split('#', 1)[0].rstrip()
    m = re.match(r"^\s*(?:'''|\"\"\")(.*?)(?:'''|\"\"\")\s*$", body, re.DOTALL)
    if m:
        return m.group(1).strip()
    return body.strip()


def check_tautology(path: Path, source: str, source_lines) -> list:
    '''Return a violation for every line that states X = X (or any language variant).

    Matches bare-word tautologies on either side of ``=``, ``即``, ``就是``,
    ``means`` or the English idiom ``X is the same as X``. The variable
    name on each side must look like an identifier (a single token). The
    closing punctuation is restricted to ``:.;)`` (no comma) so a Python
    kwargs call ``render_template("x.html", storage=storage, error=error)``
    whose last argument is shaped ``name=name,`` does NOT match - kwargs
    calls always have a trailing comma. Bare assignment lines like
    ``    foo = foo`` and one-line docstrings like ``"""foo = foo"""``
    both fire. Trailing ``#`` comments and one-line docstring wrappers
    are stripped before matching.
    '''
    out = []
    for idx, line in enumerate(source_lines, start=1):
        body = _violation_body(line)
        if not body:
            continue
        m = _TAUTOLOGY_SENTINEL.match(body)
        if not m:
            continue
        out.append({
            "rule": "tautology",
            "path": str(path),
            "line": idx,
            "text": line.strip(),
            "pattern": 1,
        })
    return out


# ---------------------------------------------------------------------------
# Rule 2 - empty template (X -> Y where both are ALL_CAPS placeholders)
# ---------------------------------------------------------------------------

_EMPTY_TEMPLATE = re.compile(
    r"^\s*"
    r"([A-Z][A-Z0-9_]{1,}|[A-Z_]{2,})"  # left placeholder
    r"\s*(?:->|→|=>|→|⟶)\s*"
    r"([A-Z][A-Z0-9_]{1,}|[A-Z_]{2,})"  # right placeholder
    r"\s*[:.,;)]*$"
)


def check_empty_template(path: Path, source: str, source_lines) -> list:
    '''Return a violation for lines shaped like "PLACEHOLDER -> PLACEHOLDER".

    Both sides must be ALL_CAPS identifiers (at least 2 chars after the
    initial letter, or 2+ underscores). This catches "FOO -> BAR",
    "INPUT -> OUTPUT", "X → Y" but ignores type annotations like
    ``-> int`` because ``int`` is lowercase, and ignores arrows inside
    prose that have lowercase words. Trailing ``#`` comments and a
    one-line docstring wrapper are stripped before matching so
    ``    FOO -> BAR  # note`` and ``    """FOO -> BAR"""`` both fire.
    '''
    out = []
    for idx, line in enumerate(source_lines, start=1):
        body = _violation_body(line)
        if not body:
            continue
        m = _EMPTY_TEMPLATE.match(body)
        if not m:
            continue
        out.append({
            "rule": "empty_template",
            "path": str(path),
            "line": idx,
            "text": line.strip(),
            "pattern": 2,
        })
    return out


# ---------------------------------------------------------------------------
# Rule 3 - word spam (same word 3+ times in one text line)
# ---------------------------------------------------------------------------

def check_word_spam(
    path: Path, source: str, source_lines, text_lines, spans_by_line,
    internal_text_lines,
) -> list:
    '''Return a violation when one word repeats 3+ times in a text line.

    Restricts itself to STRING/COMMENT lines so a function signature with
    the parameter name repeated (``def is_user(user: Optional[User]) -> bool:``)
    is not flagged. For a multi-line STRING token, only the start line
    is checked (its span covers the whole token, so a word appearing
    3+ times anywhere in the docstring fires once on the opening line).
    Internal lines of multi-line STRINGs are skipped via
    ``internal_text_lines`` so a 12-line docstring does not produce
    12 independent reports.

    Words shorter than ``WORD_SPAM_MIN_LEN`` are ignored (avoids the
    ``a``/``is``/``I`` noise). Only the first offender per line is
    reported - this rule is "yes/no per line", not "every word".
    '''
    out = []
    for ln in sorted(text_lines):
        if ln in internal_text_lines:
            continue
        if ln < 1 or ln > len(source_lines):
            continue
        words = _words_in_text_line(ln, source_lines, spans_by_line)
        if not words:
            continue
        counts: dict[str, int] = {}
        for w in words:
            if len(w) < WORD_SPAM_MIN_LEN:
                continue
            counts[w] = counts.get(w, 0) + 1
        offenders = [(w, c) for w, c in counts.items() if c >= WORD_SPAM_MIN_COUNT]
        if not offenders:
            continue
        offenders.sort(key=lambda kv: (-kv[1], kv[0]))
        word, count = offenders[0]
        out.append({
            "rule": "word_spam",
            "path": str(path),
            "line": ln,
            "text": source_lines[ln - 1].rstrip(),
            "word": word,
            "count": count,
            "pattern": 3,
        })
    return out


# ---------------------------------------------------------------------------
# Rule 4 - cliche prefix (重要的是 / 非常 / 实际上 / 应该说)
# ---------------------------------------------------------------------------

_CLICHE_PREFIXES = (
    "重要的是", "非常", "基本上", "实际上", "应该说",
    "一般来说", "具体来说", "总的来说", "毫无疑问", "显而易见",
)


def check_cliche_prefix(
    path: Path, source: str, source_lines, text_lines, spans_by_line,
    internal_text_lines,
) -> list:
    '''Return a violation when a text line opens with a Chinese filler.

    Trigger phrases are short function-word clusters ("重要的是", "非常",
    "实际上"...) that carry no payload by themselves. The check
    looks at the "violation body" of the line: trailing ``#`` comments
    and one-line docstring wrappers are stripped via ``_violation_body``
    so ``    """基本上"""  # example`` exposes the bare ``基本上``
    body. A long descriptive docstring that happens to start with
    "实际上" still passes because its body length exceeds the cap;
    a bare ``"""基本上"""`` (body = 基本上, short) fires. Code lines
    and multi-line STRING internal lines are skipped.
    '''
    out = []
    for ln in sorted(text_lines):
        if ln in internal_text_lines:
            continue
        if ln < 1 or ln > len(source_lines):
            continue
        body = _violation_body(source_lines[ln - 1])
        if not body or len(body) > CLICHE_PREFIX_MAX_CHARS:
            continue
        for prefix in _CLICHE_PREFIXES:
            if body.startswith(prefix):
                out.append({
                    "rule": "cliche_prefix",
                    "path": str(path),
                    "line": ln,
                    "text": source_lines[ln - 1].rstrip(),
                    "prefix": prefix,
                    "pattern": 4,
                })
                break
    return out


# ---------------------------------------------------------------------------
# Rule 5 - formulaic opener (在这里 / 首先 / 其次 / 最后 / 综上所述)
# ---------------------------------------------------------------------------

_FORMULAIC_OPENERS = (
    "在这里", "在这种情况下", "首先", "其次", "再次", "最后",
    "接下来", "然后", "综上所述", "总而言之", "具体而言",
)


def check_formulaic_opener(
    path: Path, source: str, source_lines, text_lines, spans_by_line,
    internal_text_lines,
) -> list:
    '''Return a violation when a text line opens with a structural phrase.

    "首先"/"其次"/"最后"/"在这里"/"综上所述" are pure structure, not
    content. The check looks at the violation body of the line
    (comment + docstring wrapper stripped) so ``    """首先"""  # note``
    exposes the bare ``首先`` body. A long descriptive docstring
    starting with "首先" still passes (body length exceeds the cap).
    Code lines and multi-line STRING internal lines are skipped.
    '''
    out = []
    for ln in sorted(text_lines):
        if ln in internal_text_lines:
            continue
        if ln < 1 or ln > len(source_lines):
            continue
        body = _violation_body(source_lines[ln - 1])
        if not body or len(body) > FORMULAIC_OPENER_MAX_CHARS:
            continue
        for opener in _FORMULAIC_OPENERS:
            if body.startswith(opener):
                out.append({
                    "rule": "formulaic_opener",
                    "path": str(path),
                    "line": ln,
                    "text": source_lines[ln - 1].rstrip(),
                    "opener": opener,
                    "pattern": 5,
                })
                break
    return out


# ---------------------------------------------------------------------------
# Rule 6 - repeated sentence (two adjacent text lines >= 85% similar)
# ---------------------------------------------------------------------------

def _norm_for_compare(text: str) -> str:
    '''Collapse whitespace for the similarity check.

    Multiple spaces, tabs, and leading/trailing whitespace are squashed
    so a re-wrapped paragraph is not flagged as "different" from the
    single-line form.
    '''
    return re.sub(r"\s+", " ", text).strip()


def check_repeated_sentence(
    path: Path, source: str, source_lines, text_lines, spans_by_line,
    internal_text_lines,
) -> list:
    '''Return a violation for two adjacent text lines that look near-duplicate.

    Both lines must be text (STRING/COMMENT) and carry at least
    ``REPEATED_SENTENCE_MIN_CHARS`` characters. Internal lines of a
    multi-line STRING are skipped so a 12-line docstring does not
    generate 11 "this line matches the previous" violations - those
    are paragraphs of the same sentence, not a copy-paste mistake.
    Similarity is computed via ``difflib.SequenceMatcher`` with
    autojunk disabled (short strings need an exact ratio, not a
    sampled one). The first line of a near-duplicate pair is reported.
    '''
    out = []
    prev_ln = None
    prev_text = None
    for ln in sorted(text_lines):
        if ln in internal_text_lines:
            prev_ln = None
            prev_text = None
            continue
        if ln < 1 or ln > len(source_lines):
            prev_ln = None
            prev_text = None
            continue
        words = _words_in_text_line(ln, source_lines, spans_by_line)
        if not words:
            prev_ln = None
            prev_text = None
            continue
        norm = _norm_for_compare(" ".join(words))
        if len(norm) < REPEATED_SENTENCE_MIN_CHARS:
            prev_ln = None
            prev_text = None
            continue
        if prev_text is not None:
            ratio = difflib.SequenceMatcher(
                a=prev_text, b=norm, autojunk=False,
            ).ratio()
            if ratio >= REPEATED_SENTENCE_RATIO:
                out.append({
                    "rule": "repeated_sentence",
                    "path": str(path),
                    "line": prev_ln,
                    "text": source_lines[prev_ln - 1].rstrip(),
                    "match_line": ln,
                    "match_text": source_lines[ln - 1].rstrip(),
                    "ratio": round(ratio, 3),
                    "pattern": 6,
                })
                # The first line of a near-duplicate run is reported once;
                # the second line becomes the new anchor so further
                # duplicates against a third line are still caught.
                prev_ln = ln
                prev_text = norm
                continue
        prev_ln = ln
        prev_text = norm
    return out


# ---------------------------------------------------------------------------
# Rule 7 - filler words (>30% of line is function words)
# ---------------------------------------------------------------------------

_FILLER_WORDS_CN = frozenset({"的", "了", "和", "是", "在", "有", "就", "也", "都", "与"})
_FILLER_WORDS_EN = frozenset({
    "the", "is", "of", "and", "to", "in", "a", "an", "for", "on", "at", "by",
    "as", "or", "be", "this", "that", "it", "with",
})


def check_filler_words(
    path: Path, source: str, source_lines, text_lines, spans_by_line,
    internal_text_lines,
) -> list:
    '''Return a violation when a text line is mostly function words.

    The Chinese and English filler sets are fixed and small. A line is
    flagged when filler count / total word count > ``FILLER_WORD_RATIO``
    AND the line has at least ``FILLER_WORD_MIN_WORDS`` words. Code
    lines are skipped. Internal lines of a multi-line STRING are
    skipped so a long docstring with high filler density is not
    reported on every line - the start line is enough. Mixed CJK /
    English lines are scored across both alphabets.
    '''
    filler = _FILLER_WORDS_CN | _FILLER_WORDS_EN
    out = []
    for ln in sorted(text_lines):
        if ln in internal_text_lines:
            continue
        if ln < 1 or ln > len(source_lines):
            continue
        words = _words_in_text_line(ln, source_lines, spans_by_line)
        if len(words) < FILLER_WORD_MIN_WORDS:
            continue
        hits = sum(1 for w in words if w in filler)
        ratio = hits / len(words)
        if ratio > FILLER_WORD_RATIO:
            out.append({
                "rule": "filler_words",
                "path": str(path),
                "line": ln,
                "text": source_lines[ln - 1].rstrip(),
                "hits": hits,
                "total": len(words),
                "ratio": round(ratio, 3),
                "pattern": 7,
            })
    return out


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def scan(path: Path) -> list:
    '''Run all seven rules against every .py file found under ``path``.'''
    violations = []
    for py in iter_python_files(path):
        source = _read_source(py)
        if not source:
            continue
        source_lines = source.splitlines()
        text_lines, spans_by_line, internal_text_lines = _text_units(source)
        violations.extend(check_tautology(py, source, source_lines))
        violations.extend(check_empty_template(py, source, source_lines))
        violations.extend(
            check_word_spam(
                py, source, source_lines, text_lines, spans_by_line,
                internal_text_lines,
            )
        )
        violations.extend(
            check_cliche_prefix(
                py, source, source_lines, text_lines, spans_by_line,
                internal_text_lines,
            )
        )
        violations.extend(
            check_formulaic_opener(
                py, source, source_lines, text_lines, spans_by_line,
                internal_text_lines,
            )
        )
        violations.extend(
            check_repeated_sentence(
                py, source, source_lines, text_lines, spans_by_line,
                internal_text_lines,
            )
        )
        violations.extend(
            check_filler_words(
                py, source, source_lines, text_lines, spans_by_line,
                internal_text_lines,
            )
        )
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
        if rule == "tautology":
            lines.append(
                f"[FAIL] tautology: {v['path']}:{v['line']} "
                f"line={v['text']!r} pattern={v['pattern']}"
            )
        elif rule == "empty_template":
            lines.append(
                f"[FAIL] empty_template: {v['path']}:{v['line']} "
                f"line={v['text']!r} pattern={v['pattern']}"
            )
        elif rule == "word_spam":
            lines.append(
                f"[FAIL] word_spam: {v['path']}:{v['line']} "
                f"word={v['word']!r} count={v['count']} pattern={v['pattern']}"
            )
        elif rule == "cliche_prefix":
            lines.append(
                f"[FAIL] cliche_prefix: {v['path']}:{v['line']} "
                f"prefix={v['prefix']!r} pattern={v['pattern']}"
            )
        elif rule == "formulaic_opener":
            lines.append(
                f"[FAIL] formulaic_opener: {v['path']}:{v['line']} "
                f"opener={v['opener']!r} pattern={v['pattern']}"
            )
        elif rule == "repeated_sentence":
            lines.append(
                f"[FAIL] repeated_sentence: {v['path']}:{v['line']} "
                f"match_line={v['match_line']} ratio={v['ratio']} pattern={v['pattern']}"
            )
        elif rule == "filler_words":
            lines.append(
                f"[FAIL] filler_words: {v['path']}:{v['line']} "
                f"hits={v['hits']} total={v['total']} ratio={v['ratio']} "
                f"pattern={v['pattern']}"
            )
    files = {v["path"] for v in violations}
    by_rule: dict[str, int] = {}
    for v in violations:
        by_rule[v["rule"]] = by_rule.get(v["rule"], 0) + 1
    lines.append("")
    lines.append(f"TOTAL: {len(violations)} violations in {len(files)} files")
    if by_rule:
        breakdown = ", ".join(
            f"{rule}={n}" for rule, n in sorted(by_rule.items())
        )
        lines.append(f"BY_RULE: {breakdown}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DELETE + BACKUP
# ---------------------------------------------------------------------------

def _apply_delete(violations, backup: bool) -> dict:
    '''Remove flagged lines from each file; return a per-file summary.

    For every file touched by a violation, the original is renamed to
    ``<file>.bak`` (unless ``backup`` is False) and the file is rewritten
    with the offending lines stripped. Returns ``{path: removed_count}``
    so the CLI can show what was done. Lines that appear in two
    violations are stripped only once (deduped by line number).
    '''
    by_file: dict[str, set[int]] = {}
    for v in violations:
        by_file.setdefault(v["path"], set()).add(v["line"])
    removed: dict[str, int] = {}
    for path_str, line_nos in by_file.items():
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            logger.warning("cannot read for delete %s: %s", path, exc)
            continue
        lines = original.splitlines()
        keep = [ln for i, ln in enumerate(lines, start=1) if i not in line_nos]
        removed_count = len(lines) - len(keep)
        if removed_count == 0:
            continue
        if backup:
            backup_path = path.with_suffix(path.suffix + ".bak")
            try:
                backup_path.write_text(original, encoding="utf-8")
            except OSError as exc:
                logger.warning("cannot write backup %s: %s", backup_path, exc)
        try:
            path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("cannot write stripped %s: %s", path, exc)
            continue
        removed[path_str] = removed_count
    return removed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_default_path() -> Path:
    '''Default --path = ``<workspace>/project_board``.

    The tool lives at ``<workspace>/tools/cleanword_check.py`` so
    ``__file__.parent.parent`` resolves to the workspace root.
    '''
    return Path(__file__).resolve().parent.parent / "project_board"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanword_check",
        description=(
            "Scan Python files for 7 verbal-bloat rules: tautology, empty "
            "template, word spam, cliche prefix, formulaic opener, repeated "
            "sentence, and filler words."
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
        "--delete", action="store_true",
        help="Remove offending lines from the target file (requires --backup).",
    )
    parser.add_argument(
        "--backup", action="store_true",
        help="Write the original file to <file>.bak before --delete.",
    )
    return parser


def main(argv=None) -> int:
    '''CLI entry point. Returns the process exit code.'''
    args = _build_parser().parse_args(argv)
    if args.delete and not args.backup:
        print("--delete requires --backup (refusing to destroy source)", file=sys.stderr)
        return 2
    target = args.path if args.path is not None else _resolve_default_path()

    violations = scan(target)

    if args.delete and violations:
        removed = _apply_delete(violations, backup=args.backup)
        summary = ", ".join(
            f"{p}={n}" for p, n in sorted(removed.items())
        )
        print(f"DELETE: removed lines in {len(removed)} files: {summary}")

    if args.quiet:
        print(len(violations))
    elif args.json:
        print(json.dumps(violations, indent=2, ensure_ascii=False))
    else:
        print(_format_human(violations))

    return 1 if (args.strict and violations) else 0


if __name__ == "__main__":
    sys.exit(main())
