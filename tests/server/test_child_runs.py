"""Runs in their own process (``RUN_ISOLATION=process``).

Most tests replace the child with a stand-in that speaks the same protocol
(control pipe, stdin commands, result file), so cancelling, timeouts,
breakpoints and the streaming calls are checked without Spark. One test runs
the real child on the template project, end to end through the API.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")

from ducta_server.config import Settings  # noqa: E402
from ducta_server.execution import child_runner  # noqa: E402
from ducta_server.execution.runner import RunSpec  # noqa: E402

#: The stand-in child. What it does is chosen by the spec's pipeline name.
FAKE_CHILD = textwrap.dedent(
    """
    import json, os, sys, time
    spec = json.load(open(sys.argv[1]))
    result_path = sys.argv[2]
    control = os.fdopen(int(os.environ["DUCTA_CHILD_CONTROL_FD"]), "w", buffering=1)
    send = lambda m: control.write(json.dumps(m) + "\\n")
    mode = spec["pipeline_name"]
    outcome, error, code = None, None, 0
    print("printed by the run", flush=True)
    send({"log": {"time": "2026-11-07T10:00:00+00:00", "level": "INFO",
                  "message": "[node_status] node_id=extract status=success", "node_id": None}})
    send({"log": {"time": "2026-11-07T10:00:01+00:00", "level": "WARNING",
                  "message": "inside a node", "node_id": "extract"}})
    if mode == "secrets":
        outcome = {k: os.environ.get(k) for k in ("JWT_SECRET_KEY", "DATABASE_URL", "KEEP_ME")}
    elif mode == "fails":
        error, code = "Pipeline 'fails' execution failed: boom", 1
    elif mode in ("forever", "sleep"):
        time.sleep(3600 if mode == "forever" else 0.6)
    elif mode == "pause":
        send({"event": "paused", "node": "extract"})
        assert json.loads(sys.stdin.readline()) == {"cmd": "resume"}
    elif mode == "stream":
        for line in sys.stdin:
            cmd = json.loads(line)
            if cmd["cmd"] == "snapshot":
                send({"reply": cmd["id"], "result": [{"execution_id": "s-1", "status": "running"}]})
            elif cmd["cmd"] == "restart":
                send({"reply": cmd["id"], "result": cmd["node"] == "score"})
                break
    json.dump({"outcome": outcome, "error": error, "certificate_run_id": "cert-1",
               "error_details": {"type": "ValueError", "message": "boom", "category": "permanent",
                                 "traceback": "tb", "traceback_lines": ["tb"]} if error else None},
              open(result_path, "w"))
    sys.exit(code)
    """
)


class _Manager:
    """What the child runner uses of the execution manager."""

    def __init__(self) -> None:
        self.cancelled = False
        self.output: List[str] = []
        self.entries: List[Any] = []
        self.engine: Any = None
        self.engines: List[Any] = []
        self.paused: List[str] = []
        self.certificate: Optional[str] = None

    def is_cancelled(self, execution_id: str) -> bool:
        return self.cancelled

    def _append_process_output(self, execution_id: str, message: str, *, level: str = "INFO"):
        self.output.append(message)

    def _emit(self, execution_id: str, entry: Any) -> None:
        self.entries.append(entry)

    def register_active_engine(self, execution_id: str, engine: Any) -> None:
        self.engine = engine
        self.engines.append(engine)

    def unregister_active_engine(self, execution_id: str) -> None:
        self.engine = None

    def wait_at_breakpoint(self, execution_id: str, node: str) -> None:
        self.paused.append(node)

    def attach_certificate(self, execution_id: str, run_id: str) -> None:
        self.certificate = run_id


class _Deadline:
    timeout_seconds = 60

    def __init__(self) -> None:
        self.has_timed_out = False


@pytest.fixture
def fake_child(tmp_path, monkeypatch):
    script = tmp_path / "fake_child.py"
    script.write_text(FAKE_CHILD, encoding="utf-8")
    started: List[int] = []
    real_popen = subprocess.Popen

    def popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        started.append(proc.pid)
        return proc

    monkeypatch.setattr(
        child_runner,
        "_child_command",
        lambda spec, result: [sys.executable, str(script), str(spec), str(result)],
    )
    monkeypatch.setattr(child_runner.subprocess, "Popen", popen)
    monkeypatch.setattr(child_runner, "STOP_GRACE_SECONDS", 2.0)
    return started


def _run(name: str, tmp_path: Path, manager: _Manager, deadline: Any = None, eid: str = "e1"):
    spec = RunSpec(source_path=tmp_path, pipeline_name=name, env="dev")
    return child_runner.run_in_child(eid, spec, tmp_path, manager, deadline)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); it has exited.
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(status.stdout.strip()) and not status.stdout.strip().startswith("Z")


class TestIsolationMode:
    @pytest.mark.parametrize(
        ("mode", "auth", "expected"),
        [
            ("auto", False, "thread"),
            ("auto", True, "process"),
            ("process", False, "process"),
            ("thread", True, "thread"),
        ],
    )
    def test_auto_isolates_once_accounts_are_on(self, mode, auth, expected, monkeypatch):
        settings = Settings(run_isolation=mode)
        monkeypatch.setattr(settings, "auth_enabled", auth)
        assert child_runner.isolation_mode(settings) == expected

    def test_without_posix_it_runs_in_process(self, monkeypatch):
        monkeypatch.setattr(child_runner, "_POSIX", False)
        assert child_runner.isolation_mode(Settings(run_isolation="process")) == "thread"

    def test_the_child_environment_drops_only_the_servers_secrets(self):
        base = {"JWT_SECRET_KEY": "k", "DATABASE_URL": "pg://", "DUCTA_ADMIN_PASSWORD": "p",
                "WAREHOUSE_PASSWORD": "w", "PATH": "/bin"}  # fmt: skip
        env = child_runner.child_environment(base)
        env.pop("PYTHONPATH", None)  # this server's Ducta, when run from a source tree
        assert env == {"WAREHOUSE_PASSWORD": "w", "PATH": "/bin"}

    def test_the_child_runs_this_servers_ducta(self, monkeypatch, tmp_path):
        """A server run from a source tree: its process must import the same Ducta
        and the same server, which a checkout keeps in two trees."""
        import ducta
        import ducta_server

        engine = tmp_path / "checkout" / "src"
        server = tmp_path / "checkout" / "server" / "src"
        monkeypatch.setattr(ducta, "__file__", str(engine / "ducta" / "__init__.py"))
        monkeypatch.setattr(ducta_server, "__file__", str(server / "ducta_server" / "__init__.py"))
        env = child_runner.child_environment({"PYTHONPATH": "/proj"})
        assert env["PYTHONPATH"].split(os.pathsep) == [
            str(engine.resolve()),
            str(server.resolve()),
            "/proj",
        ]

        installed = tmp_path / "lib" / "site-packages"
        monkeypatch.setattr(ducta, "__file__", str(installed / "ducta" / "__init__.py"))
        monkeypatch.setattr(
            ducta_server, "__file__", str(installed / "ducta_server" / "__init__.py")
        )
        assert child_runner.child_environment({}).get("PYTHONPATH") is None

    def test_protecting_the_server_is_linux_only(self, monkeypatch):
        monkeypatch.setattr(child_runner.sys, "platform", "darwin")
        assert child_runner.protect_server_process() is False


class TestRunInChild:
    def test_logs_output_outcome_and_certificate_come_back(self, fake_child, tmp_path):
        manager = _Manager()
        assert _run("ok", tmp_path, manager) is None
        assert "printed by the run" in manager.output
        status, node_line = manager.entries
        assert status.extra == {"type": "node_status", "node_id": "extract", "status": "success"}
        assert (node_line.level, node_line.extra) == ("WARNING", {"node_id": "extract"})
        assert manager.certificate == "cert-1"
        assert manager.engine is None  # unregistered once it ended

    def test_the_server_secrets_never_reach_the_run(self, fake_child, tmp_path, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "server-key")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/ducta")
        monkeypatch.setenv("KEEP_ME", "pipeline-credential")
        outcome = _run("secrets", tmp_path, _Manager())
        assert outcome == {
            "JWT_SECRET_KEY": None,
            "DATABASE_URL": None,
            "KEEP_ME": "pipeline-credential",
        }

    def test_a_failure_carries_its_analysed_error(self, fake_child, tmp_path):
        with pytest.raises(child_runner.ChildRunError) as failed:
            _run("fails", tmp_path, _Manager())
        assert str(failed.value) == "Pipeline 'fails' execution failed: boom"
        assert failed.value.error_details["category"] == "permanent"

    def test_cancelling_stops_the_process(self, fake_child, tmp_path):
        manager = _Manager()
        threading.Timer(0.8, lambda: setattr(manager, "cancelled", True)).start()
        with pytest.raises(RuntimeError, match="cancelled"):
            _run("forever", tmp_path, manager)
        assert not _alive(fake_child[0])

    def test_a_timeout_stops_the_process(self, fake_child, tmp_path):
        deadline = _Deadline()
        threading.Timer(0.8, lambda: setattr(deadline, "has_timed_out", True)).start()
        with pytest.raises(TimeoutError, match="exceeded timeout"):
            _run("forever", tmp_path, _Manager(), deadline)
        assert not _alive(fake_child[0])

    def test_a_breakpoint_waits_for_the_server_then_resumes(self, fake_child, tmp_path):
        manager = _Manager()
        assert _run("pause", tmp_path, manager) is None
        assert manager.paused == ["extract"]

    def test_the_streaming_calls_reach_the_running_child(self, fake_child, tmp_path):
        manager = _Manager()
        answers: Dict[str, Any] = {}

        def ask():
            while manager.engine is None:
                time.sleep(0.05)
            answers["snapshot"] = manager.engine.streaming_snapshot()
            answers["restart"] = manager.engine.restart_streaming_node("s-1", "score")

        asker = threading.Thread(target=ask)
        asker.start()
        _run("stream", tmp_path, manager)
        asker.join(timeout=5)
        assert answers == {
            "snapshot": [{"execution_id": "s-1", "status": "running"}],
            "restart": True,
        }

    def test_runs_of_one_pipeline_wait_for_each_other_others_do_not(self, fake_child, tmp_path):
        """The child sleeps 0.6s. One pipeline twice: one after the other. The same
        name in another project is another pipeline: side by side."""
        for project in ("p1", "p2"):
            (tmp_path / project).mkdir()

        def wall_time(projects: List[str]) -> float:
            def one(index: int, project: str) -> None:
                _run("sleep", tmp_path / project, _Manager(), eid=f"{project}-{index}")

            threads = [threading.Thread(target=one, args=pair) for pair in enumerate(projects)]
            start = time.monotonic()
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            return time.monotonic() - start

        serial = wall_time(["p1", "p1"])
        parallel = wall_time(["p1", "p2"])
        assert serial > parallel + 0.4, (serial, parallel)


class TestServerSide:
    def test_a_process_run_skips_the_in_process_path(self, tmp_path, monkeypatch):
        from ducta_server.config import get_settings
        from ducta_server.execution import runner

        calls: List[str] = []
        monkeypatch.setattr(
            child_runner, "run_in_child", lambda eid, spec, src, mgr, deadline: calls.append(eid)
        )
        monkeypatch.setenv("RUN_ISOLATION", "process")
        get_settings.cache_clear()

        class _M:
            def get_or_create_timeout_handler(self, execution_id):
                return None

            def set_active_execution(self, execution_id):
                raise AssertionError("a process run must not take the in-process path")

        try:
            spec = RunSpec(source_path=tmp_path, pipeline_name="etl", env="dev")
            runner.run_pipeline_sync("e9", spec, _M())
        finally:
            get_settings.cache_clear()
        assert calls == ["e9"]

    def test_an_analysed_error_is_recorded_as_sent(self):
        from ducta_server.execution.error_recovery import ErrorContext, ExecutionErrorLog

        log = ExecutionErrorLog("e1")
        log.log_error_details(
            {
                "type": "ValueError",
                "message": "boom",
                "category": "permanent",
                "traceback_lines": ["x"],
            },
            ErrorContext(execution_id="e1"),
        )
        (error,) = log.errors
        assert (error["error"]["type"], error["error"]["category"]) == ("ValueError", "permanent")
        assert error["hint"]

    def test_an_unknown_category_falls_back(self):
        from ducta_server.execution.error_recovery import ErrorContext, ExecutionErrorLog

        log = ExecutionErrorLog("e1")
        log.log_error_details({"category": "made-up"}, ErrorContext(execution_id="e1"))
        assert log.errors[0]["error"]["category"] == "unknown"


def test_a_real_run_in_its_own_process_through_the_api(tmp_path, monkeypatch):
    """The template's pipeline, run by the real child: same status, node dots and
    certificate as in-process — and the node cannot read the server's JWT key."""
    pytest.importorskip("pyspark")
    from fastapi.testclient import TestClient

    from ducta.console.templates import TemplateGenerator, TemplateType
    from ducta_server.config import get_settings
    from ducta_server.main import create_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUN_ISOLATION", "process")
    monkeypatch.setenv("JWT_SECRET_KEY", "server-key-under-test")
    monkeypatch.setenv("DUCTA_WORKSPACE", str(tmp_path))
    get_settings.cache_clear()
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    etl = root / "pipelines" / "etl.py"
    etl.write_text(
        etl.read_text(encoding="utf-8")
        + "\nimport os as _os\nfrom ducta_server.config import get_settings as _gs\n"
        + "print('PEEK', _os.environ.get('JWT_SECRET_KEY'), _gs().jwt_secret_key, _os.getpid())\n",
        encoding="utf-8",
    )
    try:
        with TestClient(create_app()) as client:
            client.params = {"source": str(root)}  # type: ignore[assignment]
            listed = client.get("/api/projects").json()
            project = (listed.get("projects") if isinstance(listed, dict) else listed)[0]["id"]
            started = client.post(
                f"/api/projects/{project}/pipelines/etl/execute", json={"env": "dev"}
            )
            assert started.status_code == 202, started.text
            execution_id = started.json()["id"]
            for _ in range(600):
                record = client.get(f"/api/executions/{execution_id}").json()
                if record["status"] not in ("pending", "running"):
                    break
                time.sleep(0.2)
            logs = client.get(f"/api/executions/{execution_id}/logs").json()
    finally:
        get_settings.cache_clear()

    assert record["status"] == "success", record
    assert record["certificate_run_id"]
    dots = [
        (e["extra"]["node_id"], e["extra"]["status"])
        for e in logs
        if e["extra"].get("type") == "node_status"
    ]
    assert ("load", "success") in dots
    (peek,) = [e["message"] for e in logs if e["message"].startswith("PEEK")]
    _, env_key, settings_key, pid = peek.split()
    assert (env_key, settings_key) == ("None", "change-me-in-production")
    assert int(pid) != os.getpid()


