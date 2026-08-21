"""Regression fixtures for cleanword_check - one example per rule.

Every violation lives inside a single-line docstring so the file is
valid Python the tool can ast-parse. Each numbered section targets
exactly one rule. Do NOT add legitimate prose to the docstring lines;
otherwise the rule-3/4/5/6/7 detectors will trigger on the wrong
section.
"""

# -----------------------------------------------------------------------
# Rule 1 - tautology (X = X / X 即 X / X means X)
# -----------------------------------------------------------------------

# section header for rule 1


def tautology_eq():
    """foo = foo"""  # rule 1 eq: left and right are the same identifier
    return 1


def tautology_chinese():
    """Y = Y"""  # rule 1: works for single-char Chinese identifier too
    return 1


def tautology_means():
    """Z = Z"""  # rule 1: tautology in the simplest form
    return 1


# -----------------------------------------------------------------------
# Rule 2 - empty template (PLACEHOLDER -> PLACEHOLDER)
# -----------------------------------------------------------------------

# section header for rule 2


def empty_template_arrow():
    """FOO -> BAR"""  # rule 2: both sides are ALL_CAPS placeholders
    return 1


def empty_template_unicode():
    """INPUT -> OUTPUT"""  # rule 2 with longer placeholders
    return 1


# -----------------------------------------------------------------------
# Rule 3 - word spam (same word 3+ times in one text line)
# -----------------------------------------------------------------------

# section header for rule 3


def word_spam_en():
    """the the the the the the the the the the dog runs."""  # rule 3
    return 1


def word_spam_cn():
    """的的的的的的的的的的的的的的的的的的的的的。"""  # rule 3 cn
    return 1


# -----------------------------------------------------------------------
# Rule 4 - cliche prefix (重要的是 / 非常 / 实际上)
# -----------------------------------------------------------------------

# section header for rule 4


def cliche_prefix_zhongyao():
    """重要的是"""  # rule 4: 重要的是 is a filler phrase
    return 1


def cliche_prefix_jiben():
    """基本上"""  # rule 4: 基本上
    return 1


def cliche_prefix_shiji():
    """实际上"""  # rule 4: 实际上
    return 1


# -----------------------------------------------------------------------
# Rule 5 - formulaic opener (首先 / 其次 / 最后 / 综上所述)
# -----------------------------------------------------------------------

# section header for rule 5


def formulaic_opener_shouxian():
    """首先"""  # rule 5: 首先 is structural
    return 1


def formulaic_opener_zuihou():
    """最后"""  # rule 5: 最后
    return 1


def formulaic_opener_zongshang():
    """综上所述"""  # rule 5: 综上所述
    return 1


# -----------------------------------------------------------------------
# Rule 6 - repeated sentence (two adjacent text lines >= 85% similar)
# -----------------------------------------------------------------------

# section header for rule 6


def repeated_sentence_pair():
    """the quick brown fox jumps over the lazy dog in autumn evening"""
    """the quick brown fox jumps over the lazy dog in autumn evening"""  # rule 6
    return 1


# -----------------------------------------------------------------------
# Rule 7 - filler (>50% of line is function, min 8 tokens)
# -----------------------------------------------------------------------

# section header for rule 7


def filler_words_en():
    """the is a of and to in the is a of and to in."""  # rule 7
    return 1


def filler_words_cn():
    """的了和是在的了和是在的了和是在的了和是在。"""  # rule 7 cn
    return 1
