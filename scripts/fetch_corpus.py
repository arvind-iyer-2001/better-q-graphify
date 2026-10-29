#!/usr/bin/env python3
"""Discover public q/kdb+ repositories on GitHub and shallow-clone them into corpora/ (gitignored).

Third-party code is never committed: corpora/MANIFEST.json (repo, license, pinned commit, q file count) is.
Cloned code is untrusted data: it is only read, and executed (if at all) by `qverify --execute` inside the
sandbox. Usage: python3 scripts/fetch_corpus.py [--max-mb 150] [--min-q-files 2] [--jobs 6]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPORA = ROOT / "corpora"
SEARCHES = [
    ["--language=q", "--sort=stars"],
    ["--topic=kdb", "--sort=stars"],
    ["--topic=kdb-plus", "--sort=stars"],
    ["--topic=kdbplus", "--sort=stars"],
    ["--topic=q-language", "--sort=stars"],
    ["--topic=kx", "--sort=stars"],
    ["kdb+", "--language=q", "--sort=updated"],
    ["kdb", "--language=q", "--sort=updated"],
    ["tickerplant", "--sort=stars"],
    ["kdb+ q", "--sort=stars"],
]
FIELDS = "fullName,stargazersCount,size,license,isFork,isArchived,pushedAt"


def gh(*args: str) -> list[dict]:
    p = subprocess.run(["gh", "search", "repos", *args, "--limit", "100", "--json", FIELDS],
                       capture_output=True, text=True, timeout=120)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else []


def clone(repo: dict) -> dict:
    name = repo["fullName"].replace("/", "__")
    dest = CORPORA / name
    if not dest.exists():
        p = subprocess.run(["git", "clone", "--depth", "1", "--quiet", "--no-tags",
                            f"https://github.com/{repo['fullName']}.git", str(dest)],
                           capture_output=True, text=True, timeout=300,
                           env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/opt/homebrew/bin"})
        if p.returncode:
            return {**repo, "error": p.stderr.strip()[-200:]}
    sha = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    qn = sum(1 for _ in dest.rglob("*.q"))
    return {**repo, "dir": name, "sha": sha, "q_files": qn}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mb", type=int, default=150)
    ap.add_argument("--min-q-files", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    CORPORA.mkdir(exist_ok=True)
    seen: dict[str, dict] = {}
    for s in SEARCHES:
        for r in gh(*s):
            seen.setdefault(r["fullName"], r)
    cand = [r for r in seen.values() if not r["isFork"] and r["size"] <= a.max_mb * 1024]
    print(f"{len(seen)} found, {len(cand)} after dropping forks / >{a.max_mb}MB", file=sys.stderr)
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(clone, cand))
    keep, drop = [], []
    for r in res:
        (keep if r.get("q_files", 0) >= a.min_q_files else drop).append(r)
    for r in drop:  # not q projects (GitHub's "q" language label is noisy): remove the clone
        if r.get("dir"):
            subprocess.run(["rm", "-rf", str(CORPORA / r["dir"])])
    manifest = [{"repo": r["fullName"], "dir": r["dir"], "sha": r["sha"], "q_files": r["q_files"],
                 "stars": r["stargazersCount"], "license": (r["license"] or {}).get("key"), "pushed": r["pushedAt"]}
                for r in sorted(keep, key=lambda r: -r["q_files"])]
    (CORPORA / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    print(f"kept {len(keep)} repos / {sum(r['q_files'] for r in keep)} q files; dropped {len(drop)} non-q; "
          f"{sum(1 for r in res if 'error' in r)} clone errors", file=sys.stderr)


if __name__ == "__main__":
    main()
