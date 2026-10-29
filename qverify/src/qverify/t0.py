"""Tier T0: syntactic extraction using the tree-sitter-q grammar and the local scope-aware extractor."""
from __future__ import annotations

from pathlib import Path

from .extractor_q import extract_q


def extract(path: Path) -> dict:
    """Return {defs: {qname: line}, edges: [(src_qname, tgt_label, relation, line)], imports: [(stem, line)]}."""
    raw = extract_q(path)
    if raw.get("error"):
        return {"error": raw["error"], "defs": {}, "edges": [], "imports": []}
    label = {n["id"]: n["label"] for n in raw["nodes"]}
    line = lambda loc: int(str(loc or "L1").lstrip("L") or 1)  # noqa: E731
    defs: dict[str, int] = {}
    owner: dict[str, str] = {}
    for e in raw["edges"]:
        if e["relation"] == "contains":
            defs[label[e["target"]]] = line(e.get("source_location"))
            owner[e["target"]] = label[e["target"]]
    edges, imports = [], []
    for e in raw["edges"]:
        if e["relation"] in ("calls", "uses", "reads", "writes") and e["source"] in owner:
            edges.append((owner[e["source"]], label[e["target"]], e["relation"], line(e.get("source_location"))))
        elif e["relation"] == "imports":
            imports.append((label[e["target"]], line(e.get("source_location"))))
    return {"defs": defs, "edges": edges, "imports": imports, "raw": raw}
