"""q's own reserved words + .q namespace functions, taken from the installed q (not hand-listed)."""
from __future__ import annotations

import subprocess

from .runner import q_binary


def q_keywords() -> frozenset[str]:
    p = subprocess.run([q_binary(), "-q"], input='-1 " " sv string distinct .Q.res,key `.q;\nexit 0\n',
                       capture_output=True, text=True, timeout=20)
    return frozenset(p.stdout.split())
