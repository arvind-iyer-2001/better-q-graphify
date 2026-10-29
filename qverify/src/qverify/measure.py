"""Measure tree-sitter edges against q's own resolution for one project root (the oracle)."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path

from . import t0
from .pipeline import analyse, discover


def split_of(name: str) -> str:
    """Deterministic dev/test split by repo name, so tuning on `dev` cannot leak into `test`."""
    return "dev" if hashlib.sha1(name.encode()).digest()[0] % 2 == 0 else "test"


def measure(root: Path, samples: int = 25) -> dict:
    res = analyse(root, execute=True)
    st = Counter(s["status"] for s in res["status"].values())
    ev, qsql = Counter(), 0
    for e in res["edges"]:
        if e["tier"] == "T3c" and any("supported by a name inside" in x for x in e["evidence"]):
            qsql += 1
        if e["tier"] == "T3":
            ev["agree" if "tree-sitter agrees" in e["evidence"] else
               "dangling" if e["confidence"] == "AMBIGUOUS" else
                       "indirect" if "not a lambda literal" in " ".join(e["evidence"]) else "t3_only"] += 1
    ag = ev["agree"] + qsql
    rf = [x for x in res["refuted"] if not x["kw"]]
    lab = {n["id"]: n for n in res["nodes"]}
    missed = [f'{lab[e["source"]]["label"]} -> {lab[e["target"]]["label"]} ({lab[e["source"]]["source_file"]})'
              for e in res["edges"] if e["tier"] == "T3" and "tree-sitter missed it" in e["evidence"]]
    return {"root": root.name, "files": dict(st), "n_files": sum(st.values()),
            "reflected_lambdas": sum(1 for n in res["nodes"] if n["kind"] == "lambda" and n["tier"] == "T2"),
            "agree": ag, "missed": ev["t3_only"], "refuted": len(rf), "refuted_kw": len(res["refuted"]) - len(rf),
            "filtered_unexecuted": len(res["filtered_keywords"]), "dangling": ev["dangling"],
            "refuted_samples": [f'{x["file"]}:{x["line"]} {x["edge"]} [{x["relation"]}]' for x in rf[:samples]],
            "missed_samples": missed[:samples],
            "load_errors": Counter(s.get("why", "")[:80] for s in res["status"].values()
                                   if s["status"] == "load_error").most_common(5)}
