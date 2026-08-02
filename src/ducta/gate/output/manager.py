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
from ducta.gate.output.paths import _newest_mtime, _PathManager, join_cloud_path
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


class DataOutputManager(BaseIO):
    """Simplified output manager with unified interface."""

    def __init__(self, context: Dict[str, Any]):
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
            return self._path_has_data(path)
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

    @staticmethod
    def _path_has_data(path: str) -> bool:
        """True if *path* holds a completed write (file, or non-empty dir)."""
        p = Path(path)
        if not p.exists():
            return False
        if p.is_file():
            return p.stat().st_size > 0
        if p.is_dir():
            entries = list(p.iterdir())
            if not entries:
                return False
            has_part_files = any(e.name.startswith("part-") for e in entries)
            if has_part_files:
                if (p / "_SUCCESS").exists():
                    return True
                delta_log = p / "_delta_log"
                return delta_log.is_dir() and any(delta_log.iterdir())
            return True
        return False

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

        if hasattr(dataframe, "isEmpty") and dataframe.isEmpty():
            logger.warning("Empty DataFrame, skipping write")
            return

        output_keys = self._get_output_keys(node)
        fail_on_error = self._ctx_get("global_settings", {}).get("fail_on_error", True)

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
            for out_key in output_keys:
                try:
                    self._save_single_output(out_key, dataframe, start_date, end_date, env)
                except Exception as error:
                    logger.error("Error saving output '{}': {}", out_key, error)
                    if fail_on_error:
                        raise

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
            self._write_traditional(dataframe, output_config, out_key, env)

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

        uc_config = UnityCatalogConfig(
            catalog_name=config["catalog_name"].format(environment=env),
            schema=config.get("schema", parsed["schema"]).format(environment=env),
            table_name=config.get("table_name", parsed["table_name"]).format(environment=env),
            uc_table_mode=config.get("uc_table_mode", "external"),
            write_mode=config.get("write_mode", WriteMode.OVERWRITE.value),
            overwrite_schema=config.get("overwrite_schema", True),
            partition_col=config.get("partition_col"),
            description=config.get("description"),
            optimize=config.get("optimize", True),
            vacuum=config.get("vacuum", False),
            vacuum_retention_hours=config.get("vacuum_retention_hours"),
            options=config.get("options", {}),
        )

        if config.get("overwrite_strategy", "").lower() == "replacewhere":
            if not (start_date and end_date):
                raise ConfigurationError("replaceWhere requires start_date and end_date")
            validate_date_range(start_date, end_date)
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
                    env,
                    parsed.get("schema"),
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

        self._record_fingerprint("output", out_key, full_table_name, dataframe)

    def _write_traditional(
        self, dataframe: Any, config: Dict[str, Any], out_key: str, env: Optional[str] = None
    ) -> None:
        """Write to traditional storage."""
        path = self.path_manager.resolve_output_path(config, out_key, env)

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

        self._record_fingerprint("output", out_key, path, dataframe)

    def _save_model_artifacts(self, node: Dict[str, Any], model_version: str) -> None:
        """Save model artifacts to registry."""
        registry_path = self._ctx_get("global_settings", {}).get("model_registry_path")
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

        for artifact in node.get("model_artifacts", []):
            if not (artifact and isinstance(artifact, dict) and artifact.get("name")):
                continue

            try:
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
