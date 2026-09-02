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
from pathlib import Path
from typing import Any, Dict, List, Optional

TRIALS_DIRNAME = "_trials"
SHARED_PREFIX_DIRNAME = "_shared"


def trial_output_path(base_output_path: str, search_id: str, trial_index: int) -> str:
    """Private output directory for one trial."""
    return str(Path(base_output_path) / TRIALS_DIRNAME / search_id / f"trial_{trial_index}")


def shared_prefix_path(base_output_path: str, search_id: str) -> str:
    """Directory where trial 1 materializes the trial-invariant upstream
    prefix, read-only for every other trial in the same sweep/search."""
    return str(Path(base_output_path) / TRIALS_DIRNAME / search_id / SHARED_PREFIX_DIRNAME)


def run_trial_in_process(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one trial in this (worker) process and return a plain summary."""
    result: Dict[str, Any] = {
        "index": payload.get("trial_index"),
        "params": payload.get("params") or {},
        "metrics": {},
        "gate_blocked": [],
        "failed": False,
        "reason": None,
    }

    quiet = payload.get("quiet", True)
    devnull = None
    silence: Any = contextlib.ExitStack()
    if quiet:
        devnull = open(os.devnull, "w")
        silence.enter_context(contextlib.redirect_stdout(devnull))
        silence.enter_context(contextlib.redirect_stderr(devnull))

    try:
        with silence:
            from loguru import logger

            if quiet:
                logger.remove()

            from ducta.console.config import ConfigManager
            from ducta.console.execution import ContextInitializer
            from ducta.core import PipelineExecutor

            config_manager = ConfigManager(
                base_path=payload.get("base_path"),
                layer_name=payload.get("layer_name"),
                use_case=payload.get("use_case_name"),
                config_type=payload.get("config_type"),
                interactive=False,
                require_config=False,
            )
            config_manager.change_to_config_directory()
            context = ContextInitializer(config_manager).initialize(payload["env"])

            output_path = payload.get("output_path")
            if output_path:
                os.makedirs(output_path, exist_ok=True)
                context.output_path = output_path
                settings = getattr(context, "global_settings", None)
                if isinstance(settings, dict):
                    settings["output_path"] = output_path

            read_fallback_paths = payload.get("read_fallback_paths") or []
            if read_fallback_paths:
                context._read_fallback_paths = read_fallback_paths
                settings = getattr(context, "global_settings", None)
                if isinstance(settings, dict):
                    settings["_read_fallback_paths"] = read_fallback_paths

            exec_obj = PipelineExecutor(context, config_manager.get_config_directory())
            run = exec_obj.run_pipeline(
                pipeline_name=payload["pipeline"],
                node_name=payload.get("node"),
                start_date=payload.get("start_date"),
                end_date=payload.get("end_date"),
                model_version=payload.get("model_version"),
                hyperparams=payload.get("hyperparams") or {},
            )

            result["metrics"] = dict(getattr(run, "metrics", None) or {})
            result["gate_blocked"] = sorted((getattr(run, "gate_blocked", None) or {}).keys())
            if result["gate_blocked"]:
                result["failed"] = True
                result["reason"] = f"blocked by quality gate: {', '.join(result['gate_blocked'])}"

    except Exception as e:  # noqa: BLE001 — a worker must always answer
        result["failed"] = True
        result["reason"] = f"{type(e).__name__}: {e}"
    finally:
        if devnull is not None:
            devnull.close()

    return result


def build_payloads(
    trials: List[Dict[str, Any]],
    *,
    env: str,
    pipeline: str,
    search_id: str,
    base_output_path: Optional[str],
    base_path: Optional[str] = None,
    layer_name: Optional[str] = None,
    use_case_name: Optional[str] = None,
    config_type: Optional[str] = None,
    node: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    model_version: Optional[str] = None,
    read_fallback_paths: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Build one picklable payload per trial."""
    payloads = []
    for trial in trials:
        index = trial["index"]
        payloads.append(
            {
                "trial_index": index,
                "params": trial.get("params") or {},
                "hyperparams": trial.get("hyperparams") or {},
                "env": env,
                "pipeline": pipeline,
                "node": node,
                "start_date": start_date,
                "end_date": end_date,
                "model_version": model_version,
                "base_path": base_path,
                "layer_name": layer_name,
                "use_case_name": use_case_name,
                "config_type": config_type,
                "output_path": (
                    trial_output_path(base_output_path, search_id, index)
                    if base_output_path
                    else None
                ),
                "read_fallback_paths": list(read_fallback_paths or []),
                "quiet": True,
            }
        )
    return payloads
