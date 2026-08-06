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

Declarative JDBC ingestion nodes (``type: ingestion``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.core.execution.output import OutputWriter
from ducta.core.execution.quality import QualityCheckExecutor
from ducta.core.settings import CoreSettings
from ducta.gate.exceptions import ConfigurationError as GateConfigurationError
from ducta.gate.sql import SQLSanitizer


class IngestionExecutor:
    """Executes declarative JDBC ingestion nodes (``type: ingestion``) natively."""

    DEFAULT_SOURCES_PATH = "config/sources.yaml"

    def __init__(
        self,
        context: Any,
        output_writer: "OutputWriter",
        quality_executor: QualityCheckExecutor,
        settings: Optional[CoreSettings] = None,
    ) -> None:
        self.context = context
        self.settings = settings or CoreSettings.from_context(context)
        self.output_writer = output_writer
        self._quality_executor = quality_executor

    def _resolve_sources_path(self, node_config: Dict[str, Any]) -> Path:
        """Resolve the sources file path."""
        node_path = node_config.get("sources")
        if node_path:
            return Path(node_path)

        config_paths = getattr(self.context, "config_paths", None) or {}
        if isinstance(config_paths, dict) and config_paths.get("sources_config_path"):
            return Path(config_paths["sources_config_path"])

        sources_path = self.settings.ingestion.get("sources_path")
        if sources_path:
            return Path(sources_path)

        return Path(self.DEFAULT_SOURCES_PATH)

    def _get_connection_manager(self, sources_path: Path) -> Any:
        """Get (or lazily create and cache) a ConnectionManager for a sources file."""
        from ducta.gate.gateway import ConnectionManager

        cache = getattr(self.context, "_ingestion_managers", None)
        if cache is None:
            cache = {}
            setattr(self.context, "_ingestion_managers", cache)

        key = str(sources_path)
        if key not in cache:
            cache[key] = ConnectionManager(sources_path)
        return cache[key]

    #: A bare SQL identifier, optionally schema- or catalog-qualified.
    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

    @classmethod
    def _build_dbtable(cls, node_name: str, table: str, columns, where) -> str:
        """Compose a `dbtable` value, optionally selecting columns / filtering rows.

        Everything interpolated here reaches the database verbatim, so each part
        is checked before it goes in: identifiers against a strict pattern, and
        the assembled statement through the same :class:`SQLSanitizer` the JDBC
        gateway uses. Previously the three fragments were concatenated unchecked,
        which left the ingestion node as the one SQL path in the project with no
        sanitization at all.
        """
        if not cls._IDENTIFIER_RE.match(str(table or "")):
            raise ValueError(
                f"Ingestion node '{node_name}': 'table' must be a plain identifier "
                f"(optionally schema-qualified), got {table!r}. Use 'query' for anything else."
            )

        if not columns and not where:
            return table

        if columns:
            if not isinstance(columns, (list, tuple)) or not all(
                isinstance(c, str) for c in columns
            ):
                raise ValueError(
                    f"Ingestion node '{node_name}': 'columns' must be a list of column names."
                )
            invalid = [c for c in columns if not cls._IDENTIFIER_RE.match(c)]
            if invalid:
                raise ValueError(
                    f"Ingestion node '{node_name}': 'columns' must be plain column names; "
                    f"rejected {invalid}. Use 'query' for expressions or aliases."
                )
            select = ", ".join(columns)
        else:
            select = "*"

        sql = f"SELECT {select} FROM {table}"
        if where:
            sql += f" WHERE {where}"

        try:
            SQLSanitizer.sanitize_query(sql)
        except GateConfigurationError as error:
            raise ValueError(
                f"Ingestion node '{node_name}': rejected the composed query ({error}). "
                f"Check the 'where' clause."
            ) from error

        return f"({sql}) AS q"

    def execute(
        self,
        node_name: str,
        node_config: Dict[str, Any],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
        pipeline_name: Optional[str] = None,
    ) -> None:
        """Read a table/query from a configured JDBC source into Bronze."""
        source = node_config.get("source")
        table = node_config.get("table")
        query = node_config.get("query")
        columns = node_config.get("columns")
        where = node_config.get("where")
        options = node_config.get("options") or {}

        if not source:
            raise ValueError(
                f"Ingestion node '{node_name}' requires a 'source' field "
                "(a connection name defined in config/sources.yaml)."
            )
        if bool(table) == bool(query):
            raise ValueError(
                f"Ingestion node '{node_name}' requires exactly one of 'table' or 'query'."
            )
        if query and (columns or where):
            raise ValueError(
                f"Ingestion node '{node_name}': 'columns'/'where' cannot be combined "
                "with 'query' (put the projection/filter inside the query)."
            )
        if not isinstance(options, dict):
            raise ValueError(
                f"Ingestion node '{node_name}': 'options' must be a mapping of Spark "
                "JDBC read options."
            )

        spark = getattr(self.context, "spark", None)
        if spark is None:
            raise RuntimeError(
                f"Ingestion node '{node_name}': no SparkSession available in the Ducta context."
            )

        sources_path = self._resolve_sources_path(node_config)
        manager = self._get_connection_manager(sources_path)
        conn = manager.get(source)

        opts: Dict[str, str] = {
            "url": conn.jdbc_url,
            "user": conn.jdbc_properties["user"],
            "password": conn.jdbc_properties["password"],
            "driver": conn.jdbc_properties["driver"],
        }
        if query:
            # A declared `query` used to go straight to the driver. It is
            # read-only by contract, so it goes through the same check the JDBC
            # gateway applies to the queries it is handed.
            try:
                SQLSanitizer.sanitize_query(query)
            except GateConfigurationError as error:
                raise ValueError(
                    f"Ingestion node '{node_name}': 'query' rejected ({error}). "
                    f"Ingestion queries must be read-only SELECT/WITH statements."
                ) from error
            opts["query"] = query
        else:
            opts["dbtable"] = self._build_dbtable(node_name, table, columns, where)

        opts.update({k: str(v) for k, v in options.items()})

        logger.info(
            "Ingestion node '{}': reading {} from source '{}'",
            node_name,
            f"table '{table}'" if table else "query",
            source,
        )

        result_df = spark.read.format("jdbc").options(**opts).load()

        # Sanity checks (e.g. empty_dataset) on the freshly read data.
        sanity_report = self._quality_executor.run_sanity_checks(
            [result_df], node_config, node_name, pipeline_name=pipeline_name
        )
        self._quality_executor.persist_report(
            sanity_report,
            "sanity",
            "sanity_checks",
            node_name,
            node_config,
            ml_info,
            pipeline_name=pipeline_name,
        )

        dq_report = self._quality_executor.run_dq_checks(
            result_df, node_config, node_name, pipeline_name=pipeline_name
        )
        self._quality_executor.persist_report(
            dq_report,
            "dq",
            "data_quality",
            node_name,
            node_config,
            ml_info,
            pipeline_name=pipeline_name,
        )

        self.output_writer.save(result_df, node_config, node_name, start_date, end_date, ml_info)

        logger.info("Ingestion node '{}' completed successfully", node_name)
