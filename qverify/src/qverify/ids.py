"""Case-sensitive node ids. graphify's `_make_id` lowercases, but q is case-sensitive (`l` vs `L`,
`.z.w` vs `.z.W`), so ids built from it would merge distinct names."""
from __future__ import annotations

import hashlib

from graphify.extractors.base import _make_id


def make_id(*parts: str) -> str:
    return f"{_make_id(*parts)}_{hashlib.sha1(chr(0).join(parts).encode()).hexdigest()[:8]}"
