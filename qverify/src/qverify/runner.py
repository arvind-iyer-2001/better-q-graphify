"""Run reflect.q in a sandboxed q process and return its JSON."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

REFLECT = Path(__file__).with_name("reflect.q")


def q_binary() -> str:
    return os.environ.get("Q") or str(Path.home() / ".kx/bin/q")


def _profile(outdir: str, root: str) -> str:
    """Deny network, writes (except outdir) and process exec; deny reads under $HOME except q's install and `root`."""
    q = q_binary()
    home = str(Path.home())
    kx = str(Path(q).resolve().parents[1])
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-write*)
(deny process-exec* (with no-log))
(allow process-exec (literal "{q}"))
(allow file-write* (subpath "{outdir}") (literal "/dev/null"))
(deny file-read* (subpath "{home}"))
(allow file-read* (subpath "{kx}") (subpath "{root}") (subpath "{REFLECT.parent}") (literal "{home}"))
"""


def reflect(root: Path, files: list[Path], timeout: int = 60) -> dict:
    """Load `files` (already ordered) with cwd=root; return parsed reflection."""
    with tempfile.TemporaryDirectory() as td:
        td = str(Path(td).resolve())
        prof = Path(td) / "p.sb"
        prof.write_text(_profile(td, str(root.resolve())))
        out = Path(td) / "out.json"
        env = {**os.environ, "QV_FILES": ":".join(str(f) for f in files), "QV_OUT": str(out)}
        cmd = ["sandbox-exec", "-f", str(prof), q_binary(), str(REFLECT), "-q", "-w", "1024"]
        try:
            p = subprocess.run(cmd, cwd=root, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"error": f"timeout after {timeout}s", "files": [], "defs": []}
        if not out.exists():
            return {"error": (p.stdout + p.stderr)[-600:] or f"q exit {p.returncode}",
                    "files": [], "defs": []}
        return json.loads(out.read_text())


def reflect_isolated(root: Path, order: list[Path], deps: dict[Path, list[Path]], timeout: int = 30) -> dict:
    """One sandboxed q per file: transitive deps are preloaded, only the target's diff is attributed.
    A crash, hang or `exit` in one file cannot lose the others."""
    def closure(f: Path, seen=None) -> list[Path]:
        seen = seen if seen is not None else set()
        out: list[Path] = []
        for d in deps.get(f, []):
            if d not in seen:
                seen.add(d)
                out += closure(d, seen) + [d]
        return out

    files, defs, errors = [], {}, {}
    for f in order:
        pre = [d for d in closure(f) if d != f]
        r = reflect(root, pre + [f], timeout)
        if r.get("error"):
            errors[str(f)] = r["error"]
            continue
        rec = next((x for x in r["files"] if Path(x["file"]).resolve() == f), None)
        if rec:
            files.append(rec)
            mine = set(rec["new"]) | set(rec["changed"])
            for d in r["defs"]:
                if d["name"] in mine:
                    defs[(str(f), d["name"])] = {**d, "file": str(f)}
    return {"files": files, "defs": list(defs.values()), "errors": errors}
