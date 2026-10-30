import os
from pathlib import Path

from qverify import runner


def test_backend_default_and_override(monkeypatch):
    monkeypatch.delenv("QV_SANDBOX", raising=False)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    assert runner.backend() == "docker"
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    assert runner.backend() == "sandbox-exec"
    monkeypatch.setenv("QV_SANDBOX", "docker")
    assert runner.backend() == "docker"


def test_docker_command_is_locked_down(tmp_path, monkeypatch):
    qhome = tmp_path / "q"
    (qhome / "l64").mkdir(parents=True)
    (qhome / "l64" / "q").write_text("")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("Q", str(qhome / "l64" / "q"))
    monkeypatch.delenv("QLIC", raising=False)
    cmd = runner.docker_command("n", ws, str(out), {"QV_FILES": "a.q", "QV_OUT": str(out / "o.json")})
    flat = " ".join(cmd)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges"):
        assert flag in flat
    mounts = [cmd[i + 1] for i, c in enumerate(cmd) if c == "-v"]
    writable = [m for m in mounts if m.endswith(":rw")]
    assert writable == [f"{out}:{out}:rw"]  # the only writable bind
    assert f"{ws.resolve()}:{ws.resolve()}:ro" in mounts
    assert all(m.split(":")[0] != str(Path.home()) for m in mounts)  # home itself is never mounted
