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
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from loguru import logger  # type: ignore

from ducta import state
from ducta.core.context_utils import get_context_value
from ducta.core.errors import DuctaError
from ducta.core.ledger import RETRAIN_ATTR, RUN_ID_ATTR
from ducta.runs.context import normalize_execution_context_paths, select_execution_cwd
from ducta_server.execution.output_capture import ProcessOutputCapture

_stdout_capture_lock = threading.Lock()


@contextlib.contextmanager
def _acquire_stdout_capture_lock(timeout: float) -> Iterator[None]:
    """Acquire `_stdout_capture_lock` with a timeout instead of blocking forever.

    `Future.cancel()`/a timeout can't actually kill a running thread (same
    limitation already documented for `ducta.core.execution`), so a
    hung execution keeps holding this process-global lock indefinitely. An
    unbounded `acquire()` here meant one hung execution silently wedged
    every future execution forever with no visible error. Failing fast with
    a clear, `error`-level-logged message doesn't stop the hung thread, but
    it stops the cascade.
    """
    from ducta_server.exceptions import ExecutionError

    if not _stdout_capture_lock.acquire(timeout=timeout):
        logger.error(
            "Timed out after {timeout}s waiting for the output-capture lock — "
            "a previous execution may be hung and still holding it.",
            timeout=timeout,
        )
        raise ExecutionError(
            f"Output capture busy — a previous execution may be hung "
            f"(timed out after {timeout}s waiting for it to release the lock)."
        )
    try:
        yield
    finally:
        _stdout_capture_lock.release()


# ── Multi-project workspace helpers ──────────────────────────────────────────


def _project_owns_pipeline(project_dir: Path, pipeline_name: str) -> bool:
    """Whether the Ducta project in *project_dir* defines *pipeline_name*."""
    from ducta.setting.project.loader import find_project_root, read_project

    root = find_project_root(project_dir)
    if root is None:
        return False
    try:
        return pipeline_name in read_project(root).pipelines
    except Exception:
        return False


def resolve_project_source(source_path: Path, pipeline_name: str) -> Path:
    """Return the project directory that owns *pipeline_name*.

    When *source_path* is a multi-project workspace (has a ``projects/``
    subdirectory and no top-level environment file), scans each sub-project to
    find which one declares the pipeline and returns its directory so execution
    can load the correct context and CWD.

    Falls back to *source_path* unchanged when no match is found or when
    *source_path* is already a single-project directory.
    """
    from ducta.setting.project.loader import find_project_root

    # A single project: no lookup needed.
    if find_project_root(source_path) is not None:
        return source_path

    projects_dir = source_path / "projects"
    if not projects_dir.is_dir():
        return source_path

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        if _project_owns_pipeline(project_dir, pipeline_name):
            logger.info(
                "Multi-project workspace: resolved pipeline '{pipeline}' → project '{proj}'",
                pipeline=pipeline_name,
                proj=project_dir.name,
            )
            return project_dir

    logger.warning(
        "Pipeline '{pipeline}' not found in any project under '{ws}'; using workspace root",
        pipeline=pipeline_name,
        ws=source_path,
    )
    return source_path


# ── Path normalisation helpers ────────────────────────────────────────────────


# ── Main synchronous runner ───────────────────────────────────────────────────


def _run_sanity_checks(ctx: Any, pipeline_name: str) -> None:
    """Run node input sanity checks only. Raises RuntimeError if any node fails.

    Mirrors the CLI ``--sanity-only`` path (see cli/commands/execution_cmds.py).
    """
    from ducta.check.engine import QualityReporter, SanityPhaseRunner

    logger.info("Running sanity checks only for pipeline '{}'", pipeline_name)
    runner = SanityPhaseRunner(fail_fast=False)
    reports = runner.run_preflight_checks(
        {"nodes": ctx.nodes_config}, ctx, pipeline_name=pipeline_name
    )
    QualityReporter().render_pipeline_summary(reports, show_details=True)
    failed = [r for r in reports.values() if not r.passed]
    if failed:
        raise RuntimeError(f"{len(failed)} node(s) failed sanity checks")
    logger.success("All sanity checks passed")


