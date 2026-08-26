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
from typing import Any, Dict, Optional

OUTCOME_SUCCESS = "success"
OUTCOME_GATE_BLOCKED = "gate_blocked"
OUTCOME_MISSING_DEPENDENCY = "missing_dependency"
OUTCOME_FAILED = "failed"


def run_node_in_process(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one node in this (worker) process and describe what happened.
    """
    outcome: Dict[str, Any] = {
        "node": payload.get("node_name"),
        "status": OUTCOME_FAILED,
        "error": None,
        "error_type": None,
        "node_trace": None,
    }

    devnull = None
    silence: Any = contextlib.ExitStack()
    if payload.get("quiet", True):
        devnull = open(os.devnull, "w")
        silence.enter_context(contextlib.redirect_stdout(devnull))
        silence.enter_context(contextlib.redirect_stderr(devnull))

    try:
        with silence:
            from ducta.check.core import QualityGateBlocked
            from ducta.console.config import ConfigManager
            from ducta.console.execution import ContextInitializer
            from ducta.core.execution.runner import NodeExecutor
            from ducta.core.ledger import ledger_for
            from ducta.gate.exceptions import MissingDependencyError
            from ducta.gate.input import InputLoader
            from ducta.gate.output import DataOutputManager

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
                context.output_path = output_path
                settings = getattr(context, "global_settings", None)
                if isinstance(settings, dict):
                    settings["output_path"] = output_path

            node_executor = NodeExecutor(
                context,
                InputLoader(context),
                DataOutputManager(context),
                max_workers=1,
            )
            node_executor.pipeline_name = payload.get("pipeline_name")

            try:
                node_executor.execute_single_node(
                    payload["node_name"],
                    payload.get("start_date"),
                    payload.get("end_date"),
                    payload.get("ml_info") or {},
                )
                outcome["status"] = OUTCOME_SUCCESS
            except QualityGateBlocked as e:
                outcome["status"] = OUTCOME_GATE_BLOCKED
                outcome["error"] = str(e)
                outcome["error_type"] = type(e).__name__
            except MissingDependencyError as e:
                outcome["status"] = OUTCOME_MISSING_DEPENDENCY
                outcome["error"] = str(e)
                outcome["error_type"] = type(e).__name__
            except Exception as e:  # noqa: BLE001 — reported, not propagated
                outcome["status"] = OUTCOME_FAILED
                outcome["error"] = str(e)
                outcome["error_type"] = type(e).__name__

            try:
                details = ledger_for(context).node_details or []
                outcome["node_trace"] = [
                    d for d in details if d.get("name") == payload["node_name"]
                ]
            except Exception:
                outcome["node_trace"] = None

    except Exception as e:  # noqa: BLE001 — a worker must always answer
        outcome["status"] = OUTCOME_FAILED
        outcome["error"] = f"{type(e).__name__}: {e}"
        outcome["error_type"] = type(e).__name__
    finally:
        if devnull is not None:
            devnull.close()

    return outcome


def build_node_payload(
    node_name: str,
    *,
    env: str,
    ml_info: Dict[str, Any],
    pipeline_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    base_path: Optional[str] = None,
    layer_name: Optional[str] = None,
    use_case_name: Optional[str] = None,
    config_type: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the picklable payload for one node run.
    """
    safe_ml_info = {
        key: value
        for key, value in (ml_info or {}).items()
        if key
        in {
            "hyperparams",
            "model_version",
            "seed",
            "split",
            "cv_folds",
            "pipeline_type",
            "project_name",
            "sweep_id",
            "sweep_index",
        }
    }
    return {
        "node_name": node_name,
        "pipeline_name": pipeline_name,
        "env": env,
        "ml_info": safe_ml_info,
        "start_date": start_date,
        "end_date": end_date,
        "base_path": base_path,
        "layer_name": layer_name,
        "use_case_name": use_case_name,
        "config_type": config_type,
        "output_path": output_path,
        "quiet": True,
    }
