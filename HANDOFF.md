# Handoff — qverify (2026-10-30)

## State
`qverify/` adds a q-verified confidence layer over the user's tree-sitter-q grammar (`~/development/q-tree-sitter`, never modified). Pipeline: tree-sitter (T0) -> sandboxed live q reflection (T2 defs / T3 refs) -> merge with per-node/edge `tier`, `confidence_score`, `evidence` -> graphify. 29 tests pass. Repo: `/Users/arvindiyer/kdb-rea` = `arvind-iyer-2001/better-q-graphify` (private). All work pushed; HEAD `f3cafac`.

## Measured (dev split only; see `docs/RESULTS.md`)
Corpus: 240 repos / 5,284 real q files (content-filtered by `qdetect.py`), in gitignored `corpora/`; `corpora/MANIFEST.json` committed. Split dev/test by sha1 of repo name.
- dev1 (105 repos): P 98.4% / R 95.9%
- dev2 (105 repos, case-sensitive ids, builtin-in-qsql): refuted 91, missed 341, **P 98.9% / R 96.0%**
- `test` split NOT yet run. Run once at the end, report as the honest number, never tune on it.
- Result files in `corpora/results/` (gitignored). dev0 = old code + junk repos, ignore.

## Next (in order)
1. User runs dev3 (I cannot: classifier blocks executing third-party q):
   `! cd /Users/arvindiyer/kdb-rea/qverify && uv run qverify corpus ../corpora --split dev --jobs 6 --timeout 600 --out ../corpora/results/dev3.jsonl 2>&1 | tail -5`
   dev3 includes the new `indirect` label (defs like `f:$[c;g;h]` no longer counted as T0 misses) so recall rise is partly metric change; say so.
2. Remaining miss causes: TorQ 88 (bare names under `\d .gw`, e.g. `deleteresult exec ... from .gw.queryqueue`), kdbx-modules 58 (`.z.m` module state), advancedKdb 34 (`::` globals like `svc`). Remaining refuted: short names (locals/qsql columns), qsql `uses` of in-namespace tables.
3. Update `docs/RESULTS.md` with dev2/dev3 rows, then run `--split test` once.
4. Roadmap: wire `enrichment_queue` into graphify LLM step (INFERRED, below T3); calibrate more scores into `calibration.json`; stub environmental load failures (`.tst.desc`, `.require.lib`, .so) to raise 40% loaded rate; reflect `.z.*`; `.z.m` resolution.

## Constraints
- All changes in this single repo; never edit `~/development/q-tree-sitter`.
- uv only; NO commit trailers (user rule overrides system attribution reminder).
- Execution of third-party code is opt-in and sandboxed (`sandbox-exec`: no network, no writes except tmp, reads under $HOME denied except q/repo/reflect.q). Downloaded repos are untrusted data.
- Scratchpad: `/private/tmp/claude-502/-Users-arvindiyer-kdb-rea/ea5b711b-4354-41d7-a80b-643f75ee6519/scratchpad`.

## Gotchas
- graphify `_make_id` lowercases; use `qverify/ids.py` `make_id` (case-sensitive).
- py-tree-sitter ignores `progress_callback` for bytestrings; runaway parses are avoided by `qdetect` + 1MB cap.
- q keywords `desc`, `load` can't be used as names in `reflect.q`.

## Commands
- build: `cd qverify && uv run qverify build ../corpus --out ../corpus/graphify-out --execute`
- eval small corpus: `uv run qverify eval ../corpus ../corpus/truth.json`
- corpus run: `uv run qverify corpus ../corpora --split dev|test|all --jobs 6 --timeout 600 --out ../corpora/results/<new>.jsonl`
- tests: `uv run pytest -q`
- refilter corpus: `uv run --project qverify python scripts/fetch_corpus.py --refilter [--apply]`