def _log_dry_run(engine: Any, spec: RunSpec) -> None:
    """Validate the pipeline and log its plan without executing (``--dry-run``)."""
    pipeline_name = spec.pipeline_name
    if not engine.validate_pipeline(pipeline_name):
        available = engine.list_pipelines()
        raise RuntimeError(
            f"Pipeline '{pipeline_name}' not found. Available: {', '.join(available) or 'none'}"
        )
    info = engine.get_pipeline_info(pipeline_name)
    node_names = info.get("nodes", [])
    logger.info("DRY-RUN MODE: Pipeline '{}' will not be executed", pipeline_name)
    logger.info("  Nodes: {}", ", ".join(node_names) if node_names else "None")
    if spec.node_name:
        logger.info("  Single node: {}", spec.node_name)
    if spec.start_date:
        logger.info("  Start date: {}", spec.start_date)
    if spec.end_date:
        logger.info("  End date: {}", spec.end_date)
    logger.success("DRY-RUN completed — no execution performed")


@contextlib.contextmanager
def _execution_module_isolation_scope(execution_id: str, manager: Any) -> Iterator[None]:
    """Snapshot ``sys.modules`` for *execution_id* on entry, and clean up any
    modules imported during the run on exit — while the output-capture lock
    is still held, so no concurrent run can lose its imports.
    """
    manager._isolation_manager.snapshot_modules(execution_id)
    try:
        yield
    finally:
        try:
            removed = manager._isolation_manager.cleanup(execution_id)
            logger.debug("Module cleanup: removed {count} modules", count=removed)
        except Exception as exc:
            logger.debug("Module isolation cleanup failed: {exc}", exc=exc)


def _resolve_execution_context(
    source_path: Path,
    env: str,
    pipeline_name: str,
    timeout_handler: Any,
) -> "tuple[Any, Path]":
    """Build the pipeline execution ``Context`` and the directory it runs in."""
    from ducta_server.workspace.manager import WorkspaceManager  # avoid circular at module level

    env_dir = source_path / env if (source_path / env).is_dir() else source_path
    workspace = WorkspaceManager(source_path)
    if timeout_handler:
        timeout_handler.verify()
    try:
        ctx = workspace.load_context(env)
    except Exception as exc:
        raise RuntimeError(f"Failed to load context for env '{env}': {exc}") from exc
    return ctx, env_dir


def _dispatch_pipeline_type(
    engine: Any, pipeline_type: str, spec: RunSpec, ctx: Any
) -> Optional[Dict[str, Any]]:
    """Run the pipeline according to its mode.

    Returns the skip-outcome dict when the target node ended up skipped
    (missing upstream inputs) instead of running — ``None`` for a normal
    completion.
    """
    from ducta.stream.constants import PipelineType

    chain_kwargs: Dict[str, Any] = {
        "pipeline_name": spec.pipeline_name,
        "node_name": spec.node_name,
        "start_date": spec.start_date,
        "end_date": spec.end_date,
        "model_version": spec.model_version,
        "hyperparams": spec.hyperparams,
        "reuse_upstream": spec.reuse_upstream,
        "rerun_all": spec.rerun_all,
        "node_names": spec.node_names,
    }
    outcome: Optional[Dict[str, Any]] = None
    if spec.sanity_only:
        # Run node input sanity checks only — no pipeline execution.
        _run_sanity_checks(ctx, spec.pipeline_name)
    elif spec.dry_run:
        # Validate the pipeline exists and log its plan without executing.
        _log_dry_run(engine, spec)
    elif pipeline_type in (PipelineType.STREAMING.value, PipelineType.HYBRID.value):
        _gs = getattr(ctx, "global_config", {}) or {}
        _transform_modules = _gs.get("streaming_transform_modules") or []
        if isinstance(_transform_modules, str):
            _transform_modules = [_transform_modules]
        if _transform_modules:
            logger.info(
                "Registering streaming transforms from global_config: {}",
                _transform_modules,
            )
            engine.register_streaming_transforms(list(_transform_modules))

        # Force sync mode so the execution blocks the worker thread while queries are active
        engine.run_pipeline_chain(**chain_kwargs, execution_mode="sync")
    else:
        run_result = engine.run_pipeline_chain(**chain_kwargs)
        # Skipped nodes and a blocked quality gate both let
        # run_pipeline return instead of raising, so without this
        # a run that rejected or could not read its data was
        # recorded as a success. The classification lives on the
        # result itself, shared with the CLI's report_run_outcome.
        outcome = run_result.outcome() or outcome
    return outcome


