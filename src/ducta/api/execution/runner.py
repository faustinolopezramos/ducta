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
from typing import Any, Dict, Iterable, Iterator, Optional

from loguru import logger  # type: ignore

from ducta.api.execution.output_capture import ProcessOutputCapture
from ducta.core.errors import DuctaError

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
    from ducta.api.exceptions import ExecutionError

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


# URI scheme prefixes that should never be treated as local paths
_URI_PREFIXES: tuple[str, ...] = (
    "s3://",
    "s3a://",
    "s3n://",
    "gs://",
    "abfss://",
    "abfs://",
    "dbfs:/",
    "file:/",
    "http://",
    "https://",
)


# ── Multi-project workspace helpers ──────────────────────────────────────────


def _project_owns_pipeline(project_dir: Path, pipeline_name: str) -> bool:
    """Whether the Ducta project in *project_dir* defines *pipeline_name*."""
    from ducta.setting.project_loader import find_project_root, read_project

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
    from ducta.setting.project_loader import find_project_root

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


def _looks_like_uri(value: str) -> bool:
    return value.strip().lower().startswith(_URI_PREFIXES)


def _absolutize_path_value(value: Any, base_dir: Path) -> Optional[str]:
    """Return an absolute string path for *value* resolved against *base_dir*.

    Returns *None* when *value* is not a string or is a URI.
    """
    if not isinstance(value, str):
        return None
    raw_value = value.strip()
    if not raw_value or _looks_like_uri(raw_value) or "${" in raw_value:
        return value  # a URI, or a placeholder resolved later
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return str(candidate)
    return str((base_dir / candidate).resolve())


def _normalize_nested_paths(value: Any, path_keys: set[str], base_dir: Path) -> Any:
    if isinstance(value, dict):
        for key, nested_value in list(value.items()):
            if key in path_keys:
                normalized = _absolutize_path_value(nested_value, base_dir)
                if normalized is not None:
                    value[key] = normalized
                    continue
            _normalize_nested_paths(nested_value, path_keys, base_dir)
        return value
    if isinstance(value, list):
        for item in value:
            _normalize_nested_paths(item, path_keys, base_dir)
    return value


def _normalize_config_mapping(
    config_mapping: Any,
    *,
    path_keys: Iterable[str],
    base_dir: Path,
) -> None:
    if not isinstance(config_mapping, dict):
        return
    path_key_set = set(path_keys)
    for config in config_mapping.values():
        _normalize_nested_paths(config, path_key_set, base_dir)


def normalize_execution_context_paths(ctx: Any, base_dir: Path) -> None:
    """Absolutise all relative filesystem paths in the execution *ctx*."""
    for path_attr in ("input_path", "output_path"):
        value = getattr(ctx, path_attr, None)
        normalized = _absolutize_path_value(value, base_dir)
        if normalized is not None and normalized != value:
            setattr(ctx, path_attr, normalized)

    global_config = getattr(ctx, "global_config", None)
    if isinstance(global_config, dict):
        for path_key in ("input_path", "output_path", "model_registry_path", "mlops_path"):
            value = global_config.get(path_key)
            normalized = _absolutize_path_value(value, base_dir)
            if normalized is not None and normalized != value:
                global_config[path_key] = normalized

    _normalize_config_mapping(
        getattr(ctx, "input_config", None),
        path_keys=("filepath", "path"),
        base_dir=base_dir,
    )
    _normalize_config_mapping(
        getattr(ctx, "output_config", None),
        path_keys=("filepath", "path", "checkpointLocation", "schemaLocation"),
        base_dir=base_dir,
    )
    # A stream node declares its source, sink and checkpoint inline rather than in
    # the catalog. Spark resolves a relative path against the JVM's working
    # directory, fixed when the server's first session started — so once the
    # server has run another project, `data/events` points into that one.
    nodes_config = getattr(ctx, "nodes_config", None)
    if isinstance(nodes_config, dict):
        _normalize_config_mapping(
            {
                name: node
                for name, node in nodes_config.items()
                if isinstance(node, dict) and node.get("type") == "streaming"
            },
            path_keys=(
                "path",
                "checkpoint_location",
                "checkpointLocation",
                "schemaLocation",
            ),
            base_dir=base_dir,
        )


