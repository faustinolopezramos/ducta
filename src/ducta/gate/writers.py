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

from typing import Any, Dict

from loguru import logger  # type: ignore

from ducta.gate.base import BaseIO
from ducta.gate.constants import DEFAULT_CSV_OPTIONS, WriteMode
from ducta.gate.exceptions import ConfigurationError, WriteOperationError
from ducta.gate.validators import ConfigValidator, DataValidator

DESTINATION_EMPTY_ERROR = "Destination path cannot be empty"

_data_validator = DataValidator()


def normalize_partition_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize partition configuration keys."""
    partition_val = config.get("partition")
    if partition_val is None:
        partition_val = config.get("partition_col")
    if partition_val is None:
        partition_val = config.get("partition_columns")

    if partition_val is not None:
        config = {**config}  # shallow copy – do not mutate caller's dict
        config["partition"] = partition_val
        config["partition_col"] = (
            partition_val[0]
            if isinstance(partition_val, (list, tuple)) and len(partition_val) == 1
            else partition_val
        )
        config["partition_columns"] = (
            partition_val if isinstance(partition_val, list) else [partition_val]
        )
    return config


class SparkWriterMixin:
    """Mixin for Spark-based writers with enhanced write mode and schema handling."""

    FORMAT: str = ""  # Override in concrete writer subclasses
    MAX_RECOMMENDED_PARTITIONS: int = 5

    def _configure_spark_writer(self, dataframe: Any, config: Dict[str, Any]) -> Any:
        """Configure Spark DataFrame writer with write mode and schema options."""
        config = normalize_partition_config(config)

        write_mode = self._determine_write_mode(config)
        _data_validator.validate_dataframe(
            dataframe, allow_empty=write_mode == WriteMode.OVERWRITE.value
        )
        writer = dataframe.write.format(self._get_format()).mode(write_mode)
        logger.debug("Writer configured with mode: {}", write_mode)

        writer = self._apply_partition(writer, dataframe, config)
        writer = self._apply_overwrite_and_replacewhere(writer, config, write_mode)

        for option_key, option_value in config.get("options", {}).items():
            writer = writer.option(option_key, option_value)
            logger.debug("Extra option applied: {}={}", option_key, option_value)

        return writer

    def _determine_write_mode(self, config: Dict[str, Any]) -> str:
        """Determine the write mode."""
        write_mode = config.get("write_mode", WriteMode.OVERWRITE.value)
        valid_modes = [mode.value for mode in WriteMode]
        if write_mode not in valid_modes:
            raise ConfigurationError(f"Invalid write_mode '{write_mode}'. Valid: {valid_modes}")
        if write_mode == WriteMode.MERGE.value:
            # Reaching here means a non-Delta writer: DeltaWriter handles merge
            # itself and never configures a plain DataFrameWriter for it.
            raise ConfigurationError(
                f"write_mode 'merge' is supported only for format 'delta', not "
                f"'{self._get_format()}'"
            )
        return write_mode

    def _apply_partition(
        self,
        writer: Any,
        dataframe: Any,
        config: Dict[str, Any],
    ) -> Any:
        """Apply partitioning if configured and columns exist."""
        partition_columns = config.get("partition")
        if not partition_columns:
            return writer

        if isinstance(partition_columns, str):
            partition_columns = [partition_columns]
        elif not isinstance(partition_columns, list):
            raise ConfigurationError(
                f"Partition columns must be str or list, not {type(partition_columns)}"
            ) from None

        if len(partition_columns) > self.MAX_RECOMMENDED_PARTITIONS:
            logger.warning(
                "Partitioning by {} columns may cause excessive small files. "
                "Consider reducing to {} or fewer columns for better performance. "
                "Current partitions: {}",
                len(partition_columns),
                self.MAX_RECOMMENDED_PARTITIONS,
                partition_columns,
            )

        _data_validator.validate_columns_exist(dataframe, partition_columns)
        writer = writer.partitionBy(*partition_columns)
        logger.debug("partitionBy applied: {}", partition_columns)
        return writer

    def _apply_overwrite_and_replacewhere(
        self, writer: Any, config: Dict[str, Any], write_mode: str
    ) -> Any:
        """Apply overwriteSchema and replaceWhere when appropriate."""
        overwrite_schema = bool(
            config.get("overwrite_schema", self._get_default_overwrite_schema())
        )
        if overwrite_schema and self._supports_overwrite_schema():
            writer = writer.option("overwriteSchema", "true")
            logger.debug("overwriteSchema=true applied")

        if (
            str(config.get("overwrite_strategy", "")).lower() == "replacewhere"
            and write_mode == WriteMode.OVERWRITE.value
        ):
            writer = self._apply_replace_where_strategy(writer, config)

        return writer

    def _apply_replace_where_strategy(self, writer: Any, config: Dict[str, Any]) -> Any:
        """Apply replaceWhere or replace_predicate for Delta format."""
        if self._get_format() != "delta":
            raise ConfigurationError(
                "overwrite_strategy=replaceWhere is supported only for Delta"
            ) from None

        predicate = config.get("replace_predicate")
        if predicate:
            writer = writer.option("replaceWhere", predicate).option("overwriteSchema", "false")
            logger.debug("replaceWhere applied with custom predicate: {}", predicate)
            return writer

        partition_col = config.get("partition_col")
        start_date = config.get("start_date")
        end_date = config.get("end_date")
        missing = [
            key
            for key, value in {
                "partition_col": partition_col,
                "start_date": start_date,
                "end_date": end_date,
            }.items()
            if not value
        ]
        if missing:
            raise ConfigurationError(f"replaceWhere requires: {', '.join(missing)}") from None

        if not (
            ConfigValidator.validate_date_format(start_date)
            and ConfigValidator.validate_date_format(end_date)
        ):
            raise ConfigurationError(
                f"Invalid date format: {start_date} - {end_date}. Expected: YYYY-MM-DD"
            ) from None

        predicate = f"{partition_col} BETWEEN '{start_date}' AND '{end_date}'"
        writer = writer.option("replaceWhere", predicate).option("overwriteSchema", "false")
        logger.debug("replaceWhere applied: {}", predicate)
        return writer

    def _get_format(self) -> str:
        """Get the writer format from the FORMAT class attribute."""
        return self.FORMAT

    def _supports_overwrite_schema(self) -> bool:
        """Return whether the format supports overwriteSchema."""
        return self._get_format() in ["delta", "parquet"]

    def _get_default_overwrite_schema(self) -> bool:
        """Default value for overwriteSchema option."""
        return self._get_format() == "delta"

    def _print_write_separator(self, destination: str) -> None:
        """Print data writing separator via progress_reporter if provided in context."""
        reporter = self._ctx_get("progress_reporter", None)
        if reporter and hasattr(reporter, "report_saving"):
            try:
                reporter.report_saving(destination)
                return
            except Exception:
                pass
        logger.debug("Saving output to: {}", destination)


class BaseSparkWriter(BaseIO, SparkWriterMixin):
    """Base class for all Spark writers with a shared write template."""

    def __init__(self, context: Any):
        super().__init__(context)

    def _prepare_write_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Hook for subclasses to customize config before writing."""
        return config

    def write(self, dataframe: Any, destination: str, config: Dict[str, Any]) -> None:
        """Write data to destination using Spark."""
        if not destination or not str(destination).strip():
            raise ConfigurationError(DESTINATION_EMPTY_ERROR) from None

        config = self._prepare_write_config(config)

        self._print_write_separator(destination)
        logger.info("Writing {} data to: {}", self.FORMAT.upper(), destination)

        try:
            writer = self._configure_spark_writer(dataframe, config)
            writer.save(destination)
            logger.success("{} data written successfully to: {}", self.FORMAT.upper(), destination)
        except WriteOperationError:
            raise
        except Exception as error:
            raise WriteOperationError(
                f"Failed to write {self.FORMAT.upper()} to {destination}: {error}"
            ) from error


