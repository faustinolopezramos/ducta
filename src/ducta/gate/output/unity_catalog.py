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

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.gate.base import BaseIO
from ducta.gate.constants import (
    DEFAULT_VACUUM_RETENTION_HOURS,
    MIN_VACUUM_RETENTION_HOURS,
    WriteMode,
)
from ducta.gate.exceptions import ConfigurationError, WriteOperationError
from ducta.gate.factories import WriterFactory
from ducta.gate.sql import SqlSafetyMixin, UnityCatalogDDL


@dataclass
class UnityCatalogConfig:
    """Configuration for Unity Catalog operations."""

    catalog_name: str
    schema: str
    table_name: str
    uc_table_mode: str = "external"
    optimize: bool = True
    vacuum: bool = False
    vacuum_retention_hours: Optional[int] = None
    write_mode: str = WriteMode.OVERWRITE.value
    overwrite_schema: bool = True
    partition_col: Optional[str] = None
    description: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.uc_table_mode not in ["external", "managed"]:
            raise ConfigurationError(f"Invalid uc_table_mode: {self.uc_table_mode}")


class UnityCatalogManager(BaseIO, SqlSafetyMixin):
    """Simplified Unity Catalog operations."""

    def __init__(self, context: Any):
        super().__init__(context)
        #: Resolved on first `is_enabled()`, not here — see that method.
        self._enabled: Optional[bool] = None
        self._catalog_cache: Dict[str, bool] = {}
        self._schema_cache: Dict[tuple, bool] = {}

    def _check_enabled(self) -> bool:
        """Ask the session whether Unity Catalog is on."""
        spark = self._ctx_spark()
        if not spark:
            return False
        return spark.conf.get("spark.databricks.unityCatalog.enabled", "false").lower() == "true"

    def is_enabled(self) -> bool:
        """Whether Unity Catalog is available, resolved lazily and cached."""
        if self._enabled is None:
            self._enabled = self._check_enabled()
        return self._enabled

    def clear_metadata_cache(self) -> None:
        """Invalidate cached catalog and schema metadata."""
        self._catalog_cache.clear()
        self._schema_cache.clear()
        logger.info("Unity Catalog metadata cache cleared")

    def _catalog_exists(self, catalog: str) -> bool:
        """Check catalog existence with per-instance dict caching."""
        if catalog in self._catalog_cache:
            return self._catalog_cache[catalog]

        if not self._spark_available():
            return False

        try:
            spark = self._ctx_spark()
            result = spark.sql(UnityCatalogDDL.catalog_exists_query(catalog))
            exists = len(result.take(1)) > 0
            self._catalog_cache[catalog] = exists
            return exists
        except Exception as error:
            logger.error("Error checking catalog {}: {}", catalog, error)
            return False

    def _schema_exists(self, catalog: str, schema: str) -> bool:
        """Check schema existence with per-instance dict caching."""
        cache_key = (catalog, schema)
        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key]

        if not self._spark_available():
            return False

        try:
            spark = self._ctx_spark()
            result = spark.sql(UnityCatalogDDL.schema_exists_query(catalog, schema))
            exists = len(result.take(1)) > 0
            self._schema_cache[cache_key] = exists
            return exists
        except Exception as error:
            logger.error("Error checking schema {}.{}: {}", catalog, schema, error)
            return False

    def ensure_schema_exists(
        self,
        catalog: str,
        schema: str,
        location: Optional[str] = None,
        managed: bool = False,
    ) -> None:
        """
        Ensure catalog and schema exist (convenience utility).
        """
        if not self._spark_available():
            logger.warning("Spark unavailable for schema creation")
            return

        spark = self._ctx_spark()

        if not self._catalog_exists(catalog):
            logger.warning(
                "Catalog '{}' does not exist. Attempting to create it. "
                "Best practice: Pre-create catalogs using Databricks UI/CLI. "
                "This requires CREATE CATALOG permission.",
                catalog,
            )
            spark.sql(UnityCatalogDDL.create_catalog(catalog))
            logger.info("Created catalog: {}", catalog)
            self._catalog_cache.clear()

        if not self._schema_exists(catalog, schema):
            logger.warning(
                "Schema '{}.{}' does not exist. Attempting to create it. "
                "Best practice: Pre-create schemas using Databricks UI/CLI. "
                "This requires CREATE SCHEMA permission.",
                catalog,
                schema,
            )
            spark.sql(
                UnityCatalogDDL.create_schema(catalog, schema, location=location, managed=managed)
            )
            logger.info("Created schema: {}.{}", catalog, schema)
            self._schema_cache.clear()

    def write_managed_table(
        self, dataframe: Any, full_table_name: str, config: UnityCatalogConfig
    ) -> None:
        """Write as managed UC table."""
        quoted_name = self.quote_table_name(full_table_name)

        writer = (
            dataframe.write.format("delta")
            .mode(config.write_mode)
            .option("overwriteSchema", str(config.overwrite_schema).lower())
        )

        for option_key, option_value in config.options.items():
            writer = writer.option(option_key, option_value)

        writer.saveAsTable(quoted_name)
        logger.info("Created managed table: {}", full_table_name)

    def write_external_table(
        self,
        dataframe: Any,
        full_table_name: str,
        location: str,
        config: UnityCatalogConfig,
        writer_factory: Optional[Any] = None,
    ) -> None:
        """Write as external UC table."""
        writer_config = {
            "format": "delta",
            "write_mode": config.write_mode,
            "overwrite_schema": config.overwrite_schema,
            "options": config.options,
        }

        if writer_factory is None:
            writer_factory = WriterFactory(self._context)

        writer = writer_factory.get_writer("delta")
        writer.write(dataframe, location, writer_config)

        spark = self._ctx_spark()
        if spark is None:
            raise WriteOperationError(
                f"Spark session unavailable; cannot register external table {full_table_name}"
            ) from None
        spark.sql(UnityCatalogDDL.create_external_table(full_table_name, location))
        logger.info("Created external table: {}", full_table_name)

    def post_write_operations(
        self,
        full_table_name: str,
        config: UnityCatalogConfig,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """Execute post-write operations."""
        if not self._spark_available():
            return

        spark = self._ctx_spark()
        quoted_name = self.quote_table_name(full_table_name)

        self._add_comment_if_needed(spark, quoted_name, full_table_name, config)
        self._optimize_if_needed(spark, quoted_name, full_table_name, config, start_date, end_date)
        self._vacuum_if_needed(spark, quoted_name, full_table_name, config)

    def _add_comment_if_needed(
        self,
        spark,
        quoted_name: str,
        full_table_name: str,
        config: UnityCatalogConfig,
    ) -> None:
        """Add comment to table if description or partition_col is provided."""
        if not (config.description or config.partition_col):
            return

        comment = (
            f"{config.description or 'Data table'}. Partition: {config.partition_col or 'N/A'}"
        )
        try:
            spark.sql(UnityCatalogDDL.comment_on_table(quoted_name, comment))
            logger.info("Added comment to {}", full_table_name)
        except Exception as error:
            logger.error("Error adding comment: {}", error)

    def _optimize_if_needed(
        self,
        spark,
        quoted_name: str,
        full_table_name: str,
        config: UnityCatalogConfig,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> None:
        """Optimize table for the given partition range if requested."""
        if not (config.optimize and config.partition_col and start_date and end_date):
            return

        try:
            sql = UnityCatalogDDL.optimize_where(
                quoted_name, config.partition_col, start_date, end_date
            )
            spark.sql(sql)
            logger.info("Optimized table {}", full_table_name)
        except Exception as error:
            logger.error("Error optimizing table: {}", error)

    def _vacuum_if_needed(
        self,
        spark,
        quoted_name: str,
        full_table_name: str,
        config: UnityCatalogConfig,
    ) -> None:
        """Run VACUUM on table if requested or retention configured."""
        if not (config.vacuum or config.vacuum_retention_hours):
            return

        requested_hours = config.vacuum_retention_hours or DEFAULT_VACUUM_RETENTION_HOURS
        hours = max(MIN_VACUUM_RETENTION_HOURS, requested_hours)

        if requested_hours < MIN_VACUUM_RETENTION_HOURS:
            logger.warning(
                "Requested vacuum retention of {} hours is below "
                "minimum of {} hours. Using minimum value. "
                "To use lower values, set spark.databricks.delta.retentionDurationCheck.enabled=false",
                requested_hours,
                MIN_VACUUM_RETENTION_HOURS,
            )

        try:
            spark.sql(UnityCatalogDDL.vacuum(quoted_name, hours))
            logger.info("Vacuumed table {} with {} hours retention", full_table_name, hours)
        except Exception as error:
            logger.error("Error vacuuming table: {}", error)
