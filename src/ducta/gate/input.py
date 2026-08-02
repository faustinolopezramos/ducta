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
from typing import Any, Dict, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.gate.base import BaseIO
from ducta.gate.concurrency import run_parallel
from ducta.gate.constants import is_cloud_path
from ducta.gate.exceptions import ConfigurationError, MissingDependencyError, ReadOperationError
from ducta.gate.factories import ReaderFactory


class InputLoader(BaseIO):
    """Unified InputLoader with parallel loading strategy."""

    def __init__(self, context: Dict[str, Any]):
        """Initialize the InputLoader."""
        super().__init__(context)
        self.reader_factory = ReaderFactory(context)
        self._register_custom_formats()

    def load_inputs(self, node: Dict[str, Any]) -> List[Any]:
        """Load all inputs defined for a processing node."""
        input_keys = self._get_input_keys(node)
        if not input_keys:
            node_name = node.get("name", "unnamed")
            logger.warning("Node '{}' has no defined inputs", node_name)
            return []

        fail_fast = node.get("fail_fast", True)
        if fail_fast:
            available, missing = self._inputs_available(node)
            if not available:
                node_name = node.get("name", "unnamed")
                raise MissingDependencyError(
                    f"Node '{node_name}' has missing input(s): {', '.join(missing)}"
                )

        return self._load_inputs_parallel(input_keys, fail_fast)

    def _inputs_available(self, node: Dict[str, Any]) -> "tuple[bool, List[str]]":
        """Check whether every declared input for *node* currently resolves."""
        missing: List[str] = []
        for input_key in self._get_input_keys(node):
            try:
                config = self._get_dataset_config(input_key)
                if config.get("format", "").lower() == "query":
                    continue
                self._get_filepath(config, input_key)
            except ConfigurationError:
                missing.append(input_key)
        return (not missing, missing)

    def max_input_mtime(self, node: Dict[str, Any]) -> Optional[float]:
        """Newest modification time (epoch seconds) across a node's file inputs."""
        from ducta.gate.output import _newest_mtime

        newest: Optional[float] = None
        for input_key in self._get_input_keys(node):
            try:
                config = self._get_dataset_config(input_key)
                if config.get("format", "").lower() == "query":
                    continue
                path = self._get_filepath(config, input_key)
                if is_cloud_path(path):
                    continue
                mtime = _newest_mtime(Path(path))
                if mtime is not None and (newest is None or mtime > newest):
                    newest = mtime
            except ConfigurationError:
                continue
        return newest

    def _load_inputs_parallel(self, input_keys: List[str], fail_fast: bool = True) -> List[Any]:
        """Load datasets in parallel, preserving input order."""
        fill_none = bool(
            self.context_manager.get_nested("global_settings.fill_none_on_error", False)
        )
        max_workers = self.context_manager.get_nested(
            "global_settings.max_input_workers", min(len(input_keys), 4)
        )

        self._print_loading_message(len(input_keys))

        outcome = run_parallel(
            input_keys, self._load_single_dataset, max_workers=max_workers, fail_fast=fail_fast
        )

        if fail_fast and outcome.errors:
            idx, error = outcome.errors[0]
            key = input_keys[idx]
            logger.exception("Error loading dataset '{}': {}", key, error)
            raise ReadOperationError(f"Error loading dataset '{key}': {error}") from error

        results = outcome.results
        errors: List[str] = []
        for idx, error in outcome.errors:
            key = input_keys[idx]
            logger.exception("Error loading dataset '{}': {}", key, error)
            errors.append(f"Error loading dataset '{key}': {error}")
            results[idx] = None

        if errors:
            if not fill_none:
                raise ReadOperationError(
                    f"{len(errors)} dataset(s) failed to load: {'; '.join(errors)}. "
                    "Set global_settings.fill_none_on_error=true to receive None "
                    "placeholders instead of aborting."
                )
            logger.warning("Completed loading with {} errors: {}", len(errors), errors)

        logger.info("Successfully loaded {} datasets", len(results) - len(errors))
        return results

    def _print_loading_message(self, dataset_count: int) -> None:
        """Print data loading message via progress_reporter if provided in context."""
        reporter = self._ctx_get("progress_reporter", None)
        if reporter and hasattr(reporter, "report_loading"):
            try:
                reporter.report_loading(dataset_count)
                return
            except Exception:
                pass
        logger.info("Loading {} datasets", dataset_count)

    def _load_single_dataset(self, input_key: str) -> Any:
        """Load a single dataset with proper error handling."""
        config = self._get_dataset_config(input_key)
        format_name = config.get("format", "").lower()

        if not format_name:
            raise ReadOperationError(f"Format not specified for dataset '{input_key}'") from None

        reader = self.reader_factory.get_reader(format_name)

        if format_name == "query":
            return reader.read("", config)
        filepath = self._get_filepath(config, input_key)

        from ducta.gate import handoff

        cached = handoff.take(self.context, filepath)
        if cached is not None:
            return cached

        dataframe = reader.read(filepath, config)

        data_fingerprint = self._record_fingerprint("input", input_key, filepath, dataframe)
        if data_fingerprint is not None:
            self._enforce_fingerprint_policy(input_key, data_fingerprint)

        return dataframe

    def _enforce_fingerprint_policy(self, input_key: str, data_fingerprint) -> None:
        """Apply fingerprint_policy against the previous successful run."""
        message = None
        try:
            policy = self.context_manager.get_nested("global_settings.fingerprint_policy", "record")

            if policy not in ("warn", "fail"):
                return

            previous_all = self._ctx_get("_previous_input_fingerprints", None) or {}
            previous = previous_all.get(input_key) or {}
            previous_hash = previous.get("fingerprint")
            if not previous_hash or previous_hash == data_fingerprint.fingerprint:
                return

            message = (
                f"Input '{input_key}' changed since the previous successful run: "
                f"fingerprint {previous_hash[:12]}… → {data_fingerprint.fingerprint[:12]}… "
                f"(rows {previous.get('row_count')} → {data_fingerprint.row_count}, "
                f"mtime {previous.get('file_mtime')} → {data_fingerprint.file_mtime})"
            )
            from ducta.gate.fingerprinting import diff_schema_columns

            column_diff = diff_schema_columns(
                previous.get("columns"), getattr(data_fingerprint, "columns", None)
            )
            if column_diff:
                message += f" | schema drift: {column_diff}"
        except Exception as error:
            logger.debug("Fingerprint policy check skipped for '{}': {}", input_key, error)
            return

        if policy == "fail":
            raise ReadOperationError(
                f"{message}. Aborting because fingerprint_policy=fail. "
                "Re-run with fingerprint_policy=warn (or record) to accept the new data."
            )
        logger.warning("{}. Results may not be comparable to the previous run.", message)

    def _get_dataset_config(self, input_key: str) -> Dict[str, Any]:
        """Get configuration for a dataset with validation."""
        input_cfg = self._ctx_get("input_config", {}) or {}
        config = input_cfg.get(input_key)

        if not config:
            raise ConfigurationError(f"Missing configuration for dataset '{input_key}'") from None

        if not isinstance(config, dict):
            raise ConfigurationError(
                f"Invalid configuration format for dataset '{input_key}': expected dict, got {type(config)}"
            ) from None
        return config

    def _get_filepath(self, config: Dict[str, Any], input_key: str) -> str:
        """Get filepath for a dataset, supporting glob patterns in local mode."""
        path = config.get("filepath")
        if not path:
            raise ConfigurationError(f"Missing filepath for dataset '{input_key}'") from None

        if is_cloud_path(path):
            return str(path)

        if self._is_local():
            return self._handle_local_filepath(path)
        return str(path)

    def _handle_local_filepath(self, path: str) -> str:
        """Handle local file path with glob pattern support."""
        path_obj = Path(path)

        if path_obj.is_dir() or path_obj.is_file():
            return path_obj.as_posix()

        if self._contains_glob_pattern(path):
            return self._handle_glob_pattern(path_obj, path)

        if not path_obj.exists():
            raise ConfigurationError(f"File '{path}' does not exist in local mode") from None

        return path_obj.as_posix()

    @staticmethod
    def _contains_glob_pattern(path: str) -> bool:
        """Check if path contains glob pattern characters."""
        return any(character in str(path) for character in ("*", "?", "["))

    def _handle_glob_pattern(self, path_obj: Path, path: str) -> str:
        """Handle glob pattern matching for local files."""
        if not path_obj.parent.exists():
            raise ConfigurationError(
                f"Parent directory for glob pattern '{path}' does not exist"
            ) from None

        matches = list(path_obj.parent.glob(path_obj.name))
        if matches:
            logger.debug("Glob pattern '{}' matched {} files", path, len(matches))
            return path_obj.as_posix()  # Return original pattern normalized for Spark to handle

        raise ConfigurationError(f"Glob pattern '{path}' matched no files in local mode") from None

    @staticmethod
    def _is_named_input_map(keys: Any) -> bool:
        """True when ``input`` is a ``{param_name: dataset_key}`` mapping."""
        if not isinstance(keys, dict) or not keys:
            return False
        return all(isinstance(v, str) and v.strip() for v in keys.values())

    def get_input_param_names(self, node: Dict[str, Any]) -> Optional[List[str]]:
        """Return the function parameter names when ``input`` is a named map."""
        keys = node.get("input")
        if self._is_named_input_map(keys):
            return [str(param) for param in keys.keys()]
        return None

    def _get_input_keys(self, node: Dict[str, Any]) -> List[str]:
        """Get and validate input keys from node configuration."""
        keys = node.get("input", [])

        if keys is None:
            return []
        if isinstance(keys, str):
            return [keys]
        if self._is_named_input_map(keys):
            return [v.strip() for v in keys.values()]
        if isinstance(keys, list):
            result = []
            for key in keys:
                if not isinstance(key, str) or not key.strip():
                    raise ConfigurationError(
                        f"Invalid input key: {key}. All input keys must be non-empty strings."
                    ) from None
                result.append(key.strip())
            return result
        raise ConfigurationError(
            f"Invalid input format: expected string, list, or {{param: dataset_key}} map, "
            f"got {type(keys)}"
        ) from None

    def _get_configured_formats(self) -> Set[str]:
        """Inspect input_config and return the set of formats in use."""
        input_cfg = self._ctx_get("input_config", {}) or {}
        formats = set()

        for key, cfg in input_cfg.items():
            try:
                if isinstance(cfg, dict):
                    fmt = str(cfg.get("format", "")).lower().strip()
                    if fmt:
                        formats.add(fmt)
            except Exception:
                logger.debug("Skipping format detection for malformed input_config key: {}", key)

        return formats

    def _register_custom_formats(self) -> None:
        """Register custom format handlers if configured."""
        configured_formats = self._get_configured_formats()
        checks = {
            "delta": self._verify_delta_dependencies,
            "xml": self._verify_xml_dependencies,
        }

        for format_name, checker in checks.items():
            if format_name in configured_formats:
                checker()

    def _verify_delta_dependencies(self) -> None:
        """Verify delta-spark is available when Delta inputs are configured."""
        try:
            from delta import configure_spark_with_delta_pip  # type: ignore  # noqa: F401

            logger.debug("Delta format dependencies verified successfully")
        except ImportError:
            logger.warning(
                "Input format 'delta' configured but package 'delta-spark' is not installed. "
                "Install with: pip install delta-spark"
            )

    def _verify_xml_dependencies(self) -> None:
        """Verify Spark XML support is available when XML inputs are configured."""
        try:
            spark = self._ctx_spark()
            if spark:
                spark._jvm.com.databricks.spark.xml  # type: ignore[attr-defined]
            logger.debug("XML format dependencies verified")
        except Exception as error:
            logger.warning("XML format configured but dependencies not available: {}", error)
