"""Debug runs: listen once on loopback, wait for an IDE, never block forever."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from ducta.api.services import debugger


def test_attach_config_maps_the_project():
    cfg = debugger.attach_config(Path("/srv/proj"), 5678)
    assert cfg["connect"] == {"host": "127.0.0.1", "port": 5678}
    assert cfg["pathMappings"][0]["remoteRoot"] == "/srv/proj"


def test_free_port_is_on_loopback_and_bindable():
    import socket

    port = debugger.free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


class _Manager:
    def __init__(self):
        self.port = None
        self.cert = None
        self.attached = False

    def set_debug_port(self, _id, port):
        self.port = port

    def debug_attached(self, _id):
        return self.attached

    def is_cancelled(self, _id):
        return False

    def attach_certificate(self, _id, run_id):
        self.cert = run_id


def _fake_popen(exit_code, result):
    import json

    class Proc:
        def __init__(self, cmd, **kw):
            self.cmd = cmd
            self.returncode = None
            self.env = kw.get("env", {})
            Path(cmd[-1]).write_text(json.dumps(result))

        def poll(self):
            self.returncode = exit_code
            return exit_code

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return exit_code

        def kill(self):
            pass

    return Proc


def test_a_debug_run_runs_in_its_own_process(monkeypatch, tmp_path):
    import subprocess

    from ducta.api.execution import runner

    seen = {}
    proc_cls = _fake_popen(0, {"outcome": None, "certificate_run_id": "abc123"})

    def popen(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        return proc_cls(cmd, **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(debugger, "available", lambda: True)
    mgr = _Manager()
    spec = runner.RunSpec(source_path=tmp_path, pipeline_name="p", env="dev", debug=True)
    assert runner._run_debug_child("e1", spec, tmp_path, mgr) is None
    assert mgr.port and mgr.cert == "abc123"
    cmd = seen["cmd"]
    assert cmd[cmd.index("-m") + 1] == "debugpy" and "--wait-for-client" in cmd
    assert f"127.0.0.1:{mgr.port}" in cmd
    assert "ducta.api.execution.debug_child" in cmd
    assert seen["env"]["PYDEVD_USE_SYS_MONITORING"] == "0"


def test_a_failed_debug_run_fails_the_run(monkeypatch, tmp_path):
    import subprocess

    from ducta.api.execution import runner

    monkeypatch.setattr(subprocess, "Popen", _fake_popen(1, {"error": "KeyError: 'G4'"}))
    monkeypatch.setattr(debugger, "available", lambda: True)
    spec = runner.RunSpec(source_path=tmp_path, pipeline_name="p", env="dev", debug=True)
    with pytest.raises(RuntimeError, match="G4"):
        runner._run_debug_child("e1", spec, tmp_path, _Manager())
