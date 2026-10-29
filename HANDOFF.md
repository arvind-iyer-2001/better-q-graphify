# Handoff — qverify (2026-10-29)

## State
`qverify/` adds a q-verified confidence layer on top of the existing tree-sitter-q grammar
(`~/development/q-tree-sitter`, not modified). Pipeline: tree-sitter extraction (T0) -> sandboxed live q
reflection (`value f`, T2 defs / T3 resolved references) -> merge with per-node/edge `tier`,
`confidence_score`, `evidence` -> graphify build/cluster/report. 7 tests pass (`uv run pytest`).

## Done
- `reflect.q`: loads files in dependency order, dumps defs, params, resolved globals, symbol constants as JSON
- Sandbox (macOS `sandbox-exec`): network, file writes, process exec denied; one q process per file
- Keyword filter from q's own `.Q.res` + `key .q` (T0 edge precision vs q: 17-22% -> 49-59% on 90 real files)
- `corpus/` (6 files, deliberate traps) + hand-written `truth.json`: stock P=0.63 / verified P=R=1.0 (in-sample)
- Graph in `corpus/graphify-out/` (verified) and `corpus/graphify-out-baseline/` (stock)

## Open tasks
| # | Task | Priority |
|---|------|----------|
| 1 | Local/param scoping in the T0 extractor (remaining ~50% of T0 false positives vs q) | high |
| 2 | Variable-read edges: extractor only emits call/index, misses global reads (T0 recall 52-81%) | high |
| 3 | Real-corpus load errors are environmental (.so modules, data files, `.utl.require`); stub or preload | med |
| 4 | Calibrate SCORES empirically per tier instead of policy constants | med |
| 5 | Feed `enrichment_queue` to graphify LLM step; mark results INFERRED below T3 | med |
| 6 | Reflect `.z.*` handlers (excluded as builtin namespace) | low |

## Constraints
- Execution of user code is opt-in (`--execute`); without it everything is T0 only
- Python via uv only; no commit trailers; q at `~/.kx/bin/q`
- Truth set is hand-written and in-sample; real-corpus numbers use q as oracle, not hand labels

## Commands
- build: `uv run qverify build <root> --out <dir> --execute`
- stock comparison: `uv run qverify baseline <root> --out <dir>`
- score: `uv run qverify eval ../corpus ../corpus/truth.json`
- oracle calibration: `uv run qverify calibrate <root>...`
