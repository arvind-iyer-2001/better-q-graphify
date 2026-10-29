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

from .ids import make_id as _make_id

SCORES = {
    "def_t2": 0.97, "def_t0": 0.70, "def_t0_unloaded": 0.60, "def_t0_not_in_runtime": 0.30,
    "def_z_handler": 0.75,
    "edge_agree": 0.99, "edge_t3": 0.95, "edge_dangling": 0.35,
    "edge_t0_known": 0.70, "edge_t0_unknown": 0.40,
    "edge_symconst": 0.60, "edge_qsql_support": 0.85, "import_ok": 0.95, "import_missing": 0.35,
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
        conf = label_for(score)
        if tier == "T0" and rel_ in ("calls", "reads", "writes", "uses") and conf == "EXTRACTED":
            conf = "INFERRED"  # never EXTRACTED without runtime verification, whatever the measured precision
        edges[key] = {"source": src, "target": tgt, "relation": rel_,
                      "confidence": conf, "confidence_score": round(score, 2),
                      "tier": tier, "source_file": file, "source_location": f"L{line}",
                      "evidence": evidence}

    # ---- runtime ownership --------------------------------------------------
    owner: dict[str, str] = {}
    redefined: set[tuple[str, str]] = set()
    load_idx: dict[str, int] = {}
    for i, fr in enumerate(rt.get("files", [])):
        load_idx[rel(fr["file"])] = i
        for q in fr["new"] + fr["changed"]:
            owner[q] = rel(fr["file"])
        redefined.update((rel(fr["file"]), q) for q in fr["changed"])
    rt_defs: dict[tuple[str, str], dict] = {}
    for d in rt.get("defs", []):
        rt_defs[(rel(d["file"]) if d.get("file") else owner.get(d["name"], "?"), d["name"])] = d
    file_status = {rel(f): s["status"] for f, s in status.items()}

    # ---- file nodes ---------------------------------------------------------
    fid = {}
    for f in t0:
        r = rel(f)
        fid[r] = _make_id(r)
        add_node(fid[r], Path(r).name, r, 1, "file", "T0", 1.0,
                 [f"file on disk; run status: {file_status.get(r, 'n/a')}"],
                 run_status=file_status.get(r, "n/a"))

    # ---- definitions: one node per (file, qualified name) -------------------
    t0_defs: dict[tuple[str, str], int] = {}
    for f, d in t0.items():
        for q, line in d["defs"].items():
            t0_defs.setdefault((rel(f), q), line)
    keys = sorted(set(t0_defs) | set(rt_defs))
    by_name: dict[str, list[tuple[str, str]]] = {}
    for k in sorted(keys, key=lambda k: load_idx.get(k[0], -1)):
        by_name.setdefault(k[1], []).append(k)
    def_id: dict[tuple[str, str], str] = {}

    def resolve(q: str, from_file: str):
        """The definition a reference to `q` made in `from_file` binds to: same file, else last loaded."""
        c = by_name.get(q)
        if not c:
            return None
        return (from_file, q) if (from_file, q) in def_id else c[-1]

    for k in keys:
        file, q = k
        rd = rt_defs.get(k)
        line = t0_defs.get(k, 1)
        nid = def_id[k] = _make_id(file, q)
        run = file_status.get(file, "n/a")
        dup = len(by_name[q]) > 1
        if rd:
            kind = rd["kind"]
            ev = [f"defined at runtime (q type {rd['t']}, {kind})"]
            ev.append("also found by tree-sitter" if k in t0_defs else "NOT visible to tree-sitter (dynamic definition)")
            if k in redefined:
                ev.append("redefined by a later file")
            if dup:
                ev.append(f"name defined in {len(by_name[q])} files; references bind to the same file, else the last loaded")
            add_node(nid, q, file, line, kind, "T2", S["def_t2"], ev)
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
    t3: dict[tuple[str, str, str], dict] = {}
    for (file, q), rd in rt_defs.items():
        for ref in rd.get("refs", []):
            t3[(file, q, ref["res"])] = ref
    t0_keys: dict[tuple[str, str, str], tuple[str, int]] = {}
    for f, d in t0.items():
        for s_, t_, relation, line in d["edges"]:
            t0_keys.setdefault((rel(f), s_, t_), (relation, line))

    def stub(q, kind, tier, score, ev, file, line):
        nid = _make_id("unresolved" if kind == "unresolved" else "external", q)
        if nid not in nodes:
            add_node(nid, q, file, line, kind, tier, score, ev, dangling=(kind == "unresolved"))
        return nid

    for (file, src, res), ref in t3.items():
        skey = (file, src)
        agree = (file, src, res) in t0_keys
        line = t0_keys[(file, src, res)][1] if agree else int(nodes[def_id[skey]]["source_location"].lstrip("L"))
        tkey = resolve(res, file)
        if tkey is not None:
            kind = nodes[def_id[tkey]]["kind"]
            relation = "calls" if kind in ("lambda", "function") else "uses"
            if agree and t0_keys[(file, src, res)][0] == "writes":
                relation = "writes"  # q only says "references"; the syntax knows it is an assignment
            sc = S["edge_agree"] if agree else S["edge_t3"]
            add_edge(def_id[skey], def_id[tkey], relation, file, line, "T3", sc,
                     ["q resolved this global reference (value f)"] + (["tree-sitter agrees"] if agree else ["tree-sitter missed it"]))
        elif ref["ex"]:
            continue  # resolves to a q builtin (e.g. .z.p); not part of the project graph
        else:
            rd = rt_defs[skey]
            nid = stub(res, "unresolved", "T3", S["edge_dangling"],
                       [f"q resolves '{ref['raw']}' in context {rd['ctx'] or '.'} to {res}, which is undefined"],
                       file, line)
            add_edge(def_id[skey], nid, "calls", file, line, "T3", S["edge_dangling"],
                     ["dangling reference: raises an error at runtime when executed"])
            queue.append({"node": nid, "reason": "dangling reference", "snippet": f"{src} -> {res}"})

    def sym_candidates(rd, sym):
        ctx = rd.get("ctx") or ""
        return ([f".{ctx}.{sym}"] if not sym.startswith(".") and ctx else []) + [sym]

    # ---- edges: symbol constants naming defined objects (passed by name, e.g. `trade) ----
    for (file, q), rd in rt_defs.items():
        for raw_sym in rd.get("symconst", []):
            cand = next((c for c in sym_candidates(rd, raw_sym) if resolve(c, file)), None)
            if cand is not None and (file, q, cand) not in t3 and (file, q, cand) not in t0_keys:
                tkey = resolve(cand, file)
                add_edge(def_id[(file, q)], def_id[tkey], "references", file,
                         int(nodes[def_id[(file, q)]]["source_location"].lstrip("L")), "T3c", S["edge_symconst"],
                         [f"symbol constant `{cand} names a defined {nodes[def_id[tkey]]['kind']}; may be data, not a reference"])

    # ---- edges: T0 not already covered --------------------------------------
    # a def whose right-hand side is not a lambda literal (e.g. `f:$[c;g;h]`) has tree-sitter edges from the
    # *defining expression*, while q reflects the chosen function: the two are not comparable
    t0_lambda = {(rel(f), q) for f, d in t0.items() for q in d.get("lambda_defs", ())}
    reflected = {k for k, d in rt_defs.items() if d["kind"] == "lambda" and (k not in t0_defs or k in t0_lambda)}
    for (file, src, tgt), (relation, line) in t0_keys.items():
        skey = (file, src)
        if (file, src, tgt) in t3 or skey not in def_id:
            continue
        tkey = resolve(tgt, file)
        if skey in rt_defs and tkey is not None and any(
                tgt == c for sy in rt_defs[skey].get("symconst", []) for c in sym_candidates(rt_defs[skey], sy)):
            add_edge(def_id[skey], def_id[tkey], relation, file, line, "T3c", S["edge_qsql_support"],
                     ["tree-sitter edge supported by a name inside a compiled qsql expression "
                      "(value f keeps those in constants, not in the globals list)"])
            continue
        if (tkey is None and skey in rt_defs and tgt.startswith((".Q.", ".q.", ".z.", ".h.", ".j.", ".o."))
                and any(tgt == c for sy in rt_defs[skey].get("symconst", []) for c in sym_candidates(rt_defs[skey], sy))):
            continue  # builtin referenced inside a compiled qsql expression: supported, but not a project node
        tail = tgt.rsplit(".", 1)[-1]
        is_kw = tkey is None and (tail in keywords or tail in ("x", "y", "z") or not tail or not tail[0].isalpha())
        if skey in reflected:
            refuted.append({"edge": f"{src} -> {tgt}", "relation": relation, "file": file, "line": line, "kw": is_kw,
                            "why": "q primitive/local, not a user global" if is_kw else
                                   "q's resolved globals for this function do not include it (local/param/symbol)"})
            continue
        if is_kw:
            filtered.append(f"{src} -> {tgt}")
            continue
        if tkey is not None:
            add_edge(def_id[skey], def_id[tkey], relation, file, line, "T0", S["edge_t0_known"],
                     ["tree-sitter name match to a known definition; caller not executed"])
        else:
            nid = stub(tgt, "external", "T0", S["edge_t0_unknown"],
                       ["referenced name has no definition in this corpus"], file, line)
            add_edge(def_id[skey], nid, relation, file, line, "T0", S["edge_t0_unknown"],
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
