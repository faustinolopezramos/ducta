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

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.gate.base import BaseIO
from ducta.gate.constants import SupportedFormats, WriteMode, is_cloud_path
from ducta.gate.exceptions import ConfigurationError, FormatNotSupportedError, WriteOperationError
from ducta.gate.factories import WriterFactory
from ducta.gate.output.dataframes import _DataFrameManager
from ducta.gate.output.paths import _newest_mtime, _PathManager, join_cloud_path, path_has_data
from ducta.gate.output.unity_catalog import UnityCatalogConfig, UnityCatalogManager
from ducta.gate.sql import UnityCatalogDDL
from ducta.gate.validators import DataValidator


def parse_iso_datetime(value: str) -> datetime:
    """Parse ISO datetime with proper error handling."""
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ConfigurationError(f"Invalid ISO-8601 date: '{value}'") from error


def validate_date_range(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Validate and parse date range."""
    start = parse_iso_datetime(start_date)
    end = parse_iso_datetime(end_date)
    if start > end:
        raise ConfigurationError("start_date must be <= end_date")
    return start, end


def _local_target_problem(path: Path) -> Optional[str]:
    """Why a local output path cannot be written, or None.

    Spark writes a dataset as a directory: an existing file in its place, or a
    parent that is a file or not writable, fails only once the write starts.
    """
    if path.exists() and not path.is_dir():
        return f"{path} is a file, not a dataset directory"
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir():
        return f"{probe} is not a directory, so {path} cannot be created"
    if not os.access(probe, os.W_OK | os.X_OK):
        return f"no permission to write in {probe}"
    return None


class DataOutputManager(BaseIO):
    """Simplified output manager with unified interface."""

    def __init__(self, context: Any):
        super().__init__(context)
        self.df_manager = _DataFrameManager(context)
        self.path_manager = _PathManager(context, self.config_validator)
        self.uc_manager = UnityCatalogManager(context)
        self.writer_factory = WriterFactory(context)
        self.data_validator = DataValidator()

    def is_output_materialized(self, out_key: str, env: Optional[str] = None) -> bool:
        """Return True if the output for *out_key* is already present on disk."""
        try:
            config = self._ctx_get("output_config", {}).get(out_key)
            if not config:
                return False
            if config.get("format") == SupportedFormats.UNITY_CATALOG.value:
                return False
            path = self.path_manager.resolve_output_path(config, out_key, env)
            if is_cloud_path(path):
                return False
            return path_has_data(path)
        except Exception as error:  # noqa: BLE001 — a failed check must never skip
            logger.debug("Materialization check failed for output '{}': {}", out_key, error)
            return False

    def output_mtime(self, out_key: str, env: Optional[str] = None) -> Optional[float]:
        """Newest modification time (epoch seconds) among an output's files."""
        try:
            config = self._ctx_get("output_config", {}).get(out_key)
            if not config or config.get("format") == SupportedFormats.UNITY_CATALOG.value:
                return None
            path = self.path_manager.resolve_output_path(config, out_key, env)
            if is_cloud_path(path):
                return None
            return _newest_mtime(Path(path))
        except Exception as error:  # noqa: BLE001 — a failed check must never skip
            logger.debug("Could not compute output mtime for '{}': {}", out_key, error)
            return None

    def _may_hold_data(self, out_key: str, config: Dict[str, Any], env: str) -> bool:
        """Whether writing an empty result to *out_key* could delete rows.

        Only a local path can be looked at; a table or a remote path is assumed
        to hold data.
        """
        if config.get("format") == SupportedFormats.UNITY_CATALOG.value:
            return True
        try:
            path = self.path_manager.resolve_output_path(config, out_key, env)
        except Exception:  # noqa: BLE001
            return True
        if is_cloud_path(path):
            return True
        # Not path_has_data: that counts only a completed write, and a dataset
        # written without a _SUCCESS marker still holds rows an overwrite deletes.
        target = Path(path)
        if target.is_file():
            return target.stat().st_size > 0
        return target.is_dir() and any(target.iterdir())

    def _output_keys_for_empty_result(
        self, output_keys: List[str], env: str, node_name: str, fail_on_error: bool
    ) -> List[str]:
        """Which of *output_keys* still get written when the node produced no rows.

        An overwrite of 0 rows would empty the dataset, so it is refused unless the
        dataset declares ``write: {allow_empty: true}`` or holds nothing yet. A write
        that does not replace the whole dataset has nothing to do and is skipped.
        """
        output_config = self._ctx_get("output_config", {}) or {}
        writable: List[str] = []
        refused: List[str] = []
        for out_key in output_keys:
            cfg = output_config.get(out_key, {}) or {}
            write_mode = cfg.get("write_mode", WriteMode.OVERWRITE.value)
            replaces_all = (
                getattr(write_mode, "value", write_mode) == WriteMode.OVERWRITE.value
                and str(cfg.get("partition_overwrite") or "static").lower() != "dynamic"
            )
            if not replaces_all:
                reason = (
                    f"output '{out_key}' not written: the node produced 0 rows and its write "
                    "does not replace the whole dataset (write_mode is not 'overwrite', or "
                    "partition_overwrite is 'dynamic'), so there was nothing to write and what "
                    "the dataset already holds stays"
                )
                logger.warning("{}.", reason)
                self._note_evidence_gap(reason)
            elif cfg.get("allow_empty") is True:
                logger.warning(
                    "Node produced 0 rows; writing the empty result to '{}' "
                    "(write.allow_empty is true, so the dataset is emptied).",
                    out_key,
                )
                writable.append(out_key)
            elif not self._may_hold_data(out_key, cfg, env):
                writable.append(out_key)
            else:
                refused.append(out_key)

        if refused:
            message = (
                f"Node '{node_name}' produced 0 rows, and overwriting {refused} with them "
                "would empty what they hold; nothing was written to them. If an empty "
                "result is valid for a dataset, set `write: {allow_empty: true}` on it; "
                "otherwise check the node's inputs and filters."
            )
            if fail_on_error:
                raise WriteOperationError(message)
            logger.error("{}", message)
            for out_key in refused:
                self._note_evidence_gap(
                    f"output '{out_key}' was not written (fail_on_error=false): the node "
                    "produced 0 rows and the dataset does not allow an empty result"
                )
        return writable

    def _unwritable_targets(self, output_keys: List[str], env: str) -> Dict[str, str]:
        """``{out_key: problem}`` for each output that cannot be written as configured.

        Checked before any output is written: a node with several outputs would
        otherwise write the first ones and then fail on a later one, leaving the
        datasets out of step with each other.
        """
        output_config = self._ctx_get("output_config", {}) or {}
        problems: Dict[str, str] = {}
        for out_key in output_keys:
            cfg = output_config.get(out_key)
            if not cfg:
                problems[out_key] = f"Output configuration '{out_key}' not found"
                continue
            format_name = str(getattr(cfg.get("format"), "value", cfg.get("format")) or "")
            if format_name.lower() == SupportedFormats.UNITY_CATALOG.value:
                if not self.uc_manager.is_enabled():
                    problems[out_key] = (
                        "format 'unity_catalog' needs a session with Unity Catalog "
                        "(mode: databricks); this session has none"
                    )
                continue
            if not self.writer_factory.supports(format_name):
                problems[out_key] = f"Unsupported format: '{format_name}'"
                continue
            try:
                path = self.path_manager.resolve_output_path(cfg, out_key, env)
            except Exception as error:  # noqa: BLE001
                problems[out_key] = str(error)
                continue
            if is_cloud_path(path) or "://" in path:
                continue
            problem = _local_target_problem(Path(path))
            if problem:
                problems[out_key] = problem
        return problems

    def save_output(
        self,
        env: str,
        node: Dict[str, Any],
        dataframe: Any,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> None:
        """Main entry point for saving output data."""
        if not self.df_manager.is_spark_dataframe(dataframe):
            dataframe = self.df_manager.convert_to_spark(dataframe)

        self.data_validator.validate_dataframe(dataframe, allow_empty=True)

        output_keys = self._get_output_keys(node)
        fail_on_error = self._ctx_get("global_config", {}).get("fail_on_error", True)

        if hasattr(dataframe, "isEmpty") and dataframe.isEmpty():
            output_keys = self._output_keys_for_empty_result(
                output_keys, env, str(node.get("name") or "?"), fail_on_error
            )
            if not output_keys:
                return

        # One output fails on its own write; several must all be writable before any
        # is written, or the first ones would hold this run's data and the rest not.
        problems = self._unwritable_targets(output_keys, env) if len(output_keys) > 1 else {}
        if problems:
            listed = "; ".join(f"'{key}': {why}" for key, why in problems.items())
            if fail_on_error:
                raise ConfigurationError(
                    f"Cannot write the node's outputs, so none was written — {listed}"
                )
            for key, why in problems.items():
                logger.error("Error saving output '{}': {}", key, why)
                self._note_evidence_gap(
                    f"output '{key}' was not written (fail_on_error=false): {why}"
                )
            output_keys = [key for key in output_keys if key not in problems]
            if not output_keys:
                return

        from ducta.gate import handoff

        persisted_here = False
        if (
            len(output_keys) > 1
            and hasattr(dataframe, "persist")
            and not handoff.is_enabled(self.context)
        ):
            try:
                dataframe.persist()
                persisted_here = True
            except Exception as error:
                logger.debug("Could not persist DataFrame for multi-output save: {}", error)

        try:
            written: List[str] = []
            for out_key in output_keys:
                try:
                    self._save_single_output(out_key, dataframe, start_date, end_date, env)
                    written.append(out_key)
                except Exception as error:
                    logger.error("Error saving output '{}': {}", out_key, error)
                    if written:
                        self._note_evidence_gap(
                            f"partial write: {written} already hold this run's data, but "
                            f"output '{out_key}' failed and does not"
                        )
                    if fail_on_error:
                        raise
                    self._note_evidence_gap(
                        f"output '{out_key}' was not written (fail_on_error=false): {error}"
                    )

        finally:
            if persisted_here:
                try:
                    dataframe.unpersist()
                except Exception:
                    pass

        if model_version:
            try:
                self._save_model_artifacts(node, model_version)
            except Exception as error:
                logger.error("Error saving model artifacts: {}", error)
                if fail_on_error:
                    raise
                self._note_evidence_gap(
                    f"model artifacts were not saved (fail_on_error=false): {error}"
                )

    def _save_single_output(
        self,
        out_key: str,
        dataframe: Any,
        start_date: Optional[str],
        end_date: Optional[str],
        env: str,
    ) -> None:
        """Save a single output configuration."""
        output_config = self._ctx_get("output_config", {}).get(out_key)
        if not output_config:
            raise ConfigurationError(f"Output configuration '{out_key}' not found")

        if (
            output_config.get("format") == SupportedFormats.UNITY_CATALOG.value
            and self.uc_manager.is_enabled()
        ):
            self._write_unity_catalog(dataframe, output_config, start_date, end_date, out_key, env)
        else:
            self._write_traditional(dataframe, output_config, out_key, env, start_date, end_date)

    def _write_unity_catalog(
        self,
        dataframe: Any,
        config: Dict[str, Any],
        start_date: Optional[str],
        end_date: Optional[str],
        out_key: str,
        env: str,
    ) -> None:
        """Write to Unity Catalog."""
        parsed = self.config_validator.validate_output_key(out_key)
        # `env` is spliced into the catalog, schema and table names below.
        env = self.config_validator.validate_path_segment(env, "environment")

        uc_config = UnityCatalogConfig.from_output_config(config, parsed, env)

        if config.get("overwrite_strategy", "").lower() == "replacewhere":
            if not (start_date and end_date):
                raise ConfigurationError("replaceWhere requires start_date and end_date")
            validate_date_range(start_date, end_date)
            if not uc_config.partition_col:
                raise ConfigurationError("replaceWhere requires partition_col (the date column)")
            uc_config.options["replaceWhere"] = UnityCatalogDDL.replace_where_clause(
                uc_config.partition_col, start_date, end_date
            )

        full_table_name = f"{uc_config.catalog_name}.{uc_config.schema}.{uc_config.table_name}"

        base_location = config.get("output_path") or self._ctx_get("output_path", "")
        self.uc_manager.ensure_schema_exists(
            uc_config.catalog_name,
            uc_config.schema,
            location=base_location or None,
            managed=uc_config.uc_table_mode == "managed",
        )

        start = time.time()
        try:
            if uc_config.uc_table_mode == "managed":
                self.uc_manager.write_managed_table(dataframe, full_table_name, uc_config)
            else:
                table_location = join_cloud_path(
                    base_location,
                    self.config_validator.validate_path_segment(env, "environment"),
                    parsed["schema"],
                    parsed.get("sub_folder", ""),
                    uc_config.table_name,
                )
                self.uc_manager.write_external_table(
                    dataframe, full_table_name, table_location, uc_config, self.writer_factory
                )

            logger.info("UC write completed in {:.2f}s", time.time() - start)

            self.uc_manager.post_write_operations(full_table_name, uc_config, start_date, end_date)

        except Exception as error:
            raise WriteOperationError(f"Unity Catalog write failed: {error}") from error

        self._record_output_fingerprint(out_key, full_table_name, dataframe, "delta")

    @staticmethod
    def _with_run_window(
        config: Dict[str, Any], start_date: Optional[str], end_date: Optional[str]
    ) -> Dict[str, Any]:
        """The output config with the run's window, for a ``replaceWhere`` that names none.

        ``overwrite_strategy: replaceWhere`` replaces the slice the run produced, so it needs
        the run's ``--start-date``/``--end-date``. They reached only the Unity Catalog branch;
        every other Delta output failed with "replaceWhere requires: start_date, end_date".
        A window written in the dataset itself wins.
        """
        if str(config.get("overwrite_strategy") or "").lower() != "replacewhere":
            return config
        if not (start_date and end_date):
            return config
        return {
            **config,
            "start_date": config.get("start_date") or start_date,
            "end_date": config.get("end_date") or end_date,
        }

    def _write_traditional(
        self,
        dataframe: Any,
        config: Dict[str, Any],
        out_key: str,
        env: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """Write to traditional storage."""
        path = self.path_manager.resolve_output_path(config, out_key, env)
        config = self._with_run_window(config, start_date, end_date)

        if not is_cloud_path(path):
            self._prepare_local_directory(path)

        format_name = config.get("format", "").lower()
        try:
            writer = self.writer_factory.get_writer(format_name)
        except FormatNotSupportedError as error:
            raise ConfigurationError(f"Unsupported format: '{format_name}'") from error

        start = time.time()
        writer.write(dataframe, path, config)
        logger.info("Write completed in {:.2f}s", time.time() - start)

        from ducta.gate import handoff

        handoff.offer(self.context, path, dataframe, config.get("write_mode"))

        self._record_output_fingerprint(out_key, path, dataframe, format_name)

    def _record_output_fingerprint(
        self, out_key: str, target: str, dataframe: Any, format_name: str
    ) -> None:
        """Fingerprint what this write wrote — the batch — at a cost proportional to it.

        The DataFrame is the node's cached output, so hashing it re-reads no
        table. Under ``fingerprint_mode: auto`` it is hashed in full (it is the
        batch, whatever the size of the table it landed in); the target's size
        is irrelevant here. For Delta, the commit this write produced — its
        version and ``operationMetrics`` (rows written, updated, deleted) — is
        recorded too, read from the transaction log.
        """
        configured = self._ctx_get("global_config", {}).get("fingerprint_mode")
        mode = None if configured and configured != "auto" else "exact"
        extra: Dict[str, Any] = {"scope": "written batch"}
        if format_name == "delta":
            from ducta.gate.fingerprinting import delta_last_operation

            commit = delta_last_operation(self._ctx_spark(), target)
            if commit is not None:
                extra["delta_commit"] = commit
        self._record_fingerprint(
            "output", out_key, target, dataframe, mode=mode, extra_details=extra
        )

    def _save_model_artifacts(self, node: Dict[str, Any], model_version: str) -> None:
        """Save model artifacts to registry."""
        registry_path = self._ctx_get("global_config", {}).get("model_registry_path")
        if not registry_path:
            logger.warning("Model registry path not configured")
            return

        registry_str = str(registry_path)
        if is_cloud_path(registry_str):
            logger.warning(
                "Cloud model registry paths are not supported for metadata JSON writes. "
                "Use a local path for model_registry_path. Skipping all artifacts."
            )
            return

        failed: List[str] = []
        for artifact in node.get("model_artifacts", []):
            if not (artifact and isinstance(artifact, dict) and artifact.get("name")):
                continue

            try:
                # artifact["name"] and model_version become path components
                # below — reject anything that could escape registry_str
                # (e.g. "../../etc") before they're used to build a path.
                self.config_validator.validate_name_component(artifact["name"], "artifact name")
                self.config_validator.validate_name_component(model_version, "model_version")

                artifact_path = Path(registry_str) / artifact["name"] / model_version
                artifact_path.mkdir(parents=True, exist_ok=True)

                metadata = {
                    "artifact": artifact["name"],
                    "version": model_version,
                    "node": node.get("name"),
                    "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }

                (artifact_path / "metadata.json").write_text(
                    json.dumps(metadata, indent=2), encoding="utf-8"
                )
                logger.info("Artifact '{}' saved to: {}", artifact["name"], artifact_path)

            except Exception as error:
                logger.error("Error saving artifact {}: {}", artifact.get("name", "unknown"), error)
                failed.append(f"{artifact.get('name', 'unknown')}: {error}")

        if failed:
            # One bad artifact does not stop the others, but the run does not read as clean.
            raise WriteOperationError("Could not save model artifact(s): " + "; ".join(failed))

    def _get_output_keys(self, node: Dict[str, Any]) -> List[str]:
        """Get and validate output keys from node."""
        output = node.get("output", [])
        if isinstance(output, str):
            output = [output]

        if not isinstance(output, list):
            raise ConfigurationError("node['output'] must be string or list of strings")

        seen, result = set(), []
        for key in output:
            if not isinstance(key, str) or not key.strip():
                raise ConfigurationError(f"Invalid output key: {key}")
            key = key.strip()
            if key not in seen:
                seen.add(key)
                result.append(key)

        return result
