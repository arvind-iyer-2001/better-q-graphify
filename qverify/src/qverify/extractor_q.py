"""Graphify extractor for KDB+/q (bespoke: functions are assignments to lambdas).

Vendored from the q-tree-sitter project's graphify_q/q.py and extended here with scope-aware
reference extraction:

* only `identifier` / `dotted_name` nodes are references. `builtin` nodes (count, string, each, ...)
  are q primitives and never become edges.
* a lambda's parameters, implicit x/y/z and `name:` locals shadow globals (q lambdas are not closures,
  so a nested lambda does not see its parent's locals).
* non-call global references become `reads` edges, assignments to globals (`::`, `+:`, `.ns.x:`, `a[i]:`) `writes` edges,
  and self-recursion is kept (previously only calls/indexing produced edges).
* qsql clauses (`select a, b by c where d`): bare names there are usually table columns. They produce
  an edge only when the name is defined in this file; the `from` table produces a `uses` edge unless it
  is a parameter/local.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

from graphify.extractors.base import _file_stem, _make_id, _read_text

_QSQL = {"select_statement", "exec_statement", "update_statement", "delete_statement"}
_QSQL_CLAUSES = {"select_clause", "by_clause", "where_clause"}
_ADVERB_FUNS = {"each", "peach", "over", "scan", "prior", "sv", "vs"}
_NAMES = {"identifier", "dotted_name"}


def _parser():
    mod = importlib.import_module("tree_sitter_q")
    from tree_sitter import Language, Parser
    return Parser(Language(mod.language()))


def extract_q(path: Path) -> dict:
    """Extract functions, variables, calls, reads, imports, and table uses from a .q file.

    Node fields: id, label, file_type, source_file, source_location
    Edge fields: source, target, relation (calls|reads|writes|uses|contains|imports), confidence, source_file
    """
    try:
        parser = _parser()
    except ImportError:
        return {"nodes": [], "edges": [], "error": "tree_sitter_q not installed"}

    try:
        src = Path(path).read_bytes()
        root = parser.parse(src).root_node
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}

    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()
    seen_edges: set[tuple] = set()
    ns_stack: list[str] = [""]
    label_to_nid: dict[str, str] = {}

    def text(n: Any) -> str:
        return _read_text(n, src)

    def add_node(nid: str, label: str, line: int) -> None:
        if nid not in seen_ids:
            seen_ids.add(nid)
            label_to_nid[label] = nid
            nodes.append({"id": nid, "label": label, "file_type": "code",
                          "source_file": str_path, "source_location": f"L{line}"})

    def add_edge(s: str, t: str, relation: str, line: int, confidence: str = "EXTRACTED") -> None:
        key = (s, t, relation)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"source": s, "target": t, "relation": relation, "confidence": confidence,
                      "source_file": str_path, "source_location": f"L{line}"})

    def ensure_external_node(label: str, line: int) -> str:
        if label in label_to_nid:
            return label_to_nid[label]
        nid = _make_id(label)
        add_node(nid, label, line)
        return nid

    file_nid = _make_id(str(path))
    add_node(file_nid, Path(path).name, 1)

    def qualify(name: str) -> str:
        if name.startswith("."):
            return name
        ns = ns_stack[-1]
        return f"{ns}.{name}" if ns else name

    def apply_ns(node: Any) -> None:
        parts = text(node).strip().split()
        if parts and parts[0] == "\\d":
            new_ns = parts[1] if len(parts) > 1 else "."
            ns_stack[-1] = "" if new_ns == "." else new_ns

    # ---- pre-pass: names defined at file level (used to gate qsql column-vs-global reads) ----
    file_defs: set[str] = set()

    def system_ns(node: Any) -> None:
        m = re.search(r'system\s*"d\s+([^"\s]+)"', text(node))
        if m:
            ns_stack[-1] = "" if m.group(1) == "." else m.group(1)

    def prepass(node: Any) -> None:
        if node.type in ("system_command", "namespace_directive"):
            apply_ns(node)
        elif node.type == "call":
            system_ns(node)
        elif node.type == "assignment":
            left = node.child_by_field_name("left")
            if left is not None and left.type in _NAMES:
                file_defs.add(qualify(text(left)))
            return
        for c in node.children:
            prepass(c)

    prepass(root)
    ns_stack[:] = [""]

    # ---- lambda scope: params, implicit x/y/z, `name:` locals ----
    def lambda_scope(lam: Any) -> set[str]:
        names: set[str] = set()
        params = lam.child_by_field_name("parameters")
        if params is not None:
            names.update(text(p) for p in params.children if p.type == "param")
        else:
            names.update(("x", "y", "z"))

        def scan(n: Any, in_clause: bool) -> None:
            for c in n.children:
                if c.type == "lambda":
                    continue
                if c.type == "assignment" and not in_clause:
                    left, op = c.child_by_field_name("left"), c.child_by_field_name("operator")
                    if left is not None and left.type == "identifier" and op is not None and text(op) == ":":
                        names.add(text(left))
                scan(c, in_clause or c.type in _QSQL_CLAUSES)

        scan(lam, False)
        return names

    def refs_in(node: Any, owner: str, scope: set[str], in_qsql: bool = False) -> None:
        """Emit calls/reads/uses edges for global references under `node`."""
        t = node.type
        line = node.start_point[0] + 1

        def ref(name_node: Any, relation: str, qsql_gated: bool = False) -> None:
            m_ = re.match(r"[.A-Za-z_][\w.]*", text(name_node))
            raw = m_.group(0) if m_ else text(name_node)  # the grammar can glue `:value` onto a dotted name
            if name_node.type == "identifier" and ("." in raw or raw in scope):
                return  # local/param, or a.b field access (not a global name)
            tgt = qualify(raw)
            if tgt == ".z.s" or tgt.startswith(".z.m."):
                return  # `.z.s` is the running lambda; `.z.m` is the per-module namespace, unresolvable statically
            if qsql_gated and tgt not in file_defs:
                return  # probably a table column
            add_edge(owner, ensure_external_node(tgt, line), relation, line, "INFERRED")

        if t == "lambda":
            inner = lambda_scope(node)
            for c in node.children:
                if c.type != "parameters":
                    refs_in(c, owner, inner, False)
            return
        if t in _NAMES:
            ref(node, "reads", qsql_gated=in_qsql)
            return
        if t == "assignment":
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            op = node.child_by_field_name("operator")
            optext = text(op) if op is not None else ":"
            if left is not None:
                if left.type in _NAMES:
                    # `x:v` in a lambda is a local (see lambda_scope); `.ns.x:v`, `x::v`, `x+:v`, `x,:v` write a global
                    if left.type == "dotted_name" or optext != ":":
                        ref(left, "writes")
                else:
                    head = left.child_by_field_name("function") if left.type in ("index", "call") else None
                    if head is not None and head.type in _NAMES:
                        ref(head, "writes")  # a[i]:v amends the global a (ref() skips locals)
                    for c in left.children:
                        if head is None or c.id != head.id:
                            refs_in(c, owner, scope, in_qsql)
            if right is not None:
                refs_in(right, owner, scope, in_qsql)
            return
        if t in ("call", "index"):
            fn = node.child_by_field_name("function")
            if fn is not None:
                if fn.type in _NAMES:
                    ref(fn, "calls")
                elif fn.type == "adverb_apply":
                    inner_fn = fn.child_by_field_name("function")
                    if inner_fn is not None and inner_fn.type in _NAMES:
                        ref(inner_fn, "calls")
                    elif inner_fn is not None:
                        refs_in(inner_fn, owner, scope, in_qsql)
                else:
                    refs_in(fn, owner, scope, in_qsql)
            for c in node.children:
                if fn is None or c.id != fn.id:
                    refs_in(c, owner, scope, in_qsql)
            return
        if t == "adverb_apply":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type in _NAMES:
                ref(fn, "calls")
                return
        if t == "binary":
            op, left = node.child_by_field_name("operator"), node.child_by_field_name("left")
            if (left is not None and left.type in _NAMES and op is not None
                    and op.type == "builtin" and text(op) in _ADVERB_FUNS):
                ref(left, "calls")
                for c in node.children:
                    if c.id != left.id:
                        refs_in(c, owner, scope, in_qsql)
                return
        if t in _QSQL:
            for c in node.children:
                if c.type == "from_clause":
                    for tc in c.children:
                        if tc.type in _NAMES:
                            ref(tc, "uses")
                        elif tc.type != "from":
                            refs_in(tc, owner, scope, in_qsql)
                else:
                    refs_in(c, owner, scope, True)
            return
        for c in node.children:
            refs_in(c, owner, scope, in_qsql)

    def handle_assignment(node: Any) -> None:
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None:
            return
        name = qualify(text(left))
        line = node.start_point[0] + 1
        nid = _make_id(str(path), name)
        add_node(nid, name, line)
        add_edge(file_nid, nid, "contains", line)
        refs_in(right, nid, set())  # a lambda opens its own scope inside refs_in

    def handle_system_command(node: Any) -> None:
        t = text(node).strip()
        line = node.start_point[0] + 1
        if t.startswith("\\d"):
            apply_ns(node)
        elif t.startswith("\\l"):
            rest = t[2:].strip()
            if rest:
                stem = Path(rest).stem
                nid = _make_id(stem)
                add_node(nid, stem, line)
                add_edge(file_nid, nid, "imports", line)

    def handle_system_call(node: Any) -> None:
        system_ns(node)
        m = re.search(r'system\s*"l\s+([^"]+)"', text(node))
        if m:
            stem = Path(m.group(1).strip()).stem
            nid = _make_id(stem)
            add_node(nid, stem, node.start_point[0] + 1)
            add_edge(file_nid, nid, "imports", node.start_point[0] + 1)

    def walk(node: Any) -> None:
        if node.type == "assignment":
            handle_assignment(node)
            return
        if node.type in ("system_command", "namespace_directive"):
            handle_system_command(node)
        elif node.type == "call":
            handle_system_call(node)
        for c in node.children:
            walk(c)

    walk(root)
    return {"nodes": nodes, "edges": [e for e in edges if e["source"] in seen_ids and e["target"] in seen_ids]}
