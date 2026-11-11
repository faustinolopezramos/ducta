"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

Runs in their own process (``RUN_ISOLATION=process``), seen from the server.

A run's code then cannot read this process's memory — its settings, the JWT
signing key — and its environment does not carry the server's own secrets
(:data:`SERVER_SECRETS`). Cancelling or timing out a run stops its process
(and the Spark JVM it started), which a thread could not do, and runs no
longer wait for each other: ``MAX_CONCURRENT_EXECUTIONS`` is what bounds them.

It is not a sandbox: the process belongs to the same OS user as the server, so
the files the server can read (a ``.env`` next to it, a SQLite database) it can
read too, and on macOS it can list the server's environment (``ps eww``). On
Linux :func:`protect_server_process` closes ``/proc/<pid>/environ`` and memory.

The child is :mod:`ducta.api.execution.child`; the protocol is described there.
"""

from __future__ import annotations

import dataclasses
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ducta.api.execution.child import CONTROL_FD_ENV
from ducta.server_secrets import SERVER_SECRETS as _SERVER_SECRETS

#: The server's own secrets (one list, in :mod:`ducta.server_secrets`), never handed to
#: a run's process. A pipeline's credentials (``WAREHOUSE_PASSWORD`` …) are the
#: pipeline's, and stay.
SERVER_SECRETS = sorted(_SERVER_SECRETS)

#: How long a stopped run's process gets to exit before it is killed.
STOP_GRACE_SECONDS = 10.0

#: How long the server waits for a running child to answer a question.
ANSWER_TIMEOUT_SECONDS = 10.0

_POSIX = os.name == "posix"


def isolation_mode(settings: Any) -> str:
    """``process`` or ``thread``: where this server runs pipelines.

    ``auto`` isolates when accounts are on (people other than the operator run
    code) and keeps the faster in-process runs for a personal ``ducta ui``.
    Process runs need POSIX (fd passing, process groups).
    """
    mode = str(getattr(settings, "run_isolation", "auto") or "auto")
    if mode == "auto":
        mode = "process" if getattr(settings, "auth_enabled", False) else "thread"
    if mode == "process" and not _POSIX:
        return "thread"
    return mode


def child_environment(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The environment a run's process gets: this one's, minus the server's secrets."""
    env = dict(os.environ if base is None else base)
    for name in SERVER_SECRETS:
        env.pop(name, None)
    # The run's process must run this server's Ducta. A server started from a source
    # tree (not an installed package) would otherwise get whatever Ducta the
    # interpreter has installed, or none. An installed one is found anyway, and a
    # site-packages entry on PYTHONPATH would come before the standard library.
    import ducta

    root = str(Path(ducta.__file__).resolve().parent.parent)
    if Path(root).name not in ("site-packages", "dist-packages"):
        entries = [e for e in env.get("PYTHONPATH", "").split(os.pathsep) if e]
        if root not in entries:
            env["PYTHONPATH"] = os.pathsep.join([root, *entries])
    return env


