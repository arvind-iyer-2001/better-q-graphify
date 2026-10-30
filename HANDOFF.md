# Handoff — qverify (2026-10-30)

## State
`qverify/` adds a q-verified confidence layer over the user's tree-sitter-q grammar (`~/development/q-tree-sitter`, never modified). Pipeline: tree-sitter (T0) -> sandboxed live q reflection (T2 defs / T3 refs) -> merge with per-node/edge `tier`, `confidence_score`, `evidence` -> graphify.  Repo: `/Users/arvindiyer/kdb-rea` = `arvind-iyer-2001/better-q-graphify` (private). All work pushed; HEAD `6e39286`. 30 tests pass.

## Measured (dev split only; see `docs/RESULTS.md`)
Corpus: 240 repos / 5,284 real q files (content-filtered by `qdetect.py`), in gitignored `corpora/`; `corpora/MANIFEST.json` committed. Split dev/test by sha1 of repo name.
- dev1 (105 repos): P 98.4% / R 95.9%
- dev2 (105 repos, case-sensitive ids, builtin-in-qsql): refuted 91, missed 341, **P 98.9% / R 96.0%**
- `test` split NOT yet run. Run once at the end, report as the honest number, never tune on it.
- Result files in `corpora/results/` (gitignored). dev0 = old code + junk repos, ignore.

## Done since dev2
- `extractor_q._top_nodes`: grammar ERROR (e.g. `2000.01.01D0^x`, a user-grammar gap, read-only) used to swallow hundreds of following lines (TorQ gateway.q: everything after line 160). Files with any parse error (12% of corpora files) are now re-parsed per top-level statement via `included_ranges`. Static gain across corpora: +467 nodes / +774 edges (<1%). Not yet measured through q: dev3 will include it, so TorQ misses should drop.
- Report grammar gap to user: `D0^` timestamp-with-fraction followed by `^` fails to parse.

## Server deployment (added after test split)
Test split (run once): P 99.6% / R 89.0% (puzzle_solutions = 1,696 of 2,204 misses; 97.1% without it). See RESULTS.md.
Docker sandbox backend (`runner.docker_command`, `QV_SANDBOX`), wheelhouse via `find-links = ["vendor"]`, `scripts/build_grammar_wheel.sh`,
repo-root load resolution; README "Running on a Linux server". NOT verified on Linux: no Linux q or running Docker daemon here, only command
construction is unit-tested. First server run: T0-only build, then `--execute` on one repo, then the workspace.

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
