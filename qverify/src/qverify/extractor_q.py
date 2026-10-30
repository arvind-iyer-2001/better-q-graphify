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

import bisect
import importlib
import re
import sys
from pathlib import Path
from typing import Any

from graphify.extractors.base import _file_stem, _read_text

from .ids import make_id as _make_id

_QSQL = {"select_statement", "exec_statement", "update_statement", "delete_statement"}
_QSQL_CLAUSES = {"select_clause", "by_clause", "where_clause"}
_ADVERB_FUNS = {"each", "peach", "over", "scan", "prior", "sv", "vs"}
_NAMES = {"identifier", "dotted_name"}


def _parser():
    mod = importlib.import_module("tree_sitter_q")
    from tree_sitter import Language, Parser
    return Parser(Language(mod.language()))


def _statements(src: bytes, start: int, end: int) -> list[tuple[int, int]]:
    """Split src[start:end] into q top-level statements the way q's loader does: a line that starts in
    column 0 begins a new statement, indented lines continue it. `/` .. `\\` block comments stay whole."""
    spans: list[tuple[int, int]] = []
    cur = None
    in_block = False
    pos = start
    while pos < end:
        nl = src.find(b"\n", pos, end)
        nl = end if nl < 0 else nl + 1
        line = src[pos:nl]
        body = line.rstrip(b"\r\n")
        if in_block:
            in_block = body != b"\\"
            new = False
        elif body == b"/":
            in_block, new = True, True
        else:
            new = bool(body) and body[:1] not in (b" ", b"\t")
        if new or cur is None:
            if cur is not None:
                spans.append((cur, pos))
            cur = pos
        pos = nl
    if cur is not None:
        spans.append((cur, end))
    return spans


def _top_nodes(parser: Any, src: bytes, root: Any) -> list[Any]:
    """Top-level nodes of the file. One literal the grammar cannot read derails everything after it
    (ERROR plus loose tokens up to hundreds of lines), so a file with any parse error is re-parsed
    statement by statement and only the statements that really fail are lost."""
    if not root.has_error:
        return list(root.children)
    from tree_sitter import Point, Range

    starts = [0] + [m.end() for m in re.finditer(rb"\n", src)]  # byte offset of each line start

    def point(b: int) -> Point:
        row = bisect.bisect_right(starts, b) - 1
        return Point(row, b - starts[row])

    out: list[Any] = []
    try:
        for a, b in _statements(src, 0, len(src)):
            parser.included_ranges = [Range(point(a), point(b), a, b)]
            out.extend(parser.parse(src).root_node.children)
    finally:
        parser.included_ranges = []
    return out


def extract_q(path: Path) -> dict:
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
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
        tree = parser.parse(src)
        root = tree.root_node
        tops = _top_nodes(parser, src, root)
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

    for top in tops:
        prepass(top)
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
            if name_node.type == "identifier" and raw in scope:
                return  # local / parameter
            if name_node.type == "identifier" and re.search(rb"\d[nNwW]?$", src[max(0, name_node.start_byte - 3):name_node.start_byte]):
                return  # typed null/infinity suffix (0nf, 0wu, 0Nj): the grammar emits the suffix as an identifier
            tgt = qualify(raw)
            if tgt == ".z.s" or tgt.startswith((".z.m.", ".z.M.")):
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
            if left is not None and in_qsql:
                pass  # `update c:..` / `c+:..` inside qsql define columns, not globals
            elif left is not None:
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
        # `a:b:{..}` defines both names; the value is the innermost right-hand side
        targets, cur = [], node
        while cur is not None and cur.type == "assignment":
            left = cur.child_by_field_name("left")
            if left is None or left.type not in _NAMES:
                return
            targets.append((left, cur))
            cur = cur.child_by_field_name("right")
        if not targets or cur is None:
            return
        for left, a in targets:
            m = re.match(r"[.A-Za-z_][\w.]*", text(left))
            name = qualify(m.group(0) if m else text(left))
            line = a.start_point[0] + 1
            nid = _make_id(str(path), name)
            add_node(nid, name, line)
            for n in reversed(nodes):
                if n["id"] == nid:
                    n["rhs_kind"] = "lambda" if cur.type == "lambda" else "expr"
                    break
            add_edge(file_nid, nid, "contains", line)
            refs_in(cur, nid, set())  # a lambda opens its own scope inside refs_in

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

    for top in tops:
        walk(top)
    return {"nodes": nodes, "edges": [e for e in edges if e["source"] in seen_ids and e["target"] in seen_ids]}
