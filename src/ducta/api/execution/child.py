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

The process a run executes in when the server isolates runs (``RUN_ISOLATION``).

Started by :mod:`ducta.api.execution.child_runner` as
``python -m ducta.api.execution.child <spec.json> <result.json>``. It runs the
pipeline exactly as the API would in its own process, and talks to the server:

- **stdout/stderr** — what the engine prints (the CLI's reporter, Spark): the
  run log's terminal lines, as in the server's own process;
- **the control pipe** (fd in ``DUCTA_CHILD_CONTROL_FD``), one JSON object per
  line — ``{"log": …}`` structured log records, ``{"event": "paused", "node": …}``
  at a data breakpoint, ``{"reply": n, "result": …}`` answers;
- **stdin**, one JSON object per line from the server — ``{"cmd": "resume"}``
  after a breakpoint, ``{"cmd": "snapshot", "id": n}`` (the live streaming
  status), ``{"cmd": "restart", "id": n, "stream": …, "node": …}``.

The outcome, the error (already analysed: the server records it like its own)
and the certificate run id go to *result.json*; the exit code is 0 when the
pipeline returned, 1 when it raised.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: The environment variable naming the control pipe's file descriptor.
CONTROL_FD_ENV = "DUCTA_CHILD_CONTROL_FD"


class Control:
    """The child's end of the conversation with the server."""

    def __init__(self, fd: int) -> None:
        self._out = os.fdopen(fd, "w", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()
        self._resume = threading.Event()

    def send(self, message: Dict[str, Any]) -> None:
        line = json.dumps(message, default=str)
        with self._lock:
            try:
                self._out.write(line + "\n")
            except (OSError, ValueError):
                pass  # the server is gone; the run is about to be stopped

    def log_sink(self, message: Any) -> None:
        from ducta.core.execution_context import node_id_var

        record = message.record
        self.send(
            {
                "log": {
                    "time": record["time"].isoformat(),
                    "level": record["level"].name,
                    "message": record["message"],
                    "node_id": node_id_var.get(),
                }
            }
        )

    def pause(self, node: str) -> None:
        """A data breakpoint: tell the server, wait until it says resume.

        A cancellation while paused stops this whole process instead.
        """
        self._resume.clear()
        self.send({"event": "paused", "node": node})
        self._resume.wait()

    def serve(self, engine: Any) -> None:
        """Answer the server's commands (on stdin) until it closes it."""

        def loop() -> None:
            for line in sys.stdin:
                try:
                    command = json.loads(line)
                except ValueError:
                    continue
                self._answer(engine, command)

        threading.Thread(target=loop, name="ducta-child-commands", daemon=True).start()

    def _answer(self, engine: Any, command: Dict[str, Any]) -> None:
        name = command.get("cmd")
        if name == "resume":
            self._resume.set()
            return
        result: Any = None
        try:
            if name == "snapshot":
                result = engine.streaming_snapshot()
            elif name == "restart":
                result = bool(
                    engine.restart_streaming_node(str(command["stream"]), str(command["node"]))
                )
        except Exception as e:  # noqa: BLE001 — the server gets an empty answer, not a crash
            from loguru import logger

            logger.warning("Could not answer '{}': {}", name, e)
        self.send({"reply": command.get("id"), "result": result})


def _route_logs(control: Control) -> None:
    """Every log record goes to the server, structured — as the in-process sink takes it."""
    from loguru import logger

    logger.remove()
    logger.enable("ducta")
    logger.add(control.log_sink, level="DEBUG", format="{message}")


def prepare(raw: Dict[str, Any]) -> Tuple[Any, Any]:
    """The run's spec and context, set up as the server sets them up in-process.

    Also used by :mod:`ducta.api.execution.debug_child`.
    """
    from ducta.api.execution.runner import (
        RunSpec,
        _resolve_execution_context,
        normalize_execution_context_paths,
        redirect_run_writes,
        select_execution_cwd,
    )

    fields = {k: v for k, v in raw.items() if k != "execution_id"}
    spec = RunSpec(**{**fields, "source_path": Path(raw["source_path"]), "debug": False})
    source_path = spec.source_path
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))
    ctx, env_dir = _resolve_execution_context(source_path, spec.env, spec.pipeline_name, None)
    gs = getattr(ctx, "global_config", None)
    if isinstance(gs, dict):
        gs["pipeline_name"] = spec.pipeline_name
        if spec.project_id:
            gs["project_id"] = spec.project_id
        if raw.get("execution_id"):
            gs["api_execution_id"] = raw["execution_id"]
    cwd = select_execution_cwd(source_path, env_dir, ctx)
    os.chdir(cwd)
    normalize_execution_context_paths(ctx, cwd)
    redirect_run_writes(ctx, spec)
    return spec, ctx


def _error_details(exc: BaseException) -> Dict[str, Any]:
    from ducta.api.execution.error_recovery import ErrorAnalyzer

    try:
        return ErrorAnalyzer.get_error_details(exc)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return {"type": type(exc).__name__, "message": str(exc), "category": "unknown"}


def main(argv: list) -> int:
    from ducta.api.execution.context import execution_id_var

    raw = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    result_path = Path(argv[2])
    control = Control(int(os.environ.pop(CONTROL_FD_ENV)))
    _route_logs(control)
    if raw.get("execution_id"):
        execution_id_var.set(raw["execution_id"])

    from ducta.api.execution.runner import (
        _attach_stream_alerts,
        _dispatch_pipeline_type,
        print_run_finished,
        print_run_header,
        run_failure_message,
    )
    from ducta.core.errors import DuctaError

    outcome: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    engine: Any = None
    ctx: Any = None
    pipeline_name = str(raw.get("pipeline_name") or "")
    try:
        from ducta.reporting import set_reporter

        try:
            spec, ctx = prepare(raw)
        except Exception as exc:
            raise RuntimeError(run_failure_message(pipeline_name, exc)) from exc
        print_run_header(spec)
        from ducta.console.ux.reporter import ConsoleReporter

        set_reporter(ConsoleReporter())

        from ducta.core.executors import PipelineExecutor
        from ducta.stream.constants import PipelineType

        if spec.pause_after:
            ctx.pause_after = set(spec.pause_after)
            ctx.breakpoint_hook = control.pause
        engine = PipelineExecutor(ctx)
        pipeline = engine.batch_executor._get_pipeline_config(spec.pipeline_name)
        pipeline_type = pipeline.get("type", PipelineType.BATCH.value)
        if pipeline_type == PipelineType.STREAMING.value:
            _attach_stream_alerts(engine, spec.source_path, spec.project_id, spec.env)
        control.serve(engine)
        try:
            outcome = _dispatch_pipeline_type(engine, pipeline_type, spec, ctx)
        except DuctaError:
            raise
        except Exception as exc:
            raise RuntimeError(run_failure_message(pipeline_name, exc)) from exc
        print_run_finished(outcome, pipeline_name)
    except BaseException as exc:  # noqa: BLE001 — reported to the server, which fails the run
        error = str(exc) or type(exc).__name__
        details = _error_details(exc)
    finally:
        result_path.write_text(
            json.dumps(
                {
                    "outcome": outcome,
                    "error": error,
                    "error_details": details,
                    "certificate_run_id": getattr(ctx, "_run_id", None),
                    "retrain": getattr(ctx, "_retrain", None),
                },
                default=str,
            ),
            encoding="utf-8",
        )
        if engine is not None:
            try:
                engine.shutdown()
            except Exception:  # noqa: BLE001
                pass
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
