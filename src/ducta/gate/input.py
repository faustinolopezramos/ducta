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
from typing import Any, Dict, List, Optional, Set, cast

from loguru import logger  # type: ignore

from ducta.gate.base import BaseIO
from ducta.gate.concurrency import run_parallel
from ducta.gate.constants import is_cloud_path
from ducta.gate.exceptions import ConfigurationError, MissingDependencyError, ReadOperationError
from ducta.gate.factories import ReaderFactory
from ducta.gate.fingerprinting import check_fingerprint_policy
from ducta.gate.input_paths import resolve_local_path
from ducta.gate.readers import spark_xml_available

_ON_MISSING_INPUT = frozenset({"skip", "fail"})


def sample(df: Any, rows: int) -> Any:
    """The first *rows* rows of a Spark or pandas DataFrame; anything else as it is."""
    if df is None:
        return df
    if hasattr(df, "limit") and hasattr(df, "sparkSession"):
        return df.limit(rows)
    if hasattr(df, "head") and hasattr(df, "iloc"):
        return df.head(rows)
    return df


class InputLoader(BaseIO):
    """Unified InputLoader with parallel loading strategy."""

    def __init__(self, context: Any):
        """Initialize the InputLoader (a Context or a dict: gate reads either)."""
        super().__init__(context)
        self.reader_factory = ReaderFactory(context)
        self._verify_format_dependencies()

    def load_inputs(
        self,
        node: Dict[str, Any],
        node_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Any]:
        """Load all inputs defined for a processing node.

        ``start_date``/``end_date`` bound inputs that declare
        ``incremental: {column: …}``: only that window is read and fingerprinted.
        """
        resolved_name = node_name or node.get("name") or "unnamed"
        input_keys = self._get_input_keys(node)
        if not input_keys:
            logger.warning("Node '{}' has no defined inputs", resolved_name)
            return []

        fail_fast = node.get("fail_fast", True)
        if fail_fast:
            available, missing = self._inputs_available(node)
            if not available:
                detail = f"Node '{resolved_name}' has missing input(s): {', '.join(missing)}"
                on_missing = str(node.get("on_missing_input", "skip")).strip().lower()
                if on_missing not in _ON_MISSING_INPUT:
                    logger.warning(
                        "Node '{}': unknown on_missing_input='{}'; using 'skip'. Valid: {}.",
                        resolved_name,
                        on_missing,
                        ", ".join(sorted(_ON_MISSING_INPUT)),
                    )
                    on_missing = "skip"
                if on_missing == "fail":
                    raise ReadOperationError(
                        f"{detail}. Aborting because on_missing_input=fail "
                        "(set it to 'skip' to skip this node and its descendants instead)."
                    )
                raise MissingDependencyError(detail)

        loaded = self._load_inputs_parallel(input_keys, fail_fast, start_date, end_date)
        sample_rows = self._ctx_get("sample_rows")
        if sample_rows:
            # A sample run: the node sees the first N rows of each input.
            loaded = [sample(df, int(sample_rows)) for df in loaded]
        return loaded

    @staticmethod
    def _is_query_format(config: Dict[str, Any]) -> bool:
        """True when the dataset's format is 'query' (no filepath to resolve)."""
        return str(config.get("format") or "").lower() == "query"

    def _inputs_available(self, node: Dict[str, Any]) -> "tuple[bool, List[str]]":
        """Check whether every declared input for *node* currently resolves."""
        missing: List[str] = []
        for input_key in self._get_input_keys(node):
            try:
                config = self._get_dataset_config(input_key)
                if self._is_query_format(config):
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
                if self._is_query_format(config):
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

    def _load_inputs_parallel(
        self,
        input_keys: List[str],
        fail_fast: bool = True,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Any]:
        """Load datasets in parallel, preserving input order."""
        fill_none = bool(self.context_manager.get_nested("global_config.fill_none_on_error", False))
        max_workers = self.context_manager.get_nested(
            "global_config.max_input_workers", min(len(input_keys), 4)
        )

        self._print_loading_message(len(input_keys))

        # Dates travel as arguments, not instance state: one InputLoader serves
        # every node, and nodes load their inputs concurrently.
        outcome = run_parallel(
            input_keys,
            lambda key: self._load_single_dataset(key, start_date, end_date),
            max_workers=max_workers,
            fail_fast=fail_fast,
        )

        if fail_fast and outcome.errors:
            idx, error = outcome.errors[0]
            key = input_keys[idx]
            logger.error("Error loading dataset '{}': {}", key, error)
            raise ReadOperationError(f"Error loading dataset '{key}': {error}") from error

        results = outcome.results
        errors: List[str] = []
        for idx, error in outcome.errors:
            key = input_keys[idx]
            logger.error("Error loading dataset '{}': {}", key, error)
            errors.append(f"Error loading dataset '{key}': {error}")
            results[idx] = None

        if errors:
            if not fill_none:
                raise ReadOperationError(
                    f"{len(errors)} dataset(s) failed to load: {'; '.join(errors)}. "
                    "Set global_config.fill_none_on_error=true to receive None "
                    "placeholders instead of aborting."
                )
            logger.warning("Completed loading with {} errors: {}", len(errors), errors)
            for message in errors:
                self._note_evidence_gap(f"{message} (fill_none_on_error: the node got None)")

        logger.info("Successfully loaded {} datasets", len(results) - len(errors))
        return results

    def _print_loading_message(self, dataset_count: int) -> None:
        """Tell the progress reporter (or the log) how many datasets are loading."""
        if not self._report_progress("report_loading", dataset_count):
            logger.info("Loading {} datasets", dataset_count)

    def _load_single_dataset(
        self,
        input_key: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Any:
        """Load a single dataset with proper error handling."""
        config = self._get_dataset_config(input_key)
        format_name = config.get("format", "").lower()

        if not format_name:
            raise ReadOperationError(f"Format not specified for dataset '{input_key}'")

        reader = self.reader_factory.get_reader(format_name)

        if self._is_query_format(config):
            return reader.read("", config)
        filepath = self._get_filepath(config, input_key)

        from ducta.gate import handoff

        cached = handoff.take(self.context, filepath)
        if cached is not None:
            return cached

        dataframe = reader.read(filepath, config)

        window = self._incremental_window(config, input_key, start_date, end_date)
        if window is not None:
            dataframe = self._apply_window(dataframe, window)

        delta = None
        if format_name == "delta":
            from ducta.gate.fingerprinting import delta_identity

            pinned = config.get("versionAsOf", config.get("version"))
            as_of_time = config.get("timestampAsOf", config.get("timestamp")) is not None
            # A read as of a timestamp has no version here, and the latest commit is not
            # what it read: leave the identity out and let the data be hashed.
            if pinned is not None or not as_of_time:
                delta = delta_identity(self._ctx_spark(), filepath, pinned)

        data_fingerprint = self._record_fingerprint(
            "input", input_key, filepath, dataframe, window=window, delta=delta
        )
        if data_fingerprint is not None:
            self._enforce_fingerprint_policy(input_key, data_fingerprint)

        return dataframe

    @staticmethod
    def _incremental_window(
        config: Dict[str, Any],
        input_key: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """``{column, start, end}`` for an input declaring ``incremental``, else None."""
        incremental = config.get("incremental")
        if incremental is None:
            return None
        column = incremental.get("column") if isinstance(incremental, dict) else None
        if not column:
            raise ReadOperationError(
                f"Input '{input_key}': 'incremental' needs a 'column', e.g. "
                "incremental: {column: order_date}"
            )
        if not (start_date and end_date):
            logger.warning(
                "Input '{}' declares incremental column '{}' but the run has no date "
                "range; reading (and fingerprinting) the whole dataset.",
                input_key,
                column,
            )
            return None
        return {"column": column, "start": start_date, "end": end_date}

    @staticmethod
    def _apply_window(dataframe: Any, window: Dict[str, Any]) -> Any:
        """Keep the rows of the run's window on ``column``.

        ``--end-date`` is the last day to process, so a date end covers that whole day
        (``col >= start AND col < end + 1 day``); see :func:`ducta.gate.sql.window_bounds`.
        On Spark this is a predicate the source can push down (partition pruning, Delta data
        skipping), so the read itself shrinks too.
        """
        from ducta.gate.sql import window_bounds

        column = window["column"]
        start, end, inclusive = window_bounds(window["start"], window["end"])
        if hasattr(dataframe, "rdd"):
            from pyspark.sql import functions as F  # type: ignore

            col = F.col(column)
            return dataframe.where((col >= start) & ((col <= end) if inclusive else (col < end)))
        series = dataframe[column]
        upper = (series <= end) if inclusive else (series < end)
        return dataframe[(series >= start) & upper]

    def _enforce_fingerprint_policy(self, input_key: str, data_fingerprint) -> None:
        """Apply fingerprint_policy against the previous successful run."""
        try:
            policy = self.context_manager.get_nested("global_config.fingerprint_policy", "record")
            if policy not in ("warn", "fail"):
                return
            previous_all = self._ctx_get("_previous_input_fingerprints", None) or {}
            previous = previous_all.get(input_key) or {}
        except Exception as error:  # noqa: BLE001 — a malformed record never blocks a read
            logger.debug("Fingerprint policy check skipped for '{}': {}", input_key, error)
            return
        check_fingerprint_policy(policy, previous, data_fingerprint, input_key)

    def _get_dataset_config(self, input_key: str) -> Dict[str, Any]:
        """Get configuration for a dataset with validation."""
        input_cfg = self._ctx_get("input_config", {}) or {}
        config = input_cfg.get(input_key)

        if not config:
            raise ConfigurationError(f"Missing configuration for dataset '{input_key}'")

        if not isinstance(config, dict):
            raise ConfigurationError(
                f"Invalid configuration format for dataset '{input_key}': expected dict, got {type(config)}"
            )
        return config

    def _get_filepath(self, config: Dict[str, Any], input_key: str) -> str:
        """Get filepath for a dataset, supporting glob patterns in local mode."""
        path = config.get("filepath")
        if not path:
            raise ConfigurationError(f"Missing filepath for dataset '{input_key}'")

        if is_cloud_path(path):
            return str(path)

        if self._is_local():
            return resolve_local_path(
                path,
                self._ctx_get("_read_fallback_paths", None) or [],
                self._ctx_get("output_path", None),
            )
        return str(path)

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
            return [str(param) for param in cast(Dict[str, Any], keys).keys()]
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
                    )
                result.append(key.strip())
            return result
        raise ConfigurationError(
            f"Invalid input format: expected string, list, or {{param: dataset_key}} map, "
            f"got {type(keys)}"
        )

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

    def _verify_format_dependencies(self) -> None:
        """Warn early when a configured format needs a package that is missing."""
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
        spark = self._ctx_spark()
        if spark and not spark_xml_available(spark):
            logger.warning("XML format configured but package 'spark-xml' is not available")
        else:
            logger.debug("XML format dependencies verified")