class TestChildSigterm:
    """The server stops a cancelled or timed-out run with SIGTERM. The child used to die on
    the spot: no certificate, no ``result.json``."""

    def test_sigterm_becomes_an_interrupt_once(self):
        import signal

        from ducta_server.execution import child

        before = signal.getsignal(signal.SIGTERM)
        try:
            child.install_sigterm_handler()
            assert issubclass(child.ChildTerminated, KeyboardInterrupt)
            with pytest.raises(child.ChildTerminated):
                os.kill(os.getpid(), signal.SIGTERM)
            # the first signal is handled; later ones are ignored (the server escalates to KILL)
            assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
            os.kill(os.getpid(), signal.SIGTERM)  # still alive
        finally:
            signal.signal(signal.SIGTERM, before)


def test_a_cancelled_real_run_leaves_its_certificate_and_writes_nothing_more(tmp_path, monkeypatch):
    """Cancelling a run in its own process: SIGTERM reaches the child, which seals a
    certificate that says it did not succeed, and the later nodes never write."""
    pytest.importorskip("pyspark")
    from fastapi.testclient import TestClient

    from ducta.console.templates import TemplateGenerator, TemplateType
    from ducta_server.config import get_settings
    from ducta_server.main import create_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUN_ISOLATION", "process")
    monkeypatch.setenv("DUCTA_WORKSPACE", str(tmp_path))
    get_settings.cache_clear()
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    etl = root / "pipelines" / "etl.py"
    etl.write_text(
        etl.read_text(encoding="utf-8").replace(
            '    if raw_data is None:\n        raise ValueError("raw_data cannot be None")',
            "    import time\n    time.sleep(60)",
            1,
        ),
        encoding="utf-8",
    )
    try:
        with TestClient(create_app()) as client:
            client.params = {"source": str(root)}  # type: ignore[assignment]
            listed = client.get("/api/projects").json()
            project = (listed.get("projects") if isinstance(listed, dict) else listed)[0]["id"]
            execution_id = client.post(
                f"/api/projects/{project}/pipelines/etl/execute", json={"env": "dev"}
            ).json()["id"]
            for _ in range(600):  # until `transform` is running
                logs = client.get(f"/api/executions/{execution_id}/logs").json()
                if any(
                    e["extra"].get("type") == "node_status"
                    and e["extra"].get("node_id") == "transform"
                    and e["extra"].get("status") == "running"
                    for e in logs
                ):
                    break
                time.sleep(0.2)
            else:
                pytest.fail("the run never reached `transform`")
            time.sleep(1)
            assert client.post(f"/api/executions/{execution_id}/cancel").status_code == 200
            for _ in range(250):
                record = client.get(f"/api/executions/{execution_id}").json()
                if record.get("certificate_run_id"):
                    break
                time.sleep(0.2)
            stopped_logs = client.get(f"/api/executions/{execution_id}/logs").json()
    finally:
        get_settings.cache_clear()

    assert record["status"] == "cancelled"
    assert record["certificate_run_id"], (
        f"the cancelled run left no certificate: {record}\n"
        + "\n".join(str(e.get("message"))[:200] for e in stopped_logs[-25:])
    )
    certs = list((root / "data" / "dev" / ".ducta" / "runs").glob("*/certificate.json"))
    assert certs and "success" not in certs[0].read_text(encoding="utf-8").split('"status"')[1][:12]
    assert not (root / "data" / "dev" / "silver").exists()


def test_a_cancellation_sends_the_child_one_term_however_many_places_stop_it():
    """`cancel_execution` calls the engine's `shutdown` while the run loop stops the process
    as well: two TERMs, and the second ended a child that was sealing its certificate."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    sent = []
    real = proc.send_signal
    proc.send_signal = lambda sig: (sent.append(sig), real(sig))[1]  # type: ignore[method-assign]
    threads = [threading.Thread(target=child_runner._stop, args=(proc,)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert proc.poll() is not None
    assert len(sent) == 1
