# Handoff — qverify (2026-10-29, updated after extractor work)

## State
`qverify/` adds a q-verified confidence layer on top of the existing tree-sitter-q grammar
(`~/development/q-tree-sitter`, not modified). Pipeline: tree-sitter extraction (T0) -> sandboxed live q
reflection (`value f`, T2 defs / T3 resolved references) -> merge with per-node/edge `tier`,
`confidence_score`, `evidence` -> graphify build/cluster/report. 17 tests pass (`uv run pytest`).

## Done (extractor, this repo only)
- `extractor_q.py`: vendored + rewritten. Scope analysis (params, implicit x/y/z, `name:` locals; no closures),
  only identifier/dotted_name nodes are refs (builtins ignored), `reads` edges for non-call global refs,
  qsql columns gated to names defined in-file, `.z.s` ignored. 10 unit tests in `tests/test_extractor.py`.
- Raw T0 edge accuracy vs q on 90 real files (before -> after): precision 17-22% -> 63-97%,
  recall 52-81% -> 91-97%. Excluding name collisions from loading unrelated scripts into one q
  (39/57 of kdb's refutations): precision 85-100%.
- `extractor_q_stock.py` is a frozen copy of the original, used by `qverify baseline`.

## Done (earlier)
- `reflect.q`: loads files in dependency order, dumps defs, params, resolved globals, symbol constants as JSON
- Sandbox (macOS `sandbox-exec`): network, file writes, process exec denied; one q process per file
- Keyword filter from q's own `.Q.res` + `key .q` (T0 edge precision vs q: 17-22% -> 49-59% on 90 real files)
- `corpus/` (6 files, deliberate traps) + hand-written `truth.json`: stock P=0.63 / verified P=R=1.0 (in-sample)
- Graph in `corpus/graphify-out/` (verified) and `corpus/graphify-out-baseline/` (stock)

## Open tasks
| # | Task | Priority |
|---|------|----------|
| 1 | Isolate name collisions in calibration (load each script in a fresh namespace) so precision is not understated | med |
| 2 | Remaining T0 misses (~10): table-literal and control-flow edge cases | med |
| 3 | Real-corpus load errors are environmental (.so modules, data files, `.utl.require`); stub or preload | med |
| 4 | Calibrate SCORES empirically per tier instead of policy constants | med |
| 5 | Feed `enrichment_queue` to graphify LLM step; mark results INFERRED below T3 | med |
| 6 | Reflect `.z.*` handlers (excluded as builtin namespace) | low |

## Constraints
- Execution of user code is opt-in (`--execute`); without it everything is T0 only
- Everything lives in this repo; nothing is edited in ~/development/q-tree-sitter
- Python via uv only; no commit trailers; q at `~/.kx/bin/q`
- Truth set is hand-written and in-sample; real-corpus numbers use q as oracle, not hand labels

## Commands
- build: `uv run qverify build <root> --out <dir> --execute`
- stock comparison: `uv run qverify baseline <root> --out <dir>`
- score: `uv run qverify eval ../corpus ../corpus/truth.json`
- oracle calibration: `uv run qverify calibrate <root>...`
