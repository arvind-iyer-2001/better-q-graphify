# FROZEN COPY of the unmodified q-tree-sitter extractor. Used only by `qverify baseline` for comparison. Do not edit.
"""Graphify extractor for KDB+/q (bespoke: functions are assignments to lambdas)."""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

from graphify.extractors.base import _file_stem, _make_id, _read_text


def _parser():
    mod = importlib.import_module("tree_sitter_q")
    from tree_sitter import Language, Parser
    return Parser(Language(mod.language()))


def extract_q(path: Path) -> dict:
    """Extract functions, variables, calls, imports, and table uses from a .q file.

    Returns a dict matching the Graphify extraction schema:
        {"nodes": [...], "edges": [...]}

    Node fields: id, label, file_type, source_file, source_location
    Edge fields: source, target, relation, confidence, source_file
    """
    try:
        parser = _parser()
    except ImportError:
        return {"nodes": [], "edges": [], "error": "tree_sitter_q not installed"}

    try:
        src = Path(path).read_bytes()
        tree = parser.parse(src)
        root = tree.root_node
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}

    str_path = str(path)
    stem = _file_stem(Path(path))

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()
    ns_stack: list[str] = [""]  # namespace stack from \d directives
    # Maps qualified label -> node id for fast callee resolution
    label_to_nid: dict[str, str] = {}

    def add_node(nid: str, label: str, line: int) -> None:
        if nid not in seen_ids:
            seen_ids.add(nid)
            label_to_nid[label] = nid
            nodes.append({
                "id": nid,
                "label": label,
                "file_type": "code",
                "source_file": str_path,
                "source_location": f"L{line}",
            })

    def add_edge(src_id: str, tgt_id: str, relation: str, line: int,
                 confidence: str = "EXTRACTED") -> None:
        edges.append({
            "source": src_id,
            "target": tgt_id,
            "relation": relation,
            "confidence": confidence,
            "source_file": str_path,
            "source_location": f"L{line}",
        })

    def ensure_external_node(label: str, line: int) -> str:
        """Return (possibly creating) a stub node for a cross-file symbol."""
        if label in label_to_nid:
            return label_to_nid[label]
        nid = _make_id(label)
        if nid not in seen_ids:
            seen_ids.add(nid)
            label_to_nid[label] = nid
            nodes.append({
                "id": nid,
                "label": label,
                "file_type": "code",
                "source_file": str_path,
                "source_location": f"L{line}",
            })
        return nid

    # File-level node
    file_nid = _make_id(str(path))
    add_node(file_nid, Path(path).name, 1)

    def current_ns() -> str:
        return ns_stack[-1]

    def qualify(name: str) -> str:
        """Resolve a bare name against the current namespace, or pass through dotted names."""
        if name.startswith("."):
            return name
        ns = current_ns()
        return f"{ns}.{name}" if ns else name

    def walk_calls(node: Any, caller_nid: str) -> None:
        """Recursively find call/index nodes within a subtree and emit calls edges."""
        if node.type in ("call", "index"):
            fn = node.child_by_field_name("function")
            if fn is not None:
                callee_text = _read_text(fn, src)
                callee_qualified = qualify(callee_text)
                line = node.start_point[0] + 1
                # Resolve to a real node id (stub node created for cross-file callees)
                callee_nid = ensure_external_node(callee_qualified, line)
                add_edge(caller_nid, callee_nid, "calls", line, "INFERRED")
        for child in node.children:
            walk_calls(child, caller_nid)

    def scan_qsql(node: Any, owner_nid: str) -> None:
        """Find q-SQL statements and emit uses edges for referenced tables."""
        if node.type in ("select_statement", "exec_statement",
                         "update_statement", "delete_statement"):
            frm = node.child_by_field_name("from")
            if frm is not None:
                table_text = _read_text(frm, src).split()[-1]
                table_qualified = qualify(table_text)
                line = node.start_point[0] + 1
                table_nid = ensure_external_node(table_qualified, line)
                add_edge(owner_nid, table_nid, "uses", line, "INFERRED")
        for child in node.children:
            scan_qsql(child, owner_nid)

    def handle_assignment(node: Any) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:
            return
        raw_name = _read_text(left, src)
        name = qualify(raw_name)
        line = node.start_point[0] + 1
        nid = _make_id(str(path), name)

        if right.type == "lambda":
            add_node(nid, name, line)
            add_edge(file_nid, nid, "contains", line)
            # Walk the whole lambda, not child_by_field_name("body"): a multi-
            # statement body (`{a:1; select from t}`) tags every statement with
            # the `body` field, and child_by_field_name returns only the first,
            # which would miss calls/qsql in later statements.
            walk_calls(right, nid)
            scan_qsql(right, nid)
        else:
            add_node(nid, name, line)
            add_edge(file_nid, nid, "contains", line)
            scan_qsql(right, nid)

    def handle_system_command(node: Any) -> None:
        """Handle \\d (namespace) and \\l (load) system commands."""
        text = _read_text(node, src).strip()
        line = node.start_point[0] + 1

        if text.startswith("\\d"):
            parts = text.split()
            new_ns = parts[1] if len(parts) > 1 else "."
            ns_stack[-1] = "" if new_ns == "." else new_ns
        elif text.startswith("\\l"):
            rest = text[2:].strip()
            if rest:
                tgt_stem = Path(rest).stem
                tgt_nid = _make_id(tgt_stem)
                add_node(tgt_nid, tgt_stem, line)
                add_edge(file_nid, tgt_nid, "imports", line)

    def handle_system_call(node: Any) -> None:
        """Handle system"l file.q" calls (load via system function call)."""
        t = _read_text(node, src)
        m = re.search(r'system\s*"l\s+([^"]+)"', t)
        if m:
            tgt_stem = Path(m.group(1).strip()).stem
            tgt_nid = _make_id(tgt_stem)
            add_node(tgt_nid, tgt_stem, node.start_point[0] + 1)
            add_edge(file_nid, tgt_nid, "imports", node.start_point[0] + 1)

    def walk(node: Any) -> None:
        if node.type == "assignment":
            handle_assignment(node)
            # Don't recurse into assignment children — handle_assignment already
            # recurses into lambda body via walk_calls/scan_qsql.
            return
        elif node.type in ("system_command", "namespace_directive"):
            handle_system_command(node)
        elif node.type == "call":
            # Check if this is a top-level system"l ..." call (import)
            handle_system_call(node)
        for child in node.children:
            walk(child)

    walk(root)

    # All edge endpoints are known node ids (stub nodes created for cross-file
    # callees and table references), so a simple both-endpoints check suffices.
    clean_edges = [
        e for e in edges
        if e["source"] in seen_ids and e["target"] in seen_ids
    ]

    return {"nodes": nodes, "edges": clean_edges}
