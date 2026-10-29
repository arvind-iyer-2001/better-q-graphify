"""Score an extraction against a hand-written truth file (precision / recall / dangling detection)."""
from __future__ import annotations


def _stem(label: str) -> str:
    return label[:-2] if label.endswith(".q") else label


def edge_sets(ext: dict, min_score: float = 0.0) -> tuple[dict, set]:
    label = {n["id"]: n["label"] for n in ext["nodes"]}
    calls: dict[tuple[str, str], dict] = {}
    imports: set[tuple[str, str]] = set()
    for e in ext["edges"]:
        if e.get("confidence_score", 1.0 if e["confidence"] == "EXTRACTED" else 0.7) < min_score:
            continue
        s, t = label[e["source"]], label[e["target"]]
        if e["relation"] in ("calls", "uses"):
            if not t.startswith(".z.") or t == ".z.ts":
                calls[(s, t)] = e
        elif e["relation"] == "imports":
            imports.add((_stem(s), _stem(t)))
    return calls, imports


def prf(pred: set, truth: set) -> dict:
    tp = len(pred & truth)
    p = tp / len(pred) if pred else 1.0
    r = tp / len(truth) if truth else 1.0
    return {"tp": tp, "fp": len(pred - truth), "fn": len(truth - pred),
            "precision": round(p, 3), "recall": round(r, 3)}


def score(ext: dict, truth: dict, min_score: float = 0.0) -> dict:
    calls, imports = edge_sets(ext, min_score)
    t_calls = {(a, b) for a, b, _ in truth["calls"]}
    dangling = {(a, b) for a, b, ok in truth["calls"] if not ok}
    flagged = {k for k, e in calls.items() if e["confidence"] == "AMBIGUOUS"}
    return {
        "calls+uses": prf(set(calls), t_calls),
        "false_positives": sorted(set(calls) - t_calls),
        "missed": sorted(t_calls - set(calls)),
        "imports": prf(imports, {tuple(x) for x in truth["imports"]}),
        "dangling_flagged": f"{len(flagged & dangling)}/{len(dangling)}",
        "wrongly_flagged": sorted(flagged - dangling),
    }
