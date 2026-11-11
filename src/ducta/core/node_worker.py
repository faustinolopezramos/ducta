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

from typing import Any, Dict, Optional

from ducta.core.worker_bootstrap import bootstrap_worker_context, silence_output

OUTCOME_SUCCESS = "success"
OUTCOME_GATE_BLOCKED = "gate_blocked"
OUTCOME_MISSING_DEPENDENCY = "missing_dependency"
OUTCOME_FAILED = "failed"


def run_node_in_process(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one node in this (worker) process and describe what happened."""
    outcome: Dict[str, Any] = {
        "node": payload.get("node_name"),
        "status": OUTCOME_FAILED,
        "error": None,
        "error_type": None,
        "node_trace": None,
    }

    try:
        with silence_output(payload.get("quiet", True)):
            from ducta.check.core import QualityGateBlocked
            from ducta.core.execution.runner import NodeExecutor
            from ducta.core.ledger import ledger_for
            from ducta.gate.exceptions import MissingDependencyError
            from ducta.gate.input import InputLoader
            from ducta.gate.output import DataOutputManager

            _project_root, context = bootstrap_worker_context(payload)

            node_executor = NodeExecutor(
                context,
                InputLoader(context),
                DataOutputManager(context),
                max_workers=1,
            )
            node_executor.pipeline_name = payload.get("pipeline_name")
            # Run the node here: not in yet another worker process.
            node_executor.in_worker = True
            if (payload.get("ml_info") or {}).get("mlops_run_id"):
                node_executor.set_mlops_context(
                    _worker_mlops_context(context, payload.get("pipeline_name"))
                )

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
                # Plain values, so the parent can raise the same exception.
                outcome["gate"] = {
                    "dataset_name": e.dataset_name,
                    "run_id": e.run_id,
                    "gate_name": getattr(e.gate_result, "gate_name", "gate"),
                    "triggered_rules": list(getattr(e.gate_result, "triggered_rules", []) or []),
                }
            except MissingDependencyError as e:
                outcome["status"] = OUTCOME_MISSING_DEPENDENCY
                outcome["error"] = str(e)
                outcome["error_type"] = type(e).__name__
            except Exception as e:  # noqa: BLE001 — reported, not propagated
                outcome["status"] = OUTCOME_FAILED
                outcome["error"] = str(e)
                outcome["error_type"] = type(e).__name__

            try:
                ledger = ledger_for(context)
                details = ledger.node_details or []
                outcome["node_trace"] = [
                    d for d in details if d.get("name") == payload["node_name"]
                ]
                # Fingerprints, code hash, quality: the parent's certificate needs them.
                outcome["evidence"] = ledger.worker_evidence()
            except Exception:
                outcome["node_trace"] = None

    except Exception as e:  # noqa: BLE001 — a worker must always answer
        outcome["status"] = OUTCOME_FAILED
        outcome["error"] = f"{type(e).__name__}: {e}"
        outcome["error_type"] = type(e).__name__

    return outcome


def _worker_mlops_context(context: Any, pipeline_name: Optional[str]) -> Any:
    """The registry and tracker of the parent's run, rebuilt in the worker.

    The parent tracks the run (``mlops_run_id``); the worker had no MLOps context, so
    ``persist_model`` found no registry, wrote a local pickle and never registered
    or promoted the model. Built from the worker's Context, which carries the
    parent's ``mlops_path`` (a reproduction's scratch store included).
    """
    from ducta.mlrun.config import MLOpsContext

    mlops = MLOpsContext.from_context(context, pipeline_name=pipeline_name)
    if mlops is None or mlops.model_registry is None:
        raise RuntimeError(
            "the run is tracked, but this worker process could not open its model "
            "registry and experiment tracker"
        )
    return mlops


def build_node_payload(
    node_name: str,
    *,
    env: Optional[str],
    ml_info: Dict[str, Any],
    pipeline_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    base_path: Optional[str] = None,
    output_path: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the picklable payload for one node run.

    ``overrides`` is :func:`ducta.core.worker_bootstrap.capture_run_overrides` of the
    parent's Context: what the run changed after loading it.
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
            "pipeline_split",
            "split_source",
            "cli_hyperparams",
            "cli_model_version",
            "cv_folds",
            "pipeline_type",
            "project_name",
            "sweep_id",
            "sweep_index",
            # The parent's tracked run: the worker logs to it and registers in its
            # registry (a plain string; the integration object does not pickle).
            "mlops_run_id",
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
        "output_path": output_path,
        "overrides": overrides or {},
        "quiet": True,
    }


def run_node_in_child(payload: Dict[str, Any], conn: Any) -> None:
    """Entry point of a dedicated node process: run the node, send the outcome.

    One process per node (rather than a shared pool) is what lets a timed-out
    node be terminated: a pool worker cannot be killed without killing the
    pool, and every other node running in it.
    """
    try:
        conn.send(run_node_in_process(payload))
    finally:
        conn.close()
