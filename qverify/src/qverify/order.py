"""Resolve `\\l` / system"l" imports to files on disk and topologically order them."""
from __future__ import annotations

import re
from pathlib import Path

_IMPORT = re.compile(r'^\s*\\l\s+(\S+)|system\s*"l\s+([^"\s]+)', re.M)


def imports_of(path: Path, root: Path, known: dict[str, Path]) -> list[tuple[str, Path | None, int]]:
    """Return (raw, resolved|None, line) for every load directive in `path`."""
    text = path.read_text(errors="replace")
    out = []
    for m in _IMPORT.finditer(text):
        raw = (m.group(1) or m.group(2)).strip().strip('"')
        line = text.count("\n", 0, m.start()) + 1
        try:
            cand = [root / raw, path.parent / raw]
            hit = next((c.resolve() for c in cand if c.is_file()), None)
            if hit is None:  # q allows omitting the extension
                hit = next((c.with_suffix(".q").resolve() for c in cand if c.with_suffix(".q").is_file()), None)
        except (ValueError, OSError):
            hit = None  # unparseable load target, e.g. `\l //`
        out.append((raw, hit, line))
    return out


def load_order(files: list[Path], deps: dict[Path, list[Path]]) -> list[Path]:
    seen: set[Path] = set()
    order: list[Path] = []

    def visit(f: Path, stack: tuple[Path, ...] = ()) -> None:
        if f in seen or f in stack:
            return
        for d in deps.get(f, []):
            visit(d, stack + (f,))
        seen.add(f)
        order.append(f)

    for f in sorted(files):
        visit(f)
    return order
