from __future__ import annotations

import json
from pathlib import Path

from . import order, runner, safety, t0
from .keywords import q_keywords
from .merge import merge


def discover(root: Path) -> list[Path]:
    return sorted(p.resolve() for p in root.rglob("*.q")
                  if p.is_file() and "graphify-out" not in p.parts and ".venv" not in p.parts)


def _calibrated() -> dict:
    f = Path(__file__).with_name("calibration.json")
    if not f.exists():
        return {}
    c = json.loads(f.read_text())
    return {"edge_t0_known": c["edge_t0_known"]}


def analyse(root: Path, execute: bool = False, scores: dict | None = None) -> dict:
    scores = {**_calibrated(), **(scores or {})}
    root = root.resolve()
    files = discover(root)
    t0d = {f: t0.extract(f) for f in files}
    deps = {f: order.imports_of(f, root, {}) for f in files}
    depmap = {f: [h for _, h, _ in ds if h in t0d] for f, ds in deps.items()}

    scan = {f: safety.scan(f.read_text(errors="replace")) for f in files}
    status: dict[Path, dict] = {}
    closure_unsafe: dict[Path, str] = {}

    def tainted(f: Path, seen=frozenset()) -> str | None:
        if f in seen:
            return None
        if not scan[f]["safe"]:
            return f"{f.name}: {', '.join(scan[f]['reasons'])}"
        for d in depmap.get(f, []):
            r = tainted(d, seen | {f})
            if r:
                return r
        return None

    runnable: list[Path] = []
    for f in files:
        why = tainted(f)
        if not execute:
            status[f] = {"status": "not_run", "why": "execution not enabled"}
        elif why:
            status[f] = {"status": "refused", "why": why}
        else:
            runnable.append(f)

    rt: dict = {"files": [], "defs": []}
    if execute and runnable:
        ordered = order.load_order(runnable, depmap)
        rt = runner.reflect_isolated(root, ordered, depmap)
        done = {Path(fr["file"]).resolve(): fr for fr in rt["files"]}
        for f in runnable:
            fr = done.get(f)
            if fr is None:
                status[f] = {"status": "load_error", "why": rt["errors"].get(str(f), "no reflection returned")[:200]}
            elif not fr["ok"]:
                status[f] = {"status": "load_error", "why": fr["err"][:200]}
            else:
                status[f] = {"status": "loaded"}
    out = merge(root, t0d, rt, status, deps, scores, q_keywords())
    out["status"] = {str(f.relative_to(root)): s for f, s in status.items()}
    out["scan"] = {str(f.relative_to(root)): scan[f] for f in files}
    return out


def baseline(root: Path) -> dict:
    """Stock graphify behaviour: raw output of the q extractor, no verification."""
    root = root.resolve()
    nodes, edges, seen = [], [], set()
    from .extractor_q_stock import extract_q as stock
    for f in discover(root):
        raw = stock(f)
        for n in raw["nodes"]:
            if n["id"] not in seen:
                seen.add(n["id"])
                nodes.append(n)
        edges += raw["edges"]
    return {"nodes": nodes, "edges": edges, "hyperedges": [], "input_tokens": 0, "output_tokens": 0}


def build_graph(extraction: dict, root: Path, outdir: Path) -> dict:
    from graphify.analyze import god_nodes, suggest_questions, surprising_connections
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify.detect import detect
    from graphify.export import to_json
    from graphify.report import generate

    outdir.mkdir(parents=True, exist_ok=True)
    core = {k: extraction[k] for k in ("nodes", "edges", "hyperedges", "input_tokens", "output_tokens")}
    (outdir / "extraction.json").write_text(json.dumps(core, indent=2))
    G = build_from_json(core, directed=True)
    comms = cluster(G)
    coh = score_all(G, comms)
    gods = god_nodes(G)
    surprises = surprising_connections(G, comms)
    labels = {c: f"Community {c}" for c in comms}
    qs = suggest_questions(G, comms, labels)
    det = detect(root)
    report = generate(G, comms, coh, labels, gods, surprises, det,
                      {"input": 0, "output": 0}, str(root), suggested_questions=qs)
    (outdir / "GRAPH_REPORT.md").write_text(report)
    to_json(G, comms, str(outdir / "graph.json"))
    return {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "communities": len(comms)}