def _attach_stream_alerts(
    engine: Any, source_path: Any, project_id: Any, env: str, pipeline_type: str = "streaming"
) -> None:
    """Send the project's ``alerts:`` for a stream's live events (failure, stall,
    quarantine) while it runs, not only when the run ends — a hybrid run's stream
    phase included."""
    from ducta_server.services.alerts import notify_stream_event

    try:
        executor = (
            engine.hybrid_executor if pipeline_type == "hybrid" else engine.streaming_executor
        )
        executor.event_listeners.append(
            lambda event: notify_stream_event(source_path, project_id, env, event)
        )
    except Exception as e:  # noqa: BLE001 - alerts are best effort
        logger.debug("Stream alerts not attached: {}", e)


def _link_certificate(ctx: Any, manager: Any, execution_id: str) -> None:
    """Attach the Run Certificate this run emitted, if any (best-effort).

    The executor facade stamps its run_id on the context, and what its ``retrain:``
    did (the web UI showed a retrain only in the log).
    """
    try:
        cert_run_id = get_context_value(ctx, RUN_ID_ATTR)
        if cert_run_id:
            manager.attach_certificate(execution_id, str(cert_run_id))
        retrain = get_context_value(ctx, RETRAIN_ATTR)
        if retrain:
            manager.attach_retrain(execution_id, retrain)
    except Exception as e:
        logger.debug("Could not attach certificate run_id: {}", e)


def _shutdown_engine(engine: Any, manager: Any, execution_id: str) -> None:
    """Unregister the active engine and shut it down (best-effort)."""
    manager.unregister_active_engine(execution_id)
    try:
        engine.shutdown()
    except Exception as e:
        logger.error(f"Error shutting down pipeline engine: {e}")


@dataclass(frozen=True)
class RunSpec:
    """What to run: everything a pipeline execution needs besides its id.

    Built once by ``ExecutionManager.execute`` and passed down whole, instead
    of threading the same dozen arguments positionally through each layer.
    """

    source_path: Path
    pipeline_name: str
    env: str
    node_name: Optional[str] = None
    dry_run: bool = False
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    model_version: Optional[str] = None
    hyperparams: Optional[Dict[str, Any]] = None
    sanity_only: bool = False
    reuse_upstream: bool = False
    rerun_all: bool = False
    project_id: Optional[str] = None
    #: Only these nodes of the pipeline (a scope); None for all of them.
    node_names: Optional[List[str]] = None
    #: A sample run: this many rows of each input, outputs to the scratch area.
    sample_rows: Optional[int] = None
    #: The run this one reproduces (``certificates/{run_id}/reproduce``): its
    #: outputs go to a reproduction folder, never to the real datasets.
    reproduce_of: Optional[str] = None
    #: Wait for an IDE debugger to attach before running (local only).
    debug: bool = False
    #: Data breakpoints: pause after each of these nodes until resumed.
    pause_after: Optional[List[str]] = None


def print_run_header(spec: RunSpec) -> None:
    """What a run's log starts with, in this process or a run's own."""
    logger.info("Starting Ducta pipeline execution")
    # The run log is what the engine prints: give it the CLI's reporter.
    from ducta.console.ux.reporter import ConsoleReporter
    from ducta.reporting import get_reporter, set_reporter

    if not isinstance(get_reporter(), ConsoleReporter):
        set_reporter(ConsoleReporter())
    try:
        from ducta.console.ux.rich_logger import print_execution_header

        print_execution_header(
            pipeline=spec.pipeline_name,
            env=spec.env,
            start_date=spec.start_date,
            end_date=spec.end_date,
            node=spec.node_name,
        )
    except Exception as exc:
        logger.debug("Failed to print execution header: {exc}", exc=exc)


