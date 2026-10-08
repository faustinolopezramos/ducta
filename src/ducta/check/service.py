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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from ducta.check.storage import DEFAULT_PIPELINE_NAME

if TYPE_CHECKING:
    from ducta.check.storage import StorageBackend


def _resolve_storage(storage: "Optional[StorageBackend]", workspace: str) -> "StorageBackend":
    """Return *storage* unchanged, or a default ``FileStorageBackend`` for
    *workspace* when none was given. Shared by every read-path method below."""
    if storage is not None:
        return storage
    from ducta.check import FileStorageBackend

    return FileStorageBackend(workspace)


def _pandas_loader_for(format: str):
    """Return the pandas reader for *format*, or raise if unsupported.
    Shared by ``run_checks`` and ``profile``, which both load a standalone
    file the same way."""
    import pandas as pd  # type: ignore

    loaders = {
        "parquet": pd.read_parquet,
        "csv": pd.read_csv,
        "json": pd.read_json,
    }
    loader = loaders.get(format.lower())
    if loader is None:
        raise ValueError(f"Unsupported format '{format}'. Use parquet, csv, or json.")
    return loader


def _import_extensions(project_root: Path, modules: List[str]) -> None:
    """Import custom check modules, resolved from the project root as a run does."""
    import sys

    from ducta.check.core import load_quality_extensions

    entry = str(project_root.resolve())
    added = entry not in sys.path
    if added:
        sys.path.insert(0, entry)
    try:
        load_quality_extensions(modules)
    finally:
        if added:
            sys.path.remove(entry)