def protect_server_process() -> bool:
    """On Linux, keep other processes of this user out of this one's memory and environment.

    ``PR_SET_DUMPABLE=0`` makes ``/proc/<pid>/environ`` and ``/proc/<pid>/mem``
    root-only and refuses ``ptrace`` from a non-root process — what a run's
    process would otherwise use to read the JWT key from the server. A process
    started later is dumpable again (its own setting). Also disables core dumps
    of the server. Returns ``True`` when applied.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        pr_set_dumpable = 4
        return int(libc.prctl(pr_set_dumpable, 0, 0, 0, 0)) == 0
    except (OSError, AttributeError):
        return False


_pipeline_locks: Dict[Tuple[str, str], threading.Lock] = {}
_pipeline_locks_guard = threading.Lock()


def _pipeline_lock(source_path: Path, pipeline_name: str) -> threading.Lock:
    key = (str(source_path), pipeline_name)
    with _pipeline_locks_guard:
        return _pipeline_locks.setdefault(key, threading.Lock())


def _wait_for_turn(
    lock: threading.Lock, execution_id: str, manager: Any, timeout_handler: Any
) -> None:
    """Wait until no other run of this pipeline is running here.

    Two runs of one pipeline write the same outputs: run side by side, the second
    stopped at once on the output lock ("locked by another run"). In this process
    they used to wait for each other; they still do. Other pipelines go in parallel.
    """
    announced = False
    while not lock.acquire(timeout=0.2):
        if not announced:
            logger.info("Waiting for the run of this pipeline that is already running")
            announced = True
        if manager.is_cancelled(execution_id):
            raise RuntimeError("Execution cancelled by user")
        if timeout_handler is not None and timeout_handler.has_timed_out:
            raise TimeoutError(
                f"Pipeline execution {execution_id} exceeded timeout of "
                f"{timeout_handler.timeout_seconds}s"
            )


class ChildRunError(RuntimeError):
    """A run's process failed; ``error_details`` is its exception, already analysed."""

    def __init__(self, message: str, error_details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.error_details = error_details


def _stop(proc: "subprocess.Popen[bytes]") -> None:
    """Stop *proc* and everything it started (its Spark JVM): TERM, then KILL."""
    if proc.poll() is not None:
        return

    def signal_all(sig: int) -> None:
        try:
            if _POSIX:
                os.killpg(proc.pid, sig)
            else:
                proc.send_signal(sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    signal_all(signal.SIGTERM)
    try:
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        signal_all(getattr(signal, "SIGKILL", signal.SIGTERM))
        proc.wait(timeout=STOP_GRACE_SECONDS)


class ChildEngine:
    """A run's engine as the API sees it while it runs in its own process.

    Registered as the execution's active engine, so the streaming routes and
    cancellation work as they do for a run in this process: each call becomes
    a command on the child's stdin, answered on its control pipe.
    """

    def __init__(self, proc: "subprocess.Popen[bytes]") -> None:
        self._proc = proc
        self._write_lock = threading.Lock()
        self._calls_lock = threading.Lock()
        self._next_id = 0
        self._waiting: Dict[int, Tuple[threading.Event, List[Any]]] = {}

    def _write(self, message: Dict[str, Any]) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            return
        with self._write_lock:
            try:
                stdin.write((json.dumps(message) + "\n").encode("utf-8"))
                stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass  # the process has ended

    def _call(self, command: str, **args: Any) -> Any:
        with self._calls_lock:
            self._next_id += 1
            call_id = self._next_id
            done, slot = threading.Event(), [None]
            self._waiting[call_id] = (done, slot)
        self._write({"cmd": command, "id": call_id, **args})
        answered = done.wait(ANSWER_TIMEOUT_SECONDS)
        with self._calls_lock:
            self._waiting.pop(call_id, None)
        return slot[0] if answered else None

    def answered(self, call_id: Any, result: Any) -> None:
        with self._calls_lock:
            waiting = self._waiting.get(call_id) if isinstance(call_id, int) else None
        if waiting is not None:
            waiting[1][0] = result
            waiting[0].set()

    def resume(self) -> None:
        self._write({"cmd": "resume"})

    def streaming_snapshot(self) -> List[Dict[str, Any]]:
        result = self._call("snapshot")
        return result if isinstance(result, list) else []

    def restart_streaming_node(self, stream_execution_id: str, node_name: str) -> bool:
        return bool(self._call("restart", stream=stream_execution_id, node=node_name))

    def shutdown(self) -> None:
        """What a cancellation calls: stop the run's process."""
        _stop(self._proc)


def _read_output(proc: "subprocess.Popen[bytes]", manager: Any, execution_id: str) -> None:
    from ducta.api.execution.output_capture import append_output_line

    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):
        append_output_line(manager, execution_id, raw.decode(errors="replace").rstrip("\r\n"))


def _read_control(fd: int, engine: ChildEngine, manager: Any, execution_id: str) -> None:
    from ducta.api.execution.log_sink import log_entry

    def pause(node: str) -> None:
        try:
            manager.wait_at_breakpoint(execution_id, node)
        except Exception:  # noqa: BLE001 — cancelled while paused: the run is being stopped
            return
        engine.resume()

    with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as control:
        for line in control:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("log"), dict):
                record = message["log"]
                try:
                    when = datetime.fromisoformat(str(record.get("time")))
                except ValueError:
                    continue
                entry = log_entry(
                    when,
                    str(record.get("level") or "INFO"),
                    str(record.get("message") or ""),
                    record.get("node_id") or None,
                )
                manager._emit(execution_id, entry)
            elif "reply" in message:
                engine.answered(message.get("reply"), message.get("result"))
            elif message.get("event") == "paused":
                threading.Thread(
                    target=pause,
                    args=(str(message.get("node") or "?"),),
                    name=f"ducta-pause-{execution_id}",
                    daemon=True,
                ).start()


