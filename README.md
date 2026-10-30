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

## Calibration

`uv run qverify calibrate <roots> --write src/qverify/calibration.json` measures tree-sitter edge precision
against q on files that load, and `build` uses it as the score for unexecuted T0 edges. Those edges are
capped at `INFERRED` regardless of the measured value (the files that fail to load are likely harder).

## Status

The `corpus/` test set is small and in-sample. See `HANDOFF.md` for measured results and open tasks.

## Running on a Linux server (multi-repo workspace)

Point `qverify` at the workspace directory that contains the repos. Files are discovered recursively, node ids are
path-based (unique across repos), and `\l` loads resolve against the workspace root, the file's directory, or the
file's own repo root (nearest `.git`).

```bash
# 1. grammar wheel for this machine (needs gcc; reads your q-tree-sitter checkout, never writes to it)
scripts/build_grammar_wheel.sh /path/to/q-tree-sitter
cd qverify && uv sync

# 2. first run: structure only, executes nothing
uv run qverify build /path/to/workspace --out /path/to/workspace-graph

# 3. verified run: q loads each file inside a locked-down container
export Q=$QHOME/l64/q          # your q binary; the licence is read from $QHOME (or $QLIC)
export QV_IMAGE=debian:stable-slim   # any glibc image already on the server
uv run qverify build /path/to/workspace --out /path/to/workspace-graph --execute
```

Sandbox backend (`QV_SANDBOX=sandbox-exec|docker`; default: macOS `sandbox-exec`, otherwise Docker). Per file, q runs in
`docker run --network none --read-only --cap-drop ALL --no-new-privileges --pids-limit 256 --memory 2g`, with the workspace,
`reflect.q` and the q install mounted read-only and one writable temp bind for the JSON result. A hung file is killed by
name after the timeout. Not isolated: anything the image itself allows (the container can spawn processes, but cannot
reach the network or write outside its temp bind). Files that need a network (`hopen`), data or a library missing in the
container fail to load and stay `T0`/`INFERRED`; that is the intended safe default.
