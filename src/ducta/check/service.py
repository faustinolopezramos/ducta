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

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ducta.check.storage import DEFAULT_PIPELINE_NAME

if TYPE_CHECKING:
    from ducta.check.storage import StorageBackend


class QualityService:
    """Facade over the ducta.check engine for CLI consumption."""

    @staticmethod
    def list_checks() -> List[Dict[str, str]]:
        """Return metadata for every registered quality check."""
        from ducta.check import QUALITY_CHECKS_REGISTRY

        result = []
        for name, cls in QUALITY_CHECKS_REGISTRY.items():
            module = cls.__module__ or ""
            origin = "built-in" if module.startswith("ducta.check") else module
            result.append(
                {
                    "name": name,
                    "class_name": cls.__name__,
                    "module": module,
                    "origin": origin,
                }
            )
        return result

    @staticmethod
    def run_checks(
        input_path: str,
        format: str = "parquet",
        config_path: str = "",
        fail_fast: bool = False,
        workspace: str = ".",
        source_config_path: Optional[str] = None,
        source_checks: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run data-quality checks on a local file and return a report dict."""
        import pandas as pd  # type: ignore

        from ducta.check import FileStorageBackend, ValidationPhaseRunner
        from ducta.console.config import load_config_file

        # Load dataframe
        loaders = {
            "parquet": pd.read_parquet,
            "csv": pd.read_csv,
            "json": pd.read_json,
        }
        loader = loaders.get(format.lower())
        if loader is None:
            raise ValueError(f"Unsupported format '{format}'. Use parquet, csv, or json.")
        df = loader(input_path)

        # Load checks config
        raw_config = load_config_file(config_path)
        checks_config = raw_config.get("checks", raw_config)

        dataset_name = Path(input_path).stem
        runner = ValidationPhaseRunner(workspace_path=workspace, fail_fast=fail_fast)
        report = runner.run(
            dataset_name=dataset_name,
            df=df,
            config={"checks": checks_config},
        )
        report_dict = report.to_dict()
        report_dict["source"] = {
            "input_path": input_path,
            "format": format,
            "config_path": source_config_path,
            "checks": source_checks,
            "fail_fast": fail_fast,
        }
        if report.run_id:
            storage = (
                runner.storage
                if isinstance(runner.storage, FileStorageBackend)
                else (FileStorageBackend(workspace))
            )
            storage.save_report(report_dict, report.run_id, dataset_name)
        return report_dict

    @staticmethod
    def get_report(
        dataset: str,
        workspace: str = ".",
        run_id: Optional[str] = None,
        all_reports: bool = False,
        storage: "Optional[StorageBackend]" = None,
        pipeline_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load a stored quality report (or list available run IDs)."""
        if storage is None:
            from ducta.check import FileStorageBackend

            storage = FileStorageBackend(workspace)
        effective_pipeline = pipeline_name or DEFAULT_PIPELINE_NAME
        run_ids = storage.list_reports(dataset, effective_pipeline)

        if all_reports:
            return {"status": "list", "run_ids": sorted(run_ids)}

        if not run_ids:
            return {
                "status": "no_reports",
                "message": f"No quality reports found for dataset '{dataset}' in '{workspace}'",
            }

        target_run_id = run_id or sorted(run_ids)[-1]
        report = storage.load_report(target_run_id, dataset, effective_pipeline)
        if report is None:
            raise FileNotFoundError(f"Report '{target_run_id}' not found for dataset '{dataset}'")
        return report

    @staticmethod
    def delete_report(
        dataset: str,
        run_id: str,
        workspace: str = ".",
        storage: "Optional[StorageBackend]" = None,
        pipeline_name: Optional[str] = None,
    ) -> None:
        """Delete a stored quality report."""
        if storage is None:
            from ducta.check import FileStorageBackend

            storage = FileStorageBackend(workspace)
        if not storage.delete_report(run_id, dataset, pipeline_name or DEFAULT_PIPELINE_NAME):
            raise FileNotFoundError(f"Report '{run_id}' not found for dataset '{dataset}'")

    @staticmethod
    def list_datasets(
        workspace: str = ".",
        storage: "Optional[StorageBackend]" = None,
        pipeline_name: Optional[str] = None,
    ) -> List[str]:
        """List datasets with at least one stored quality report.

        With *pipeline_name* given, returns plain dataset names within that
        pipeline. Omitted, aggregates across every pipeline and returns
        ``"{pipeline_name}/{dataset_name}"`` qualified names.
        """
        if storage is None:
            from ducta.check import FileStorageBackend

            storage = FileStorageBackend(workspace)
        return storage.list_datasets(pipeline_name)

    @staticmethod
    def get_summary(
        workspace: str = ".",
        trend_n: int = 12,
        storage: "Optional[StorageBackend]" = None,
        pipeline_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Per-dataset overview: latest report status plus score trend.

        With *pipeline_name* omitted, aggregates across every pipeline —
        each summary entry's ``dataset`` is then the qualified
        ``"{pipeline_name}/{dataset_name}"`` name (see ``list_datasets``).
        """
        if storage is None:
            from ducta.check import FileStorageBackend

            storage = FileStorageBackend(workspace)
        summary: List[Dict[str, Any]] = []
        for entry in storage.list_datasets(pipeline_name):
            if pipeline_name is not None:
                entry_pipeline, dataset = pipeline_name, entry
            else:
                entry_pipeline, _, dataset = entry.partition("/")
            run_ids = sorted(storage.list_reports(dataset, entry_pipeline))
            latest: Optional[Dict[str, Any]] = None
            if run_ids:
                latest = storage.load_report(run_ids[-1], dataset, entry_pipeline)
            trend = storage.load_score_trend(dataset, trend_n, entry_pipeline) or []
            summary.append(
                {
                    "dataset": entry,
                    "run_count": len(run_ids),
                    "latest_run_id": run_ids[-1] if run_ids else None,
                    "latest_score": (latest or {}).get("score"),
                    "passed": (latest or {}).get("passed"),
                    "created_at": (latest or {}).get("created_at"),
                    "trend": [s.get("score") for s in trend if isinstance(s, dict)],
                }
            )
        return summary

    @staticmethod
    def validate_node_config(
        node_name: str,
        config_path: str,
        global_settings_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate quality config for a node without executing any checks."""
        from ducta.check import QUALITY_CHECKS_REGISTRY
        from ducta.console.config import load_config_file

        errors: List[str] = []
        warnings: List[str] = []

        # Load node config
        raw = load_config_file(config_path)
        nodes = raw.get("nodes", raw)
        if node_name not in nodes:
            errors.append(f"Node '{node_name}' not found in '{config_path}'")
            return {"valid": False, "errors": errors, "warnings": warnings}

        node_cfg = nodes[node_name]

        # Load profiles if global_settings provided
        profiles: Dict[str, Any] = {}
        if global_settings_path:
            try:
                gs = load_config_file(global_settings_path)
                raw_profiles = gs.get("quality", {}).get("profiles", {})
                profiles = raw_profiles if isinstance(raw_profiles, dict) else {}
            except Exception as exc:
                warnings.append(f"Could not load global_settings: {exc}")

        def _validate_checks_section(section_key: str) -> None:
            section = node_cfg.get(section_key, {})
            if not section.get("enabled", False):
                return

            profile_name = section.get("profile")
            if profile_name and profile_name not in profiles:
                warnings.append(
                    f"Profile '{profile_name}' referenced in {section_key} is not defined "
                    "in global_settings"
                )

            for check_name, check_cfg in section.get("checks", {}).items():
                if not isinstance(check_cfg, dict):
                    continue
                if not check_cfg.get("enabled", True):
                    continue
                if check_name not in QUALITY_CHECKS_REGISTRY:
                    errors.append(
                        f"Unknown check '{check_name}' in node '{node_name}' "
                        f"({section_key}). Available: {sorted(QUALITY_CHECKS_REGISTRY)}"
                    )

        _validate_checks_section("sanity_checks")
        _validate_checks_section("data_quality")

        if not node_cfg.get("sanity_checks") and not node_cfg.get("data_quality"):
            warnings.append(f"Node '{node_name}' has no 'sanity_checks' or 'data_quality' section")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    # ------------------------------------------------------------------ #
    # get_trend                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_trend(
        dataset: str,
        workspace: str = ".",
        last_n: int = 20,
        storage: "Optional[StorageBackend]" = None,
        pipeline_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the last N quality scores for a dataset."""
        if storage is None:
            from ducta.check import FileStorageBackend

            storage = FileStorageBackend(workspace)
        scores = storage.load_score_trend(dataset, last_n, pipeline_name or DEFAULT_PIPELINE_NAME)

        if not scores:
            return {
                "status": "no_trend",
                "message": f"No score history found for dataset '{dataset}' in '{workspace}'",
            }
        return {"dataset": dataset, "scores": scores}

    @staticmethod
    def get_score(
        run_id: str,
        workspace: str = ".",
        storage: "Optional[StorageBackend]" = None,
        pipeline_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the composite pipeline quality score for a given run.

        With *pipeline_name* omitted, aggregates the score across every
        pipeline that has a report for *run_id* (run ids are effectively
        unique per execution, so this stays unambiguous even without scoping).
        """
        if storage is None:
            # Check existence *before* constructing FileStorageBackend — its
            # __init__ creates '.quality' as a side effect (mkdir(exist_ok=True)),
            # which would make this guard never fire if checked afterwards.
            quality_dir = Path(workspace) / ".quality"
            if not quality_dir.exists():
                raise FileNotFoundError(f"No quality data found in workspace '{workspace}'")

            from ducta.check import FileStorageBackend

            storage = FileStorageBackend(workspace)

        node_scores: Dict[str, float] = {}
        gate_actions: Dict[str, str] = {}
        sanity_scores: List[float] = []
        dq_scores: List[float] = []

        for entry in storage.list_datasets(pipeline_name):
            if pipeline_name is not None:
                entry_pipeline, dataset_name = pipeline_name, entry
            else:
                entry_pipeline, _, dataset_name = entry.partition("/")
            report = storage.load_report(run_id, dataset_name, entry_pipeline)
            if report is None:
                continue

            score = float(report.get("score", 1.0))
            node_scores[entry] = score

            # Infer sanity vs dq from report_type field when available
            report_type = report.get("report_type", "")
            if report_type == "sanity":
                sanity_scores.append(score)
            else:
                dq_scores.append(score)

            # Gate action from stored gate result or derive from passed flag
            gate_result = storage.load_gate_result(run_id, dataset_name, entry_pipeline)
            if gate_result and "action" in gate_result:
                gate_actions[entry] = gate_result["action"]
            elif not report.get("passed", True):
                gate_actions[entry] = "block"
            else:
                gate_actions[entry] = "pass"

        if not node_scores:
            raise FileNotFoundError(
                f"No quality reports found for run_id '{run_id}' in workspace '{workspace}'"
            )

        all_scores = list(node_scores.values())
        health_index = sum(all_scores) / len(all_scores)
        sanity_score = sum(sanity_scores) / len(sanity_scores) if sanity_scores else 1.0
        dq_score = sum(dq_scores) / len(dq_scores) if dq_scores else 1.0
        nodes_blocked = [n for n, a in gate_actions.items() if a == "block"]

        return {
            "run_id": run_id,
            "health_index": round(health_index, 4),
            "sanity_score": round(sanity_score, 4),
            "dq_score": round(dq_score, 4),
            "nodes_blocked": nodes_blocked,
            "gate_actions": gate_actions,
        }
