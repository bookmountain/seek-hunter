"""Word-level comparison helpers shared by the validator and the Changes panel.

A rewrite is *trivial* when it only changes spelling variants (optimizing/optimising, color/colour),
punctuation, whitespace, case or hyphenation. Such edits carry no tailoring signal, so the validator
reverts them and the Changes panel shows the bullet as kept.
"""

import difflib
import re

_PUNCT = re.compile(r"[^\w]+")
VARIANT_MAX_DISTANCE = 2
VARIANT_MIN_PREFIX = 4


def _tokens(text: str) -> list[str]:
    out = []
    for word in text.lower().replace("-", " ").split():
        word = _PUNCT.sub("", word)
        if word:
            out.append(word)
    return out


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_spelling_variant(a: str, b: str) -> bool:
    prefix = len(a) >= VARIANT_MIN_PREFIX and a[:VARIANT_MIN_PREFIX] == b[:VARIANT_MIN_PREFIX]
    return prefix and _distance(a, b) <= VARIANT_MAX_DISTANCE


def is_trivial_change(before: str, after: str) -> bool:
    a, b = _tokens(before), _tokens(after)
    if "".join(a) == "".join(b):
        return True
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        old, new = a[i1:i2], b[j1:j2]
        if "".join(old) == "".join(new):
            continue
        if op != "replace" or len(old) != len(new):
            return False
        if not all(is_spelling_variant(x, y) for x, y in zip(old, new, strict=True)):
            return False
    return True


def word_diff(before: str, after: str) -> list[dict]:
    """[{"op": "equal"|"delete"|"insert", "text": "..."}] over whitespace-split words (punctuation stays
    attached). A replacement becomes a delete followed by an insert."""
    a, b = before.split(), after.split()
    ops: list[dict] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            ops.append({"op": "equal", "text": " ".join(a[i1:i2])})
            continue
        if i2 > i1:
            ops.append({"op": "delete", "text": " ".join(a[i1:i2])})
        if j2 > j1:
            ops.append({"op": "insert", "text": " ".join(b[j1:j2])})
    return ops
