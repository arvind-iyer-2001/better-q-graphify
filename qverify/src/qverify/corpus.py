"""Run `qverify measure` over every repo in a corpora directory, resumably, one subprocess per repo."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .measure import split_of


def run_corpus(corpora: Path, split: str, jobs: int, timeout: int, out: Path) -> None:
    manifest = json.loads((corpora / "MANIFEST.json").read_text())
    repos = [m for m in manifest if split in ("all", split_of(m["dir"]))]
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {json.loads(l)["root"] for l in out.read_text().splitlines() if l.strip()}
    todo = [m for m in repos if m["dir"] not in done]
    print(f"{len(repos)} repos in split '{split}', {len(todo)} to do", file=sys.stderr)

    def one(m: dict) -> dict:
        try:
            p = subprocess.run([sys.executable, "-m", "qverify", "measure", str(corpora / m["dir"])],
                               capture_output=True, text=True, timeout=timeout)
            line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
            r = json.loads(line) if line.startswith("{") else {"root": m["dir"], "error": p.stderr[-300:]}
        except subprocess.TimeoutExpired:
            r = {"root": m["dir"], "error": f"timeout {timeout}s"}
        r["split"] = split_of(m["dir"])
        r["q_files"] = m["q_files"]
        return r

    with ThreadPoolExecutor(jobs) as ex, out.open("a") as fh:
        for i, r in enumerate(ex.map(one, todo), 1):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(f"[{i}/{len(todo)}] {r['root']} " + (r.get("error", "")[:60] or
                  f"agree={r['agree']} refuted={r['refuted']} missed={r['missed']}"), file=sys.stderr)
