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

import sys
from typing import Any, Optional

from loguru import logger  # type: ignore

from ducta.gate.base import BaseIO
from ducta.gate.exceptions import ConfigurationError, WriteOperationError

try:
    from pyspark.sql import DataFrame as SparkDataFrame  # type: ignore
except ImportError:
    SparkDataFrame = type("SparkDataFrame", (), {})  # type: ignore[misc,assignment]  # no pyspark

try:
    import pandas as pd  # type: ignore
except ImportError:
    pd = None

try:
    import polars as pl  # type: ignore
except ImportError:
    pl = None


def _connect_dataframe_class() -> Optional[type]:
    """Spark Connect's DataFrame class, when something has already imported it.

    Never imported here. On Spark 4 without the ``connect`` extra, importing
    ``pyspark.sql.connect`` runs a dependency check that calls ``sys.exit(0)``
    when ``__main__`` has no file (``python -c``, ``python -m``, spawned
    workers): the process ended with success having done nothing. A Connect
    DataFrame cannot exist before its module is loaded, so looking the class up
    in ``sys.modules`` misses none.
    """
    module = sys.modules.get("pyspark.sql.connect.dataframe")
    cls = getattr(module, "DataFrame", None)
    return cls if isinstance(cls, type) else None


class _DataFrameManager(BaseIO):
    """Unified DataFrame operations manager."""

    def convert_to_spark(self, dataframe: Any, schema: Any = None):
        """Convert any DataFrame to Spark DataFrame."""
        if not self._spark_available():
            raise WriteOperationError("Spark session unavailable")

        if self.is_spark_dataframe(dataframe):
            return dataframe

        spark = self._require_spark()

        if pd and isinstance(dataframe, pd.DataFrame):
            logger.debug("Converting pandas DataFrame to Spark")
            return (
                spark.createDataFrame(dataframe, schema=schema)
                if schema
                else spark.createDataFrame(dataframe)
            )

        if pl and isinstance(dataframe, pl.DataFrame):
            logger.debug("Converting Polars DataFrame to Spark")
            try:
                if hasattr(dataframe, "to_arrow"):
                    arrow_table = dataframe.to_arrow()

                    try:
                        pandas_dataframe = arrow_table.to_pandas(self_destruct=True)
                    except TypeError:
                        pandas_dataframe = arrow_table.to_pandas()
                else:
                    pandas_dataframe = dataframe.to_pandas()
                return (
                    spark.createDataFrame(pandas_dataframe, schema=schema)
                    if schema
                    else spark.createDataFrame(pandas_dataframe)
                )
            except Exception as error:
                raise WriteOperationError(f"Polars conversion failed: {error}") from error

        raise ConfigurationError(f"Unsupported DataFrame type: {type(dataframe)}")

    def is_spark_dataframe(self, dataframe: Any) -> bool:
        """Detect Spark DataFrames (classic and Connect)."""
        if isinstance(dataframe, SparkDataFrame):
            return True
        connect = _connect_dataframe_class()
        if connect is not None and isinstance(dataframe, connect):
            return True

        module = getattr(type(dataframe), "__module__", "")
        if "pyspark.sql" in module:
            return hasattr(dataframe, "schema") and (
                hasattr(dataframe, "write") or hasattr(dataframe, "toPandas")
            )

        return False