def select_execution_cwd(source_path: Path, env_dir: Path, ctx: Any) -> Path:
    """Choose the best working directory for the execution.

    Prefers *source_path* when relative config paths resolve there; otherwise
    falls back to *env_dir* or *source_path*.
    """
    global_config = getattr(ctx, "global_config", {}) or {}
    candidate_paths = [
        global_config.get("input_path"),
        global_config.get("output_path"),
    ]
    relative_paths = [
        Path(str(v))
        for v in candidate_paths
        if isinstance(v, str) and v.strip() and not Path(str(v)).is_absolute()
    ]
    if not relative_paths:
        return source_path

    root_matches = sum(1 for p in relative_paths if (source_path / p).exists())
    env_matches = sum(1 for p in relative_paths if (env_dir / p).exists())

    if root_matches > 0 and root_matches >= env_matches:
        return source_path
    if env_matches > root_matches:
        return env_dir
    return source_path


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
    from ducta.api.workspace.manager import WorkspaceManager  # avoid circular at module level

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


def _link_certificate(ctx: Any, manager: Any, execution_id: str) -> None:
    """Attach the Run Certificate this run emitted, if any (best-effort).

    The executor facade stamps its run_id on the context.
    """
    try:
        cert_run_id = getattr(ctx, "_run_id", None)
        if cert_run_id:
            manager.attach_certificate(execution_id, str(cert_run_id))
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
    from ducta.api.execution.context import execution_id_var

    manager.set_active_execution(execution_id)
    execution_id_var.set(execution_id)

    timeout_handler = manager.get_or_create_timeout_handler(execution_id)

    # For multi-project workspaces (no top-level environment file), resolve the
    # effective project directory so context loading and CWD work correctly.
    pipeline_name, env = spec.pipeline_name, spec.env
    source_path = resolve_project_source(spec.source_path, pipeline_name)
    ws_root_str = str(source_path)
    added_to_sys_path = False

    # NOTE: this lock serialises the *entire* pipeline body, not just the dup2
    # call, because os.dup2(1/2), os.chdir() and sys.path mutation below are all
    # process-global. As a result pipeline executions run strictly one-at-a-time
    # regardless of `max_concurrent_executions`; that setting only governs how
    # many runs may sit dequeued/active in the queue, not true parallelism.
    # Real concurrency would require running each pipeline in its own subprocess.
    from ducta.api.config import get_settings

    with _acquire_stdout_capture_lock(get_settings().execution_timeout_seconds):
        with ProcessOutputCapture(execution_id, manager):
            # Snapshot sys.modules under the lock so the baseline (and the later
            # cleanup) cannot race with another execution's imports.
            with _execution_module_isolation_scope(execution_id, manager):
                logger.info("Starting Ducta pipeline execution")
                try:
                    from ducta.console.ux.rich_logger import print_execution_header

                    print_execution_header(
                        pipeline=pipeline_name,
                        env=env,
                        start_date=spec.start_date,
                        end_date=spec.end_date,
                        node=spec.node_name,
                    )
                except Exception as exc:
                    logger.debug("Failed to print execution header: {exc}", exc=exc)

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

                    execution_cwd = select_execution_cwd(source_path, env_dir, ctx)
                    os.chdir(execution_cwd)
                    normalize_execution_context_paths(ctx, execution_cwd)

                    if timeout_handler:
                        timeout_handler.verify()

                    from ducta.core.executors import PipelineExecutor
                    from ducta.stream.constants import PipelineType

                    engine = PipelineExecutor(ctx)
                    pipeline = engine.batch_executor._get_pipeline_config(pipeline_name)
                    pipeline_type = pipeline.get("type", PipelineType.BATCH.value)

                    manager.register_active_engine(execution_id, engine)
                    # Terminal outcomes that do not raise. ``None`` means a clean run;
                    # otherwise ``{"status": ..., "node": ..., "reason": ...}``.
                    outcome: Optional[Dict[str, Any]] = None
                    try:
                        outcome = _dispatch_pipeline_type(engine, pipeline_type, spec, ctx)
                    finally:
                        _link_certificate(ctx, manager, execution_id)
                        _shutdown_engine(engine, manager, execution_id)

                    try:
                        from ducta.console.ux.rich_logger import (
                            RichLoggerManager,
                            print_process_separator,
                        )

                        console = RichLoggerManager.get_console()
                        console.print()
                        print_process_separator(
                            "success", "EXECUTION COMPLETED", f"Pipeline: {pipeline_name}", console
                        )
                        console.print()
                    except Exception:
                        pass

                    logger.success("Ducta pipeline execution completed successfully")
                    return outcome
                except DuctaError:
                    # Engine errors already carry the pipeline, the failed nodes and
                    # an http_status. Re-wrapping them in a RuntimeError threw all of
                    # that away and left the caller with a string to parse.
                    raise
                except Exception as exc:
                    raise RuntimeError(
                        f"Pipeline '{pipeline_name}' execution failed: {exc}"
                    ) from exc
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