def print_run_finished(outcome: Optional[Dict[str, Any]], pipeline_name: str) -> None:
    """What a run's log ends with when the pipeline returned (not raised)."""
    finished = (outcome or {}).get("status")
    try:
        from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

        console = RichLoggerManager.get_console()
        console.print()
        print_process_separator(
            "warning" if finished else "success",
            f"EXECUTION {str(finished).upper()}" if finished else "EXECUTION COMPLETED",
            f"Pipeline: {pipeline_name}",
            console,
        )
        console.print()
    except Exception:
        pass
    if finished:
        # gate_blocked / skipped: it finished, but did not do all its work.
        logger.warning("Ducta pipeline execution finished: {}", finished)
    else:
        logger.success("Ducta pipeline execution completed successfully")


def run_failure_message(pipeline_name: str, exc: BaseException) -> str:
    """The run's error message for an exception the engine did not already explain."""
    return f"Pipeline '{pipeline_name}' execution failed: {exc}"


def redirect_to_scratch(ctx: Any, env: str, rows: int, pipeline_name: Optional[str] = None) -> Path:
    """Make this run a sample run: each node reads the first *rows* rows of its
    inputs, and everything the run writes — outputs, quality reports, the run
    certificate, chain state — lands under ``<output>/<env>/.ducta/scratch``.

    So a sample run cannot overwrite a real dataset, and is never the "last
    successful run" staleness and "what changed" compare against.
    """
    from ducta.core.scratch import redirect_writes

    original = Path(str(getattr(ctx, "output_path", None) or ctx.global_config.get("output_path")))
    scratch = state.scratch_dir(original, env)
    ctx.sample_rows = rows
    redirect_writes(ctx, scratch, env, certificates=True, pipeline_name=pipeline_name)
    # Checks still run and report, but a sample is small by design: a gate such
    # as `row_count >= 350` would always block it. Warn instead of blocking.
    for node in (getattr(ctx, "nodes_config", None) or {}).values():
        if isinstance(node, dict):
            for block in _gate_blocks(node):
                for gate_key in ("quality_gate", "sanity_gate"):
                    gate = block.get(gate_key)
                    if isinstance(gate, dict):
                        block[gate_key] = {**gate, "behavior": "warn_only"}
    return scratch


def redirect_run_writes(ctx: Any, spec: "RunSpec") -> None:
    """Send a sample run's or a reproduction's writes away from the real datasets."""
    if spec.sample_rows:
        scratch = redirect_to_scratch(
            ctx, spec.env, int(spec.sample_rows), pipeline_name=spec.pipeline_name
        )
        logger.info(
            "Sample run: first {} rows of each input; outputs and evidence "
            "go to {} — the real datasets are not touched",
            spec.sample_rows,
            scratch,
        )
    elif spec.reproduce_of:
        from ducta.core.certificate import certificate_dir, load_certificate
        from ducta.core.scratch import pin_served_models, prepare_reproduction

        # Read before the run's paths move: it names the model versions to serve.
        cert_path = certificate_dir(ctx, spec.reproduce_of) / "certificate.json"
        cert = load_certificate(cert_path) if cert_path.is_file() else {}
        target = prepare_reproduction(
            ctx, spec.env, spec.reproduce_of, pipeline_name=spec.pipeline_name
        )
        pin_served_models(ctx, cert)
        logger.info(
            "Reproducing run {}: outputs go to {} — the real datasets are not touched",
            spec.reproduce_of,
            target,
        )


