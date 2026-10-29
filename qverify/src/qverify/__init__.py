from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .pipeline import analyse, baseline, build_graph


def main() -> None:
    ap = argparse.ArgumentParser(prog="qverify", description="Tiered, q-verified graph extraction for q/kdb+")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="verified extraction -> graphify graph")
    b.add_argument("root", type=Path)
    b.add_argument("--out", type=Path, default=Path("graphify-out"))
    b.add_argument("--execute", action="store_true",
                   help="load files into a sandboxed live q (runs the code). Without it: tier T0 only.")
    s = sub.add_parser("baseline", help="stock graphify q extraction, for comparison")
    s.add_argument("root", type=Path)
    s.add_argument("--out", type=Path, default=Path("graphify-out-baseline"))
    e = sub.add_parser("eval", help="score verified vs baseline against a truth file")
    e.add_argument("root", type=Path)
    e.add_argument("truth", type=Path)
    c = sub.add_parser("calibrate", help="score tree-sitter edges against q's own resolution (no hand truth)")
    c.add_argument("roots", type=Path, nargs="+")
    c.add_argument("--write", type=Path, help="write pooled measured precision to this calibration.json")
    m = sub.add_parser("measure", help="(internal) measure one root, print JSON")
    m.add_argument("root", type=Path)
    k = sub.add_parser("corpus", help="measure every repo in a corpora dir (parallel, per-repo timeout)")
    k.add_argument("corpora", type=Path)
    k.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    k.add_argument("--jobs", type=int, default=4)
    k.add_argument("--timeout", type=int, default=900)
    k.add_argument("--out", type=Path, required=True, help="jsonl results file (resumable)")
    a = ap.parse_args()

    if a.cmd == "measure":
        from .measure import measure
        print(json.dumps(measure(a.root)))
        return
    if a.cmd == "corpus":
        from .corpus import run_corpus
        run_corpus(a.corpora, a.split, a.jobs, a.timeout, a.out)
        return

    if a.cmd == "calibrate":
        pooled_ag = pooled_rf = 0
        for r in a.roots:
            res = analyse(r, execute=True)
            st = Counter(s["status"] for s in res["status"].values())
            ev = Counter()
            for e in res["edges"]:
                if e["tier"] == "T3c" and any("supported by a name inside" in x for x in e["evidence"]):
                    ev["agree"] += 1
                if e["tier"] == "T3":
                    ev["agree" if "tree-sitter agrees" in e["evidence"] else
                       "dangling" if e["confidence"] == "AMBIGUOUS" else
                       "indirect" if "not a lambda literal" in " ".join(e["evidence"]) else "t3_only"] += 1
            nref = sum(1 for n in res["nodes"] if n["kind"] == "lambda" and n["tier"] == "T2")
            ag, ms = ev["agree"], ev["t3_only"]
            rf_all = len(res["refuted"])
            from collections import defaultdict
            from . import t0 as _t0
            from .pipeline import discover
            owners = defaultdict(set)
            for f in discover(r):
                for q in _t0.extract(f)["defs"]:
                    owners[q].add(f)
            uniq_rf = sum(1 for x in res["refuted"] if not x["kw"] and len(owners[x["edge"].split(" -> ")[0]]) <= 1)
            rf = sum(1 for x in res["refuted"] if not x["kw"])  # after keyword filter
            print(json.dumps({"root": r.name, "files": dict(st), "reflected_lambdas": nref,
                              "edges_agree": ag, "edges_t0_missed": ms, "edges_t0_refuted_before_filter": rf_all, "edges_t0_refuted_after_filter": rf,
                              "filtered_unexecuted": len(res["filtered_keywords"]),
                              "dangling": ev["dangling"],
                              "T0_precision_before": round(ag / (ag + rf_all), 3) if ag + rf_all else None,
                              "T0_precision_after": round(ag / (ag + rf), 3) if ag + rf else None,
                              "T0_precision_unique_names": round(ag / (ag + uniq_rf), 3) if ag + uniq_rf else None,
                              "T0_recall_vs_q": round(ag / (ag + ms), 3) if ag + ms else None}))
            pooled_ag += ag
            pooled_rf += uniq_rf
        if a.write and pooled_ag + pooled_rf:
            prec = round(pooled_ag / (pooled_ag + pooled_rf), 2)
            a.write.write_text(json.dumps({
                "edge_t0_known": prec, "n_edges": pooled_ag + pooled_rf,
                "sources": [r.name for r in a.roots],
                "note": "pooled precision of tree-sitter edges vs q on files that loaded; "
                        "excludes callers whose name is defined in several scripts. Files that fail to load "
                        "are likely harder, so this is an upper bound for them."}, indent=2))
            print(f"wrote {a.write}: edge_t0_known={prec} (n={pooled_ag + pooled_rf})")
        return

    if a.cmd == "eval":
        from .score import score
        truth = json.loads(a.truth.read_text())
        base = baseline(a.root)
        ver = analyse(a.root, execute=True)
        t0only = analyse(a.root, execute=False)
        out = {"baseline (stock graphify q extractor)": score(base, truth),
               "qverify T0 only (no execution)": score(t0only, truth),
               "qverify verified, all edges": score(ver, truth),
               "qverify verified, score>=0.9": score(ver, truth, 0.9)}
        print(json.dumps(out, indent=1))
        return

    if a.cmd == "baseline":
        print(json.dumps(build_graph(baseline(a.root), a.root.resolve(), a.out)))
        return
    res = analyse(a.root, execute=a.execute)
    stats = build_graph(res, a.root.resolve(), a.out)
    (a.out / "verification.json").write_text(json.dumps(
        {"status": res["status"], "scan": res["scan"], "refuted_edges": res["refuted"],
         "enrichment_queue": res["enrichment_queue"]}, indent=2))
    tiers = Counter(n["tier"] for n in res["nodes"])
    etiers = Counter((e["tier"], e["confidence"]) for e in res["edges"])
    print(json.dumps({"graph": stats, "node_tiers": tiers, "edge_tiers": {f"{k[0]}/{k[1]}": v for k, v in etiers.items()},
                      "refuted_edges": len(res["refuted"]), "enrichment_items": len(res["enrichment_queue"])}, indent=1))
