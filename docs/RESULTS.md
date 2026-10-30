# Measured results

How accurate are the tree-sitter (T0) edges, judged against q's own resolution (`value f`) on real public code?
Oracle = a live q (sandboxed). Only files that load can be judged; everything else stays at tier T0.

Corpus: public GitHub repos found by `scripts/fetch_corpus.py`, filtered by content (`qdetect.py`) to real q code
(240 repos / 5,284 q files). Repos are split deterministically by name hash into `dev` (tuned on) and `test`
(untouched until the end). Numbers below are `dev`.

| Run | Code | Repos | Confirmed | Refuted | Missed | Precision | Recall |
|---|---|---|---|---|---|---|---|
| original 3 KX projects (90 files), stock extractor | stock | 3 | - | - | - | 17-22% | 52-81% |
| same, after scoping/reads/writes work | v1 | 3 | 305 | ~10 | ~1 | 93-100% | 99-100% |
| dev0 (118 repos, incl. non-q repos) | v2 | 112 | 7,691 | 712 | 514 | 91.5% | 93.7% |
| **dev1** (clean corpus) | v3 | 105 | 8,214 | 131 | 350 | **98.4%** | **95.9%** |
| dev2 (case-sensitive ids, builtin refs in qsql) | v4 | 105 | 8,239 | 91 | 341 | 98.9% | 96.0% |
| **dev3** (`indirect` relabel, ERROR-region re-parse) | v5 | 105 | 8,342 | 91 | 108 | **98.9%** | **98.7%** |

dev3 recall jump is mostly a metric change: defs whose rhs is not a lambda literal (e.g. resq `.utl.require:$[..]`) are no longer counted as tree-sitter misses (~100 edges); the ERROR-region re-parse accounts for the TorQ drop (88 -> 4).

dev1 per repo (47 repos with >= 20 edges): median precision 100%, 10th percentile 87%, worst 76%.
Files: 2,638 total; 40% load fully into q, 54% hit a load error (framework/library bootstraps, `.so` modules,
missing data), 6% refused. Files that do not load are not judged and stay `T0`/`INFERRED`.

Known limits: edges inside `.z.m` (module namespace) are skipped; typed-null suffixes like `0nf` are a
grammar gap worked around in the extractor; recall is measured only on functions q could reflect.
