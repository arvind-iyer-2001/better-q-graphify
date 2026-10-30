#!/usr/bin/env bash
# Build the tree-sitter-q wheel for THIS machine (platform + python) into qverify/vendor.
# Usage: scripts/build_grammar_wheel.sh /path/to/q-tree-sitter [out_dir]
# Needs a C compiler. The grammar repo is only read: it is copied to a temp dir and built there.
set -euo pipefail
src="${1:?usage: build_grammar_wheel.sh /path/to/q-tree-sitter [out_dir]}"
out="${2:-$(cd "$(dirname "$0")/.." && pwd)/qverify/vendor}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/g" "$out"
for item in pyproject.toml src bindings; do cp -R "$src/$item" "$tmp/g/"; done
(cd "$tmp/g" && uv build --wheel --out-dir "$out")
ls -1 "$out"/tree_sitter_q-*.whl