class DeltaWriter(BaseSparkWriter):
    """Delta Lake writer with advanced partition, selective replace and MERGE support."""

    FORMAT = "delta"

    def write(self, dataframe: Any, destination: str, config: Dict[str, Any]) -> None:
        if config.get("write_mode") != WriteMode.MERGE.value:
            super().write(dataframe, destination, config)
            return
        if not destination or not str(destination).strip():
            raise ConfigurationError(DESTINATION_EMPTY_ERROR) from None
        self._print_write_separator(destination)
        try:
            DeltaMerge(dataframe, destination, config).run(
                create=lambda: super(DeltaWriter, self).write(
                    dataframe, destination, {**config, "write_mode": WriteMode.OVERWRITE.value}
                )
            )
        except (WriteOperationError, ConfigurationError):
            raise
        except Exception as error:
            raise WriteOperationError(f"MERGE into {destination} failed: {error}") from error


class DeltaMerge:
    """Upsert a DataFrame into a Delta table by key.

    ``output.yaml``::

        write_mode: merge
        merge:
          keys: [order_id]                 # required
          when_matched: update_all         # update_all | {update: [cols]} | ignore
          when_not_matched: insert_all     # insert_all | ignore
          delete_when: "s._deleted = true" # optional; s = incoming batch, t = target
          schema_evolution: false

    Keys match null-safely (``<=>``): with plain ``=`` a row whose key is NULL
    never matches, so every re-run inserts it again and the write stops being
    idempotent. Duplicate keys in the incoming batch are rejected up front with
    the offending keys, rather than surfacing as Delta's "multiple source rows
    matched" halfway through the merge.
    """

    def __init__(self, dataframe: Any, destination: str, config: Dict[str, Any]) -> None:
        self.df = dataframe
        self.destination = destination
        self.spec = config.get("merge") or {}
        self.keys = self.spec.get("keys") or []
        if isinstance(self.keys, str):
            self.keys = [self.keys]
        validate_merge_spec(self.spec)

    def run(self, create: Any) -> None:
        spark = self.df.sparkSession
        self._check_keys_exist()
        self._check_no_duplicate_keys()

        target = self._target(spark)
        if target is None:
            logger.info("MERGE target {} does not exist yet — creating it", self.destination)
            create()
            return

        builder = target.alias("t").merge(
            self.df.alias("s"),
            " AND ".join(f"t.`{k}` <=> s.`{k}`" for k in self.keys),
        )
        delete_when = self.spec.get("delete_when")
        if delete_when:
            builder = builder.whenMatchedDelete(condition=delete_when)

        when_matched = self.spec.get("when_matched", "update_all")
        if when_matched == "update_all":
            builder = builder.whenMatchedUpdateAll()
        elif isinstance(when_matched, dict):
            builder = builder.whenMatchedUpdate(set={c: f"s.`{c}`" for c in when_matched["update"]})

        if self.spec.get("when_not_matched", "insert_all") == "insert_all":
            # A row flagged for deletion that is not in the target must not be
            # inserted just because it did not match.
            builder = builder.whenNotMatchedInsertAll(
                condition=f"NOT ({delete_when})" if delete_when else None
            )

        conf_key = "spark.databricks.delta.schema.autoMerge.enabled"
        evolve = bool(self.spec.get("schema_evolution", False))
        previous = spark.conf.get(conf_key, None) if evolve else None
        if evolve:
            spark.conf.set(conf_key, "true")
        try:
            builder.execute()
        finally:
            if evolve:
                if previous is None:
                    spark.conf.unset(conf_key)
                else:
                    spark.conf.set(conf_key, previous)
        logger.success("MERGE into {} on {} completed", self.destination, self.keys)

    def _target(self, spark: Any) -> Any:
        try:
            from delta.tables import DeltaTable  # type: ignore
        except ImportError as e:
            raise ConfigurationError(
                "write_mode 'merge' needs the delta-spark package (pip install 'ducta[delta]')"
            ) from e
        if "/" in self.destination or ":" in self.destination:
            if not DeltaTable.isDeltaTable(spark, self.destination):
                return None
            return DeltaTable.forPath(spark, self.destination)
        if not spark.catalog.tableExists(self.destination):
            return None
        return DeltaTable.forName(spark, self.destination)

    def _check_keys_exist(self) -> None:
        missing = [k for k in self.keys if k not in self.df.columns]
        if missing:
            raise ConfigurationError(
                f"MERGE into {self.destination}: key column(s) {missing} are not in the "
                f"output (columns: {self.df.columns})"
            )

    def _check_no_duplicate_keys(self) -> None:
        dupes = self.df.groupBy(*self.keys).count().where("count > 1")
        examples = dupes.limit(5).collect()
        if examples:
            total = dupes.count()
            shown = "; ".join(
                ", ".join(f"{k}={row[k]!r}" for k in self.keys) + f" (x{row['count']})"
                for row in examples
            )
            raise WriteOperationError(
                f"MERGE into {self.destination}: {total} key(s) appear more than once in "
                f"the incoming batch, so the merge is ambiguous — e.g. {shown}. "
                "Deduplicate the node's output by its merge keys."
            )


