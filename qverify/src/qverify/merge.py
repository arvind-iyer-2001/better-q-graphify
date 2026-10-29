"""Merge T0 (syntax) with runtime reflection into a tiered, scored graphify extraction.

Tiers (strongest evidence wins; every node/edge carries tier, confidence_score, evidence):
  T0  tree-sitter only                       - structure, no semantics
  T2  definition observed in a live q        - name exists, real type/arity
  T3  reference resolved by q (value f)      - call/use edge q itself will follow
Scores are policy constants (SCORES); `calibrate` replaces the T0 ones empirically.
"""
from __future__ import annotations

import re
from pathlib import Path

from graphify.extractors.base import _make_id

SCORES = {
    "def_t2": 0.97, "def_t0": 0.70, "def_t0_unloaded": 0.60, "def_t0_not_in_runtime": 0.30,
    "def_z_handler": 0.75,
    "edge_agree": 0.99, "edge_t3": 0.95, "edge_dangling": 0.35,
    "edge_t0_known": 0.70, "edge_t0_unknown": 0.40,
    "edge_symconst": 0.60, "import_ok": 0.95, "import_missing": 0.35,
}
_DYNAMIC = re.compile(r'\b(value|eval|reval)\b|\bparse\b')


def label_for(score: float) -> str:
    return "EXTRACTED" if score >= 0.9 else "INFERRED" if score >= 0.5 else "AMBIGUOUS"


