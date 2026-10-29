"""Static pre-scan deciding whether a q file may be executed by the reflector.

Loading a q file runs its top-level statements. The macOS sandbox (see runner.py) denies network,
file writes and process execution, so the scan only refuses what the sandbox cannot contain: a
top-level `exit` / `\\` that would kill the reflector before it reports. Comments are not stripped
(over-matching only costs confidence). Dynamic evaluation is reported, not refused: it is opaque
to analysis, not unsafe.
"""
from __future__ import annotations

import re

_REFUSE = {"top-level exit": re.compile(r"^\s*(exit\b|\\\\\s*$)", re.M)}
_DYNAMIC = re.compile(r'\b(value|eval|reval)\s*[("]')


def scan(text: str) -> dict:
    reasons = sorted(k for k, p in _REFUSE.items() if p.search(text))
    return {"safe": not reasons, "reasons": reasons, "dynamic": bool(_DYNAMIC.search(text))}
