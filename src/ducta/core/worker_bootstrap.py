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

Shared bootstrap for the ``node_worker.py`` / ``sweep_worker.py``
multiprocessing entry points: both build an isolated pipeline ``Context`` in
a fresh worker process, from a picklable payload dict, optionally silencing
stdout/stderr. Extracted because both previously carried independent
~25-line copies of this exact sequence.
"""

from __future__ import annotations

import contextlib
import copy
import os
from pathlib import Path
from typing import Any, Dict, Tuple


@contextlib.contextmanager
def silence_output(quiet: bool):
    """Redirect stdout/stderr to ``os.devnull`` for the block's duration, when *quiet*."""
    if not quiet:
        yield
        return
    with open(os.devnull, "w") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            yield


def capture_run_overrides(context: Any) -> Dict[str, Any]:
    """What the parent run changed on its Context after loading it, as plain values.

    A worker process rebuilds its Context from the project files, so anything a run
    adjusted afterwards (a sample run's scratch redirection above all) has to travel
    with the payload, or the worker would write the real datasets and read every row.
    """
    settings = getattr(context, "global_config", None)
    settings = settings if isinstance(settings, dict) else {}
    global_config = {
        key: copy.deepcopy(settings[key])
        # mlops_path: a reproduction's (and a sample run's) registry and tracker are a
        # scratch store; without it a worker registered and promoted in the real one.
        for key in ("output_path", "run_certificate_dir", "chain", "mlops_path")
        if key in settings
    }
    quality = settings.get("quality")
    if isinstance(quality, dict) and isinstance(quality.get("output"), dict):
        global_config["quality_output"] = copy.deepcopy(quality["output"])
    outputs = getattr(context, "output_config", None) or {}
    inputs = getattr(context, "input_config", None) or {}
    return {
        "sample_rows": getattr(context, "sample_rows", None),
        "reproduction_of": getattr(context, "reproduction_of", None),
        # Where a reproduction's serving nodes read their models, and which versions.
        "serving_mlops_path": getattr(context, "serving_mlops_path", None),
        "pinned_models": dict(getattr(context, "pinned_models", None) or {}),
        "allow_python_config": bool(getattr(context, "allow_python_config", True)),
        "global_config": global_config,
        "output_filepaths": {
            key: cfg["filepath"]
            for key, cfg in outputs.items()
            if isinstance(cfg, dict) and cfg.get("filepath")
        },
        # A sample run or a reproduction reads what it wrote itself (redirect_writes
        # repoints the inputs), and the real data where it wrote nothing: without
        # these a worker read the real datasets.
        "input_filepaths": {
            key: cfg["filepath"]
            for key, cfg in inputs.items()
            if isinstance(cfg, dict) and cfg.get("filepath")
        },
        "read_fallback_paths": list(getattr(context, "_read_fallback_paths", None) or []),
    }


def apply_run_overrides(context: Any, overrides: Dict[str, Any]) -> None:
    """Re-apply :func:`capture_run_overrides` on a worker's freshly loaded Context."""
    if not overrides:
        return
    if overrides.get("sample_rows"):
        context.sample_rows = overrides["sample_rows"]
    if overrides.get("serving_mlops_path"):
        context.serving_mlops_path = overrides["serving_mlops_path"]
    if overrides.get("pinned_models"):
        context.pinned_models = dict(overrides["pinned_models"])
    if overrides.get("reproduction_of"):
        context.reproduction_of = overrides["reproduction_of"]
    settings = getattr(context, "global_config", None)
    if isinstance(settings, dict):
        captured = dict(overrides.get("global_config") or {})
        quality_output = captured.pop("quality_output", None)
        settings.update(captured)
        if quality_output is not None and isinstance(settings.get("quality"), dict):
            settings["quality"]["output"] = quality_output
    outputs = getattr(context, "output_config", None) or {}
    for key, filepath in (overrides.get("output_filepaths") or {}).items():
        if isinstance(outputs.get(key), dict):
            outputs[key]["filepath"] = filepath
    inputs = getattr(context, "input_config", None) or {}
    for key, filepath in (overrides.get("input_filepaths") or {}).items():
        if isinstance(inputs.get(key), dict):
            inputs[key]["filepath"] = filepath
    fallbacks = list(overrides.get("read_fallback_paths") or [])
    if fallbacks:
        context._read_fallback_paths = fallbacks
        if isinstance(settings, dict):
            settings["_read_fallback_paths"] = fallbacks


def bootstrap_worker_context(
    payload: Dict[str, Any], *, ensure_output_dir: bool = False
) -> Tuple[Path, Any]:
    """Build a ``(project_root, context)`` pair for a worker-process payload."""
    from ducta.setting.project.context import load_project_context

    overrides = payload.get("overrides") or {}
    project_root, context = load_project_context(
        payload.get("base_path"),
        payload["env"],
        chdir=True,
        allow_python_config=overrides.get("allow_python_config", True),
    )
    apply_run_overrides(context, overrides)

    output_path = payload.get("output_path")
    if output_path:
        if ensure_output_dir:
            os.makedirs(output_path, exist_ok=True)
        context.output_path = output_path
        settings = getattr(context, "global_config", None)
        if isinstance(settings, dict):
            settings["output_path"] = output_path

    return project_root, context