def merge(root: Path, t0: dict[Path, dict], rt: dict, status: dict[Path, dict],
          deps: dict[Path, list[tuple[str, Path | None, int]]], scores: dict | None = None,
          keywords: frozenset = frozenset()) -> dict:
    S = {**SCORES, **(scores or {})}
    rel = lambda p: str(Path(p).resolve().relative_to(root.resolve()))  # noqa: E731
    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}
    refuted: list[dict] = []
    filtered: list[str] = []
    queue: list[dict] = []

    def add_node(nid, label, file, line, kind, tier, score, evidence, **extra):
        nodes[nid] = {"id": nid, "label": label, "file_type": "code", "source_file": file,
                      "source_location": f"L{line}", "kind": kind, "tier": tier,
                      "confidence_score": round(score, 2), "evidence": evidence, **extra}

    def add_edge(src, tgt, rel_, file, line, tier, score, evidence):
        key = (src, tgt, rel_)
        if key in edges and edges[key]["confidence_score"] >= score:
            return
        edges[key] = {"source": src, "target": tgt, "relation": rel_,
                      "confidence": label_for(score), "confidence_score": round(score, 2),
                      "tier": tier, "source_file": file, "source_location": f"L{line}",
                      "evidence": evidence}

    # ---- runtime ownership --------------------------------------------------
    owner: dict[str, str] = {}
    redefined: set[str] = set()
    for fr in rt.get("files", []):
        for q in fr["new"] + fr["changed"]:
            owner[q] = rel(fr["file"])
        redefined.update(fr["changed"])
    rt_defs = {d["name"]: d for d in rt.get("defs", [])}
    file_status = {rel(f): s["status"] for f, s in status.items()}

    # ---- file nodes ---------------------------------------------------------
    fid = {}
    for f in t0:
        r = rel(f)
        fid[r] = _make_id(r)
        add_node(fid[r], Path(r).name, r, 1, "file", "T0", 1.0,
                 [f"file on disk; run status: {file_status.get(r, 'n/a')}"],
                 run_status=file_status.get(r, "n/a"))

    # ---- definitions --------------------------------------------------------
    t0_defs: dict[str, tuple[str, int]] = {}
    for f, d in t0.items():
        for q, line in d["defs"].items():
            t0_defs.setdefault(q, (rel(f), line))
    qnames = set(t0_defs) | set(rt_defs)
    def_id: dict[str, str] = {}
    for q in sorted(qnames):
        rd = rt_defs.get(q)
        file, line = t0_defs.get(q, (owner.get(q, "?"), 1))
        nid = def_id[q] = _make_id(file, q)
        run = file_status.get(file, "n/a")
        extra = {}
        if rd:
            kind = rd["kind"]
            ev = [f"defined at runtime (q type {rd['t']}, {kind})"]
            if q in t0_defs:
                ev.append("also found by tree-sitter")
            else:
                ev.append("NOT visible to tree-sitter (dynamic definition)")
            if q in redefined:
                ev.append("redefined by a later file")
            add_node(nid, q, file, line, kind, "T2", S["def_t2"], ev, **extra)
            if kind == "lambda":
                nodes[nid]["params"] = rd["params"]
                nodes[nid]["globals_ctx"] = rd["ctx"]
                if _DYNAMIC.search(re.sub(r'"[^"]*"', '""', rd["src"])) or _DYNAMIC.search(rd["src"]):
                    nodes[nid]["dynamic"] = True
                    queue.append({"node": nid, "reason": "dynamic evaluation (value/eval/parse): callees invisible statically",
                                  "snippet": rd["src"][:300]})
        elif q.startswith(".z."):
            add_node(nid, q, file, line, "lambda", "T0", S["def_z_handler"],
                     ["system handler; runtime reflection does not cover .z namespace"])
        elif run == "loaded":
            add_node(nid, q, file, line, "unknown", "T0", S["def_t0_not_in_runtime"],
                     ["file loaded cleanly but q has no such name: conditional, unreachable or after an error"])
            queue.append({"node": nid, "reason": "tree-sitter definition absent at runtime", "snippet": q})
        else:
            add_node(nid, q, file, line, "unknown", "T0", S["def_t0_unloaded"],
                     [f"syntax only; file not executed ({run})"])
        if file in fid:
            add_edge(fid[file], nid, "contains", file, line, nodes[nid]["tier"], nodes[nid]["confidence_score"],
                     ["definition site"])

    # ---- edges: T3 from reflection ------------------------------------------
    t3: dict[tuple[str, str], dict] = {}
    for q, rd in rt_defs.items():
        for ref in rd.get("refs", []):
            t3[(q, ref["res"])] = ref
    t0_keys: dict[tuple[str, str], tuple[str, str, int]] = {}
    for f, d in t0.items():
        for s, t, relation, line in d["edges"]:
            t0_keys.setdefault((s, t), (rel(f), relation, line))

    def stub(q, kind, tier, score, ev, file, line):
        nid = _make_id("unresolved" if kind == "unresolved" else "external", q)
        if nid not in nodes:
            add_node(nid, q, file, line, kind, tier, score, ev, dangling=(kind == "unresolved"))
        return nid

    for (src, tgt), ref in t3.items():
        sfile = nodes[def_id[src]]["source_file"]
        agree = (src, tgt) in t0_keys
        line = t0_keys[(src, tgt)][2] if agree else nodes[def_id[src]]["source_location"].lstrip("L")
        line = int(line)
        if tgt in def_id:
            kind = nodes[def_id[tgt]]["kind"]
            relation = "calls" if kind in ("lambda", "function") else "uses"
            sc = S["edge_agree"] if agree else S["edge_t3"]
            add_edge(def_id[src], def_id[tgt], relation, sfile, line, "T3", sc,
                     ["q resolved this global reference (value f)"] + (["tree-sitter agrees"] if agree else ["tree-sitter missed it"]))
        elif ref["ex"]:
            continue  # resolves to a q builtin (e.g. .z.p); not part of the project graph
        else:
            nid = stub(tgt, "unresolved", "T3", S["edge_dangling"],
                       [f"q resolves '{ref['raw']}' in context {rt_defs[src]['ctx'] or '.'} to {tgt}, which is undefined"],
                       sfile, line)
            add_edge(def_id[src], nid, "calls", sfile, line, "T3", S["edge_dangling"],
                     ["dangling reference: raises an error at runtime when executed"])
            queue.append({"node": nid, "reason": "dangling reference", "snippet": f"{src} -> {tgt}"})

    # ---- edges: symbol constants naming defined objects (passed by name, e.g. `trade) ----
    for q, rd in rt_defs.items():
        for sym in rd.get("symconst", []):
            if sym in def_id and sym != q and (q, sym) not in t3:
                add_edge(def_id[q], def_id[sym], "references", nodes[def_id[q]]["source_file"],
                         int(nodes[def_id[q]]["source_location"].lstrip("L")), "T3c", S["edge_symconst"],
                         [f"symbol constant `{sym} names a defined {nodes[def_id[sym]]['kind']}; may be data, not a reference"])

    # ---- edges: T0 not already covered --------------------------------------
    reflected = {q for q, d in rt_defs.items() if d["kind"] == "lambda"}
    for (src, tgt), (file, relation, line) in t0_keys.items():
        if (src, tgt) in t3 or src not in def_id:
            continue
        tail = tgt.rsplit(".", 1)[-1]
        is_kw = tgt not in def_id and (tail in keywords or tail in ("x", "y", "z") or not tail or not tail[0].isalpha())
        if src in reflected:
            refuted.append({"edge": f"{src} -> {tgt}", "relation": relation, "file": file, "line": line, "kw": is_kw,
                            "why": "q primitive/local, not a user global" if is_kw else
                                   "q's resolved globals for this function do not include it (local/param/symbol)"})
            continue
        if is_kw:
            filtered.append(f"{src} -> {tgt}")
            continue
        if tgt in def_id:
            add_edge(def_id[src], def_id[tgt], relation, file, line, "T0", S["edge_t0_known"],
                     ["tree-sitter name match to a known definition; caller not executed"])
        else:
            nid = stub(tgt, "external", "T0", S["edge_t0_unknown"],
                       ["referenced name has no definition in this corpus"], file, line)
            add_edge(def_id[src], nid, relation, file, line, "T0", S["edge_t0_unknown"],
                     ["tree-sitter only; target undefined in corpus"])

    # ---- imports ------------------------------------------------------------
    for f, ds in deps.items():
        r = rel(f)
        for raw, hit, line in ds:
            if hit is not None and rel(hit) in fid:
                add_edge(fid[r], fid[rel(hit)], "imports", r, line, "T0", S["import_ok"],
                         [f"\\l {raw} resolved on disk"])
            else:
                nid = stub(raw, "unresolved", "T0", S["import_missing"], [f"\\l {raw} not found on disk"], r, line)
                add_edge(fid[r], nid, "imports", r, line, "T0", S["import_missing"], ["load target missing"])

    for f, s in status.items():
        if s["status"] != "loaded":
            queue.append({"node": fid[rel(f)], "reason": f"file not executed: {s['status']} {s.get('why', '')}".strip(),
                          "snippet": rel(f)})

    return {"nodes": list(nodes.values()), "edges": list(edges.values()),
            "hyperedges": [], "input_tokens": 0, "output_tokens": 0,
            "refuted": refuted, "filtered_keywords": filtered, "enrichment_queue": queue}