class QualityService:
    """Facade over the ducta.check engine for CLI consumption."""

    @staticmethod
    def list_checks() -> List[Dict[str, Any]]:
        """Return metadata for every registered quality check: what it is, what a
        failure counts as, and the parameters it takes."""
        from ducta.check import QUALITY_CHECKS_REGISTRY
        from ducta.check.params import schema_for

        result = []
        for name, cls in QUALITY_CHECKS_REGISTRY.items():
            module = cls.__module__ or ""
            origin = "built-in" if module.startswith("ducta.check") else module
            doc = (cls.__doc__ or "").strip().splitlines()
            try:
                severity = str(getattr(cls(), "severity", "") or "") or None
            except Exception:  # noqa: BLE001 — a check that needs arguments
                severity = None
            result.append(
                {
                    "name": name,
                    "class_name": cls.__name__,
                    "module": module,
                    "origin": origin,
                    "description": doc[0] if doc else None,
                    "default_severity": severity,
                    "params": schema_for(name, cls),
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
        from ducta.check import FileStorageBackend, ValidationPhaseRunner
        from ducta.setting.loaders import ConfigLoaderFactory

        df = _pandas_loader_for(format)(input_path)

        # A standalone checks file (YAML, JSON or TOML), not a project file.
        raw_config = ConfigLoaderFactory(allow_python=False).load_config(config_path) or {}
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
    def profile(
        input_path: str,
        format: str = "parquet",
        strictness: str = "balanced",
        sample_rows: Optional[int] = None,
        dataset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assay a local file and return its profile plus a proposed spec.

        Deliberately loads with pandas, exactly as :meth:`run_checks` does: the
        standalone path must work on a bare ``pip install ducta`` with no JVM,
        because its whole point is to be useful before anyone has adopted the
        framework.
        """
        from ducta.check.profiling import infer_spec, profile_dataset, spec_to_yaml

        df = _pandas_loader_for(format)(input_path)
        name = dataset_name or Path(input_path).stem
        profile = profile_dataset(df, dataset_name=name, sample_rows=sample_rows)
        spec = infer_spec(profile, strictness)

        return {
            "profile": profile.to_dict(),
            "spec": spec,
            "yaml": spec_to_yaml(profile, spec, strictness),
            "source": {
                "input_path": input_path,
                "format": format,
                "strictness": strictness,
                "sample_rows": sample_rows,
            },
        }

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
        storage = _resolve_storage(storage, workspace)
        effective_pipeline = pipeline_name or DEFAULT_PIPELINE_NAME
        run_ids = storage.list_reports(dataset, effective_pipeline)

        if all_reports:
            return {"status": "list", "run_ids": sorted(run_ids)}

        if not run_ids:
            return {
                "status": "no_reports",
                "message": f"No quality reports found for dataset '{dataset}' in '{workspace}'",
            }

        if run_id:
            target_run_id = run_id
        else:
            recent = storage.list_reports_by_recency(dataset, effective_pipeline)
            # list_reports_by_recency should never come back empty when
            # run_ids isn't, but fall back to the (arbitrary-order) alpha
            # sort rather than crash if a backend's mtime lookup fails.
            target_run_id = recent[0] if recent else sorted(run_ids)[-1]
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
        storage = _resolve_storage(storage, workspace)
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
        storage = _resolve_storage(storage, workspace)
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
        storage = _resolve_storage(storage, workspace)
        summary: List[Dict[str, Any]] = []
        for entry in storage.list_datasets(pipeline_name):
            if pipeline_name is not None:
                entry_pipeline, dataset = pipeline_name, entry
            else:
                entry_pipeline, _, dataset = entry.partition("/")
            # Ordered most-recent-first by file mtime, not lexicographically —
            # run_id is a random UUID fragment, not a sortable timestamp.
            run_ids = storage.list_reports_by_recency(dataset, entry_pipeline)
            latest: Optional[Dict[str, Any]] = None
            if run_ids:
                latest = storage.load_report(run_ids[0], dataset, entry_pipeline)
            trend = storage.load_score_trend(dataset, trend_n, entry_pipeline) or []
            summary.append(
                {
                    "dataset": entry,
                    "run_count": len(run_ids),
                    "latest_run_id": run_ids[0] if run_ids else None,
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
        project_root: Union[str, Path],
        env: Optional[str] = None,
        load_extensions: bool = True,
    ) -> Dict[str, Any]:
        """Validate a node's quality configuration without executing any checks.

        Reads the project at ``project_root`` as ``env`` sees it, so profile
        references resolve against that environment's ``settings.quality``.
        ``load_extensions`` imports the project's ``quality.extensions`` so
        custom checks are known; the API server passes False (it never imports
        workspace code), and an unregistered check is then only a warning.
        """
        from ducta.check import QUALITY_CHECKS_REGISTRY
        from ducta.setting.project_loader import compile_project, validate_project

        errors: List[str] = []
        warnings: List[str] = []

        root = Path(project_root)
        docs = compile_project(validate_project(root, None if env in (None, "base") else env))
        extensions = (docs["global_config"].get("quality") or {}).get("extensions") or []
        if extensions and load_extensions:
            _import_extensions(root, extensions)
        nodes = docs["nodes_config"]
        if node_name not in nodes:
            errors.append(f"Node '{node_name}' is not in the project")
            return {"valid": False, "errors": errors, "warnings": warnings}
        node_cfg = nodes[node_name]

        raw_profiles = (docs["global_config"].get("quality") or {}).get("profiles") or {}
        profiles = raw_profiles if isinstance(raw_profiles, dict) else {}

        # The blocks the engine runs for this node: `quality` on its output, and
        # each input's contract (catalog `checks` merged with `input_checks`).
        blocks: List[Tuple[str, Dict[str, Any]]] = [
            ("'quality'", node_cfg.get("data_quality") or {})
        ]
        sanity = node_cfg.get("sanity_checks") or {}
        if sanity.get("checks"):
            blocks.append(("input checks", sanity))
        for dataset, block in (sanity.get("inputs") or {}).items():
            blocks.append((f"checks on input '{dataset}'", block or {}))

        for origin, section in blocks:
            # A block without `enabled` runs, as in the engine.
            if not section or section.get("enabled", True) is False:
                continue
            profile_name = section.get("profile")
            if profile_name and profile_name not in profiles:
                # A run fails on an unknown profile (QualityConfigError), so it is an error.
                errors.append(
                    f"Profile '{profile_name}' used by {origin} is not defined in "
                    "settings.quality.profiles"
                )
            for check_name, check_cfg in (section.get("checks") or {}).items():
                if isinstance(check_cfg, dict) and not check_cfg.get("enabled", True):
                    continue
                if check_name in QUALITY_CHECKS_REGISTRY:
                    continue
                if extensions and not load_extensions:
                    warnings.append(
                        f"Check '{check_name}' ({origin}) is not built in; it may come from "
                        f"the project's quality.extensions, which were not imported here"
                    )
                else:
                    errors.append(
                        f"Unknown check '{check_name}' in node '{node_name}' ({origin}). "
                        f"Available: {sorted(QUALITY_CHECKS_REGISTRY)}"
                    )

        if not node_cfg.get("sanity_checks") and not node_cfg.get("data_quality"):
            warnings.append(f"Node '{node_name}' has no quality checks")

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
        storage = _resolve_storage(storage, workspace)
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
        storage = _resolve_storage(storage, workspace)

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