def validate_merge_spec(spec: Any) -> None:
    """Raise ConfigurationError for a malformed ``merge:`` block (used by preflight too)."""
    if not isinstance(spec, dict) or not spec.get("keys"):
        raise ConfigurationError("write_mode 'merge' needs merge.keys: [<column>, ...]")
    when_matched = spec.get("when_matched", "update_all")
    if not (
        when_matched in ("update_all", "ignore")
        or (isinstance(when_matched, dict) and isinstance(when_matched.get("update"), list))
    ):
        raise ConfigurationError(
            "merge.when_matched must be 'update_all', 'ignore' or {update: [columns]}"
        )
    if spec.get("when_not_matched", "insert_all") not in ("insert_all", "ignore"):
        raise ConfigurationError("merge.when_not_matched must be 'insert_all' or 'ignore'")
    delete_when = spec.get("delete_when")
    if delete_when is not None:
        from ducta.check.checks.business import BusinessRulesCheck

        try:
            BusinessRulesCheck._validate_sql_rule(str(delete_when))
        except ValueError as e:
            raise ConfigurationError(f"merge.delete_when: {e}") from e


class ParquetWriter(BaseSparkWriter):
    """Writer for Parquet format."""

    FORMAT = "parquet"


class CSVWriter(BaseSparkWriter):
    """Writer for CSV format."""

    FORMAT = "csv"

    def _prepare_write_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge CSV-specific default options into config."""
        csv_defaults = {**DEFAULT_CSV_OPTIONS, "quote": '"', "escape": '"'}
        merged_options = {**csv_defaults, **config.get("options", {})}
        return {**config, "options": merged_options}


class JSONWriter(BaseSparkWriter):
    """Writer for JSON format."""

    FORMAT = "json"


class ORCWriter(BaseSparkWriter):
    """Writer for ORC format."""

    FORMAT = "orc"
