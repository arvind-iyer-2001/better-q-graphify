"""Run reflect.q in a sandboxed q process and return its JSON."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
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


def backend() -> str:
    """`QV_SANDBOX=sandbox-exec|docker` forces one; default is sandbox-exec on macOS and docker elsewhere."""
    forced = os.environ.get("QV_SANDBOX")
    if forced:
        if forced not in ("sandbox-exec", "docker"):
            raise ValueError(f"QV_SANDBOX must be sandbox-exec or docker, not {forced!r}")
        return forced
    return "sandbox-exec" if sys.platform == "darwin" else "docker"


def docker_command(name: str, root: Path, outdir: str, env: dict[str, str]) -> list[str]:
    """`docker run` for one reflect.q pass. The container sees only: the workspace (read-only), reflect.q and
    the q install + licence (read-only), and `outdir` (the single writable bind). No network, no capabilities,
    read-only root, tmpfs /tmp. Paths are mounted at their host location so QV_FILES needs no translation."""
    q = q_binary()
    qhome = str(Path(q).resolve().parents[1])
    ro = [str(root.resolve()), str(REFLECT.parent), qhome]
    lic = os.environ.get("QLIC")
    if lic:
        ro.append(str(Path(lic).resolve()))
    cmd = ["docker", "run", "--rm", "--init", "--name", name,
           "--network", "none", "--read-only", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges", "--pids-limit", "256",
           "--memory", os.environ.get("QV_MEMORY", "2g"), "--cpus", os.environ.get("QV_CPUS", "1"),
           "--user", f"{os.getuid()}:{os.getgid()}", "--tmpfs", "/tmp:rw,size=256m",
           "-e", "HOME=/tmp", "-e", f"QHOME={qhome}", "-e", f"QV_FILES={env['QV_FILES']}", "-e", f"QV_OUT={env['QV_OUT']}"]
    if lic:
        cmd += ["-e", f"QLIC={Path(lic).resolve()}"]
    for path in dict.fromkeys(ro):
        cmd += ["-v", f"{path}:{path}:ro"]
    cmd += ["-v", f"{outdir}:{outdir}:rw", "-w", str(root.resolve()),
            os.environ.get("QV_IMAGE", "debian:stable-slim"), q, str(REFLECT), "-q", "-w", "1024"]
    return cmd


def reflect(root: Path, files: list[Path], timeout: int = 60) -> dict:
    """Load `files` (already ordered) with cwd=root; return parsed reflection."""
    with tempfile.TemporaryDirectory() as td:
        td = str(Path(td).resolve())
        out = Path(td) / "out.json"
        env = {**os.environ, "QV_FILES": ":".join(str(f) for f in files), "QV_OUT": str(out)}
        name = None
        if backend() == "docker":
            name = f"qverify-{uuid.uuid4().hex[:12]}"
            os.chmod(td, 0o777)  # the container runs as the caller's uid, but keep the bind writable regardless
            cmd = docker_command(name, root, td, env)
        else:
            prof = Path(td) / "p.sb"
            prof.write_text(_profile(td, str(root.resolve())))
            cmd = ["sandbox-exec", "-f", str(prof), q_binary(), str(REFLECT), "-q", "-w", "1024"]
        try:
            p = subprocess.run(cmd, cwd=root, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            if name:  # killing the docker CLI does not stop the container
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
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