def _child_command(spec_file: Path, result_file: Path) -> List[str]:
    return [sys.executable, "-m", "ducta.api.execution.child", str(spec_file), str(result_file)]


def run_in_child(
    execution_id: str,
    spec: Any,
    source_path: Path,
    manager: Any,
    timeout_handler: Any = None,
) -> Optional[Dict[str, Any]]:
    """Run *spec* in its own process; wait for it. Returns what the run returned."""
    lock = _pipeline_lock(source_path, spec.pipeline_name)
    _wait_for_turn(lock, execution_id, manager, timeout_handler)
    try:
        return _run_in_child(execution_id, spec, source_path, manager, timeout_handler)
    finally:
        lock.release()


def _run_in_child(
    execution_id: str,
    spec: Any,
    source_path: Path,
    manager: Any,
    timeout_handler: Any,
) -> Optional[Dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="ducta-run-") as tmp:
        spec_file, result_file = Path(tmp) / "spec.json", Path(tmp) / "result.json"
        payload = {
            **dataclasses.asdict(spec),
            "source_path": str(source_path),
            "execution_id": execution_id,
        }
        spec_file.write_text(json.dumps(payload, default=str), encoding="utf-8")
        read_fd, write_fd = os.pipe()
        env = child_environment()
        env[CONTROL_FD_ENV] = str(write_fd)
        cmd = _child_command(spec_file, result_file)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(source_path),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                pass_fds=(write_fd,),
                start_new_session=_POSIX,
            )
        except BaseException:
            os.close(read_fd)
            raise
        finally:
            os.close(write_fd)  # the child holds its own copy; EOF comes when it exits
        logger.debug("Run {} in its own process (pid {})", execution_id, proc.pid)

        engine = ChildEngine(proc)
        readers = [
            threading.Thread(target=_read_output, args=(proc, manager, execution_id), daemon=True),
            threading.Thread(
                target=_read_control,
                args=(read_fd, engine, manager, execution_id),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()
        manager.register_active_engine(execution_id, engine)
        try:
            while proc.poll() is None:
                if manager.is_cancelled(execution_id):
                    _stop(proc)
                    raise RuntimeError("Execution cancelled by user")
                if timeout_handler is not None and timeout_handler.has_timed_out:
                    _stop(proc)
                    raise TimeoutError(
                        f"Pipeline execution {execution_id} exceeded timeout of "
                        f"{timeout_handler.timeout_seconds}s"
                    )
                time.sleep(0.2)
        finally:
            _stop(proc)  # anything (a timeout injected here) leaves no process behind
            manager.unregister_active_engine(execution_id)
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            for reader in readers:
                reader.join(timeout=5)
        result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}

    if result.get("certificate_run_id"):
        manager.attach_certificate(execution_id, str(result["certificate_run_id"]))
    if isinstance(result.get("retrain"), dict):
        manager.attach_retrain(execution_id, result["retrain"])
    if proc.returncode != 0:
        raise ChildRunError(
            result.get("error") or f"The run's process exited with code {proc.returncode}",
            result.get("error_details"),
        )
    return result.get("outcome")
