"""Content check: is this .q file really q/kdb+ code? (GitHub's `q` language label also covers query logs,
word lists, and fuzz data that merely carry the extension.)"""
from __future__ import annotations

import re
from pathlib import Path

_SIGNALS = [re.compile(p, re.M) for p in (
    r"^\s*\.?[A-Za-z_][\w.]*\s*:+\s*\{",                      # name:{lambda}
    r"^\\(d|l|p|c|C|t|T|e|g|w|x|v|f|a|b|B|s|S|u)\b",           # system commands
    r"\b(select|exec|update|delete)\b[^\n]{0,200}\bfrom\b",     # qsql
    r"\.(z|Q|q|h|j|o)\.[A-Za-z]",                               # q builtin namespaces
    r"\bsystem\s*\"",                                           # system "cmd"
    r"^\s*\.?[A-Za-z_][\w.]*\s*:+\s*\(\s*\[",                   # name:([] table)
    r"`:[\w/.]+|`\w+\$|\d+#|\bhopen\b|\binsert\b|\bupsert\b",  # common q idioms
)]
_HEAD = 200_000


def looks_like_q(path: Path) -> bool:
    try:
        raw = path.read_bytes()[:_HEAD]
    except OSError:
        return False
    if b"\0" in raw:
        return False
    text = raw.decode("utf-8", errors="replace")
    # prose / log / fuzz data: almost no q structure per KB
    hits = sum(1 for p in _SIGNALS if p.search(text))
    return hits >= 2 or (hits == 1 and len(text) < 4000)
