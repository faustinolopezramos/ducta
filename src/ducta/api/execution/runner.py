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
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

from loguru import logger  # type: ignore

from ducta.api.execution.output_capture import ProcessOutputCapture

_stdout_capture_lock = threading.Lock()


@contextlib.contextmanager
def _acquire_stdout_capture_lock(timeout: float) -> Iterator[None]:
    """Acquire `_stdout_capture_lock` with a timeout instead of blocking forever.

    `Future.cancel()`/a timeout can't actually kill a running thread (same
    limitation already documented for `ducta.core.node_executor`), so a
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
    """Return True if *project_dir* contains the named pipeline."""
    from ducta.api.workspace.loaders import load_config_file

    _PIPE_EXTS = (".yaml", ".yml", ".toml", ".json")

    def _pipeline_in_file(path: Path) -> bool:
        try:
            data = load_config_file(path) or {}
            return pipeline_name in data
        except Exception:
            return False

    # Standard project: config/pipelines.* (including nested config dirs)
    config_dir = project_dir / "config"
    if config_dir.is_dir():
        for ext in _PIPE_EXTS:
            for candidate in config_dir.rglob(f"pipelines{ext}"):
                if _pipeline_in_file(candidate):
                    return True

    # Legacy layout: base/pipeline/pipelines.*
    for ext in _PIPE_EXTS:
        legacy = project_dir / "base" / "pipeline" / f"pipelines{ext}"
        if legacy.exists() and _pipeline_in_file(legacy):
            return True

    # Layered project: scan layers declared in ducta.yaml
    for ext in _PIPE_EXTS:
        ducta_file = project_dir / f"ducta{ext}"
        if not ducta_file.exists():
            continue
        try:
            ducta_cfg = load_config_file(ducta_file) or {}
            for _layer, layer_cfg in ducta_cfg.get("layers", {}).items():
                pipe_rel = layer_cfg.get("pipelines")
                if pipe_rel:
                    pipe_path = project_dir / pipe_rel
                    if pipe_path.exists() and _pipeline_in_file(pipe_path):
                        return True
        except Exception:
            pass

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
    _ENV_EXTS = (".yml", ".yaml", ".toml", ".json")

    # Single-project: has its own environment file or ducta.yaml — no lookup needed
    if any((source_path / f"environment{ext}").exists() for ext in _ENV_EXTS):
        return source_path
    if any((source_path / f"ducta{ext}").exists() for ext in _ENV_EXTS):
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
    if not raw_value or _looks_like_uri(raw_value):
        return value
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

    global_settings = getattr(ctx, "global_settings", None)
    if isinstance(global_settings, dict):
        for path_key in ("input_path", "output_path", "model_registry_path", "mlops_path"):
            value = global_settings.get(path_key)
            normalized = _absolutize_path_value(value, base_dir)
            if normalized is not None and normalized != value:
                global_settings[path_key] = normalized

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


def select_execution_cwd(source_path: Path, env_dir: Path, ctx: Any) -> Path:
    """Choose the best working directory for the execution.

    Prefers *source_path* when relative config paths resolve there; otherwise
    falls back to *env_dir* or *source_path*.
    """
    global_settings = getattr(ctx, "global_settings", {}) or {}
    candidate_paths = [
        global_settings.get("input_path"),
        global_settings.get("output_path"),
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


def _log_dry_run(
    engine: Any,
    pipeline_name: str,
    node_name: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> None:
    """Validate the pipeline and log its plan without executing (``--dry-run``)."""
    if not engine.validate_pipeline(pipeline_name):
        available = engine.list_pipelines()
        raise RuntimeError(
            f"Pipeline '{pipeline_name}' not found. Available: {', '.join(available) or 'none'}"
        )
    info = engine.get_pipeline_info(pipeline_name)
    raw_nodes = info.get("nodes", [])
    node_names = [n if isinstance(n, str) else (n.get("name") or "unknown") for n in raw_nodes]
    logger.info("DRY-RUN MODE: Pipeline '{}' will not be executed", pipeline_name)
    logger.info("  Nodes: {}", ", ".join(node_names) if node_names else "None")
    if node_name:
        logger.info("  Single node: {}", node_name)
    if start_date:
        logger.info("  Start date: {}", start_date)
    if end_date:
        logger.info("  End date: {}", end_date)
    logger.success("DRY-RUN completed — no execution performed")


def run_pipeline_sync(
    execution_id: str,
    source_path: Path,
    pipeline_name: str,
    env: str,
    node_name: Optional[str],
    dry_run: bool,
    start_date: Optional[str],
    end_date: Optional[str],
    manager: Any,  # ExecutionManager — typed as Any to avoid circular imports
    model_version: Optional[str] = None,
    hyperparams: Optional[dict] = None,
    sanity_only: bool = False,
    project_id: Optional[str] = None,
    reuse_upstream: bool = False,
    rerun_all: bool = False,
) -> Optional[Dict[str, Any]]:
    """Execute a pipeline synchronously inside a dedicated thread.

    Returns a dict with the skip reason when the target node ended up skipped
    (missing upstream inputs) instead of running — ``None`` for a normal
    completion (success/dry-run/sanity-only).
    """
    from ducta.api.execution.resilience_helpers import set_current_execution_id
    from ducta.api.workspace.manager import WorkspaceManager  # avoid circular at module level

    manager.set_active_execution(execution_id)
    set_current_execution_id(execution_id)

    timeout_handler = manager.get_or_create_timeout_handler(execution_id)

    # For multi-project workspaces (no top-level environment file), resolve the
    # effective project directory so context loading and CWD work correctly.
    source_path = resolve_project_source(source_path, pipeline_name)
    ws_root_str = str(source_path)
    added_to_sys_path = False
    added_layer_root_to_sys_path: Optional[str] = None

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
            manager._isolation_manager.snapshot_modules(execution_id)
            logger.info("Starting Ducta pipeline execution")
            try:
                from ducta.console.ux.rich_logger import print_execution_header

                print_execution_header(
                    pipeline=pipeline_name,
                    env=env,
                    start_date=start_date,
                    end_date=end_date,
                    node=node_name,
                )
            except Exception as exc:
                logger.debug("Failed to print execution header: {exc}", exc=exc)

            if ws_root_str not in sys.path:
                sys.path.insert(0, ws_root_str)
                added_to_sys_path = True
                logger.debug("Added source root to sys.path: {p}", p=ws_root_str)

            original_cwd = os.getcwd()
            try:
                env_dir = source_path / env if (source_path / env).is_dir() else source_path

                # Detect layered project (ducta.yaml) — bypass WorkspaceManager.load_context
                # which only understands environment.yaml-based layouts.
                _DUCTA_EXTS = (".yaml", ".yml", ".toml", ".json")
                ducta_file = next(
                    (
                        source_path / f"ducta{ext}"
                        for ext in _DUCTA_EXTS
                        if (source_path / f"ducta{ext}").exists()
                    ),
                    None,
                )
                if ducta_file is not None:
                    from ducta.setting import LayerContextBuilder, LayeredProjectDetector
                    from ducta.setting.contexts import Context as _Context

                    detector = LayeredProjectDetector(source_path)
                    matching_layers = detector.find_layers_for_pipeline(pipeline_name)
                    if not matching_layers:
                        raise RuntimeError(
                            f"Pipeline '{pipeline_name}' not found in any layer "
                            f"of layered project at '{source_path}'"
                        )
                    if len(matching_layers) > 1:
                        raise RuntimeError(
                            f"Pipeline '{pipeline_name}' is ambiguous: found in layers "
                            f"{matching_layers}. Use a unique pipeline name per layer."
                        )
                    layer_name = matching_layers[0]
                    context_args = LayerContextBuilder.build_context_args(detector, layer_name, env)
                    if context_args is None:
                        raise RuntimeError(
                            f"Cannot build context for layer '{layer_name}': "
                            "one or more config files are missing (input.yaml / output.yaml?)"
                        )
                    LayerContextBuilder.inject_sys_path(detector, layer_name)
                    # Insert layer root (e.g. bronze/) at the front of sys.path so
                    # 'import src.intl_results' resolves via the layer's bronze/src/
                    # (a proper package with __init__.py) before Python can cache
                    # ws_root/src/ as a namespace package and pollute sys.modules['src'].
                    _layer_cfg = detector.get_layer(layer_name)
                    if _layer_cfg is not None:
                        _layer_root = str((detector.project_root / _layer_cfg.path).resolve())
                        if _layer_root not in sys.path:
                            sys.path.insert(0, _layer_root)
                            added_layer_root_to_sys_path = _layer_root
                    ctx = _Context(
                        global_settings=context_args["global_settings"],
                        pipelines_config=context_args["pipelines_config"],
                        nodes_config=context_args["nodes_config"],
                        input_config=context_args["input_config"],
                        output_config=context_args["output_config"],
                        env=env,
                    )
                    # _config_file_path drives the node executor's module search-path
                    # derivation: parent dir (= layer root) + parent/src are added as
                    # fallback import paths. Use a sentinel path whose .parent IS the
                    # layer root rather than a config subdirectory inside it.
                    if added_layer_root_to_sys_path:
                        ctx._config_file_path = str(
                            Path(added_layer_root_to_sys_path) / "config.yaml"
                        )
                    else:
                        ctx._config_file_path = context_args["global_settings"]
                    ctx.env = env
                    if timeout_handler:
                        timeout_handler.verify()
                else:
                    workspace = WorkspaceManager(source_path)
                    if timeout_handler:
                        timeout_handler.verify()
                    try:
                        ctx = workspace.load_context(env)
                    except Exception as exc:
                        raise RuntimeError(
                            f"Failed to load context for env '{env}': {exc}"
                        ) from exc

                # Expose the pipeline name to runtime consumers. The streaming
                # status / checkpoints / data endpoints read
                # global_settings["pipeline_name"] to scope their work to this
                # pipeline; without it "Clear Checkpoints" 400s and the data
                # preview falls back to every node in the workspace.
                _gs = getattr(ctx, "global_settings", None)
                if isinstance(_gs, dict):
                    _gs["pipeline_name"] = pipeline_name
                    # Propagated into MLOps run tags so runs can be traced back
                    # to the owning project (execution is project-scoped, MLOps
                    # storage is workspace-scoped).
                    if project_id:
                        _gs["project_id"] = project_id

                execution_cwd = select_execution_cwd(source_path, env_dir, ctx)
                os.chdir(execution_cwd)
                normalize_execution_context_paths(ctx, execution_cwd)

                if timeout_handler:
                    timeout_handler.verify()

                from ducta.core.executor import PipelineExecutor
                from ducta.stream.constants import PipelineType

                engine = PipelineExecutor(ctx)
                pipeline = engine.batch_executor._get_pipeline_config(pipeline_name)
                pipeline_type = pipeline.get("type", PipelineType.BATCH.value)

                manager.register_active_engine(execution_id, engine)
                skip_info: Optional[Dict[str, Any]] = None
                try:
                    if sanity_only:
                        # Run node input sanity checks only — no pipeline execution.
                        _run_sanity_checks(ctx, pipeline_name)
                    elif dry_run:
                        # Validate the pipeline exists and log its plan without executing.
                        _log_dry_run(engine, pipeline_name, node_name, start_date, end_date)
                    elif pipeline_type in (PipelineType.STREAMING.value, PipelineType.HYBRID.value):
                        _gs = getattr(ctx, "global_settings", {}) or {}
                        _transform_modules = _gs.get("streaming_transform_modules") or []
                        if isinstance(_transform_modules, str):
                            _transform_modules = [_transform_modules]
                        if _transform_modules:
                            logger.info(
                                "Registering streaming transforms from global_settings: {}",
                                _transform_modules,
                            )
                            engine.register_streaming_transforms(list(_transform_modules))

                        # Force sync mode so the execution blocks the worker thread while queries are active
                        engine.run_pipeline_chain(
                            pipeline_name=pipeline_name,
                            node_name=node_name,
                            start_date=start_date,
                            end_date=end_date,
                            model_version=model_version,
                            hyperparams=hyperparams,
                            execution_mode="sync",
                            reuse_upstream=reuse_upstream,
                            rerun_all=rerun_all,
                        )
                    else:
                        engine.run_pipeline_chain(
                            pipeline_name=pipeline_name,
                            node_name=node_name,
                            start_date=start_date,
                            end_date=end_date,
                            model_version=model_version,
                            hyperparams=hyperparams,
                            reuse_upstream=reuse_upstream,
                            rerun_all=rerun_all,
                        )
                        # Only the batch path sets this (execute_single_node); read the
                        # private lazy-init'd attr directly so we don't instantiate a
                        # BatchExecutor for streaming/hybrid pipelines that never used one.
                        batch_executor = getattr(engine, "_batch_executor", None)
                        skip_info = getattr(batch_executor, "_skipped_atomic_node", None)
                finally:
                    # Link the Run Certificate this run emitted (the executor facade
                    # stamps its run_id on the context).
                    try:
                        cert_run_id = getattr(ctx, "_run_id", None)
                        if cert_run_id:
                            manager.attach_certificate(execution_id, str(cert_run_id))
                    except Exception as e:
                        logger.debug("Could not attach certificate run_id: {}", e)
                    manager.unregister_active_engine(execution_id)
                    try:
                        engine.shutdown()
                    except Exception as e:
                        logger.error(f"Error shutting down pipeline engine: {e}")

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
                return skip_info
            except Exception as exc:
                raise RuntimeError(f"Pipeline '{pipeline_name}' execution failed: {exc}") from exc
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
                if added_layer_root_to_sys_path:
                    try:
                        sys.path.remove(added_layer_root_to_sys_path)
                    except ValueError:
                        pass
                manager.set_active_execution(None)
                # Remove modules imported during this run while still holding the
                # execution-body lock, so no concurrent run can lose its imports.
                try:
                    removed = manager._isolation_manager.cleanup(execution_id)
                    logger.debug("Module cleanup: removed {count} modules", count=removed)
                except Exception as exc:
                    logger.debug("Module isolation cleanup failed: {exc}", exc=exc)
