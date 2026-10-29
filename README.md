# better-q-graphify

Per-node and per-edge confidence for q/kdb+ knowledge graphs built with [graphify](https://github.com/safishamsi/graphify).

Stock extraction marks every call edge `INFERRED` and treats q primitives (`string`, `count`, ...) and
parameters as user functions. `qverify` adds a verification layer on top of a tree-sitter-q grammar:

| Tier | Evidence |
|---|---|
| T0 | tree-sitter syntax only |
| T2 | definition observed in a live q |
| T3 | reference resolved by q itself (`value f`); dangling references flagged `AMBIGUOUS` |
| T3c | symbol constant naming a defined object (lower confidence) |

Every node and edge carries `tier`, `confidence_score` and `evidence`. Items that need judgement
(dynamic `value "..."`, dangling references) go to `enrichment_queue` for an LLM pass.

## Use

```bash
cd qverify
uv run qverify build ../corpus --out ../corpus/graphify-out --execute
uv run qverify baseline ../corpus --out ../corpus/graphify-out-baseline   # stock, for comparison
uv run qverify eval ../corpus ../corpus/truth.json
uv run qverify calibrate <root>...        # score tree-sitter edges against q as oracle
uv run pytest
```

## Requirements and safety

- q at `~/.kx/bin/q` (or `Q=`), macOS (`sandbox-exec`), Python 3.14 via uv
- tree-sitter-q wheel vendored in `qverify/vendor/`. The T0 extractor (`extractor_q.py`) lives in this repo:
  scope-aware (params/locals/implicit x,y,z shadow globals), ignores q primitives, emits `reads` edges.
  `extractor_q_stock.py` is a frozen copy of the original, used only by `qverify baseline`.
- `--execute` runs the code being analysed. Each file runs in its own q process under a sandbox that
  denies network, file writes and process execution. File reads are allowed except common credential
  directories. Without `--execute` everything stays at T0.

## Status

The `corpus/` test set is small and in-sample. See `HANDOFF.md` for measured results and open tasks.