def _gate_blocks(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every check block of a node that may carry a ``quality_gate``."""
    blocks: List[Dict[str, Any]] = []
    for key in ("data_quality", "sanity_checks"):
        block = node.get(key)
        if isinstance(block, dict):
            blocks.append(block)
            per_input = block.get("inputs")
            if isinstance(per_input, dict):
                blocks += [b for b in per_input.values() if isinstance(b, dict)]
    return blocks


#: How long a debug run waits for an IDE to attach before running without one.
DEBUG_ATTACH_TIMEOUT_SECONDS = 300


def _run_debug_child(
    execution_id: str, spec: RunSpec, source_path: Path, manager: Any
) -> Optional[Dict[str, Any]]:
    """Run *spec* in a child process listening for a debugger; wait for it."""
    import dataclasses
    import json
    import subprocess
    import tempfile
    import time

    from ducta_server.services import debugger

    if not debugger.available():
        raise RuntimeError(
            "Debug run: debugpy is not installed where the API runs (pip install debugpy)"
        )
    port = debugger.free_port()
    manager.set_debug_port(execution_id, port)
    with tempfile.TemporaryDirectory(prefix="ducta-debug-") as tmp:
        spec_file = Path(tmp) / "spec.json"
        result_file = Path(tmp) / "result.json"
        payload = {**dataclasses.asdict(spec), "source_path": str(source_path)}
        spec_file.write_text(json.dumps(payload, default=str), encoding="utf-8")
        cmd = [
            sys.executable, "-X", "frozen_modules=off", "-m", "debugpy",
            "--listen", f"{debugger.HOST}:{port}", "--wait-for-client",
            "-m", "ducta_server.execution.debug_child", str(spec_file), str(result_file),
        ]  # fmt: skip
        # settrace, not sys.monitoring: under 3.12+ monitoring, a node run on an
        # executor thread stopped where pydevd could not find the thread again
        # (no variables, no evaluate).
        env = {
            **os.environ,
            "PYDEVD_DISABLE_FILE_VALIDATION": "1",
            "PYDEVD_USE_SYS_MONITORING": "0",
        }
        logger.info(
            "Debug run: waiting for a debugger on {}:{} — the browser's Debug panel, or "
            "'Attach to Ducta' in your IDE",
            debugger.HOST,
            port,
        )
        # stdout/stderr are inherited: they land in this run's captured logs.
        proc = subprocess.Popen(cmd, cwd=str(source_path), env=env)
        started = time.monotonic()
        try:
            while proc.poll() is None:
                if manager.is_cancelled(execution_id):
                    proc.terminate()
                    proc.wait(timeout=10)
                    raise RuntimeError("Debug run cancelled")
                if (
                    not manager.debug_attached(execution_id)
                    and time.monotonic() - started > DEBUG_ATTACH_TIMEOUT_SECONDS
                ):
                    proc.terminate()
                    proc.wait(timeout=10)
                    raise RuntimeError(f"No debugger attached in {DEBUG_ATTACH_TIMEOUT_SECONDS}s")
                time.sleep(0.3)
        finally:
            if proc.poll() is None:
                proc.kill()
        result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
    if result.get("certificate_run_id"):
        manager.attach_certificate(execution_id, str(result["certificate_run_id"]))
    if isinstance(result.get("retrain"), dict):
        manager.attach_retrain(execution_id, result["retrain"])
    if proc.returncode != 0:
        raise RuntimeError(result.get("error") or f"The debug run failed (exit {proc.returncode})")
    logger.success("Debug run finished")
    return result.get("outcome")


def run_pipeline_sync(
    execution_id: str,
    spec: RunSpec,
    manager: Any,  # ExecutionManager — typed as Any to avoid circular imports
) -> Optional[Dict[str, Any]]:
    """Execute a pipeline synchronously inside a dedicated thread.

    Returns a dict with the skip reason when the target node ended up skipped
    (missing upstream inputs) instead of running — ``None`` for a normal
    completion (success/dry-run/sanity-only).
    """
    from ducta_server.config import get_settings
    from ducta_server.execution.child_runner import isolation_mode, run_in_child
    from ducta_server.execution.context import execution_id_var

    execution_id_var.set(execution_id)
    timeout_handler = manager.get_or_create_timeout_handler(execution_id)

    # For multi-project workspaces (no top-level environment file), resolve the
    # effective project directory so context loading and CWD work correctly.
    pipeline_name, env = spec.pipeline_name, spec.env
    source_path = resolve_project_source(spec.source_path, pipeline_name)

    if not spec.debug and isolation_mode(get_settings()) == "process":
        # Its own process: no lock, no shared cwd, sys.path or file descriptors.
        return run_in_child(execution_id, spec, source_path, manager, timeout_handler)

    manager.set_active_execution(execution_id)
    ws_root_str = str(source_path)
    added_to_sys_path = False

    # NOTE: this lock serialises the *entire* pipeline body, not just the dup2
    # call, because os.dup2(1/2), os.chdir() and sys.path mutation below are all
    # process-global. As a result pipeline executions run strictly one-at-a-time
    # regardless of `max_concurrent_executions`; that setting only governs how
    # many runs may sit dequeued/active in the queue, not true parallelism.
    # RUN_ISOLATION=process (above) runs each pipeline in its own process instead.
    with _acquire_stdout_capture_lock(get_settings().execution_timeout_seconds):
        with ProcessOutputCapture(execution_id, manager):
            # Snapshot sys.modules under the lock so the baseline (and the later
            # cleanup) cannot race with another execution's imports.
            with _execution_module_isolation_scope(execution_id, manager):
                print_run_header(spec)

                if ws_root_str not in sys.path:
                    sys.path.insert(0, ws_root_str)
                    added_to_sys_path = True
                    logger.debug("Added source root to sys.path: {p}", p=ws_root_str)

                original_cwd = os.getcwd()
                try:
                    ctx, env_dir = _resolve_execution_context(
                        source_path, env, pipeline_name, timeout_handler
                    )

                    # Expose the pipeline name to runtime consumers. The streaming
                    # status / checkpoints / data endpoints read
                    # global_config["pipeline_name"] to scope their work to this
                    # pipeline; without it "Clear Checkpoints" 400s and the data
                    # preview falls back to every node in the workspace.
                    _gs = getattr(ctx, "global_config", None)
                    if isinstance(_gs, dict):
                        _gs["pipeline_name"] = pipeline_name
                        # Propagated into MLOps run tags so runs can be traced back
                        # to the owning project (execution is project-scoped, MLOps
                        # storage is workspace-scoped).
                        if spec.project_id:
                            _gs["project_id"] = spec.project_id
                        # The stream journal records it, so this execution's
                        # stream stays findable after the server restarts.
                        _gs["api_execution_id"] = execution_id

                    execution_cwd = select_execution_cwd(source_path, env_dir, ctx)
                    os.chdir(execution_cwd)
                    normalize_execution_context_paths(ctx, execution_cwd)
                    redirect_run_writes(ctx, spec)

                    if spec.debug:
                        # Its own process, under debugpy: a breakpoint there can
                        # stop every thread without stopping this server.
                        return _run_debug_child(execution_id, spec, source_path, manager)
                    if spec.pause_after:
                        # Read by the coordinator after each node succeeds.
                        ctx.pause_after = set(spec.pause_after)
                        ctx.breakpoint_hook = lambda node: manager.wait_at_breakpoint(
                            execution_id, node
                        )

                    if timeout_handler:
                        timeout_handler.verify()

                    from ducta.core.executors import PipelineExecutor
                    from ducta.stream.constants import PipelineType

                    engine = PipelineExecutor(ctx)
                    pipeline = engine.batch_executor.get_pipeline_config(pipeline_name)
                    pipeline_type = pipeline.get("type", PipelineType.BATCH.value)

                    manager.register_active_engine(execution_id, engine)
                    if pipeline_type in (PipelineType.STREAMING.value, PipelineType.HYBRID.value):
                        _attach_stream_alerts(
                            engine, source_path, spec.project_id, env, pipeline_type
                        )
                    # Terminal outcomes that do not raise. ``None`` means a clean run;
                    # otherwise ``{"status": ..., "node": ..., "reason": ...}``.
                    outcome: Optional[Dict[str, Any]] = None
                    try:
                        outcome = _dispatch_pipeline_type(engine, pipeline_type, spec, ctx)
                    finally:
                        _link_certificate(ctx, manager, execution_id)
                        _shutdown_engine(engine, manager, execution_id)

                    print_run_finished(outcome, pipeline_name)
                    return outcome
                except DuctaError:
                    # Engine errors already carry the pipeline, the failed nodes and
                    # an http_status. Re-wrapping them in a RuntimeError threw all of
                    # that away and left the caller with a string to parse.
                    raise
                except Exception as exc:
                    raise RuntimeError(run_failure_message(pipeline_name, exc)) from exc
                finally:
                    try:
                        os.chdir(original_cwd)
                    except OSError:
                        pass
                    if added_to_sys_path:
                        try:
                            sys.path.remove(ws_root_str)
                        except ValueError:
                            pass
                    manager.set_active_execution(None)
