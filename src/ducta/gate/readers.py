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

import pickle
from typing import Any, Dict

from loguru import logger  # type: ignore

from ducta.gate.base import BaseIO
from ducta.gate.constants import DEFAULT_CSV_OPTIONS, DEFAULT_ENCODING
from ducta.gate.exceptions import ConfigurationError, ReadOperationError


class SparkReaderBase(BaseIO):
    """Base class for Spark readers providing unified context access and common utilities."""

    def _apply_partition_filter(self, dataframe: Any, config: Dict[str, Any]) -> Any:
        """Apply partition filter to DataFrame if specified."""
        partition_filter = config.get("partition_filter")
        if not partition_filter:
            return dataframe

        logger.info("Applying partition_filter: {}", partition_filter)
        try:
            dataframe = dataframe.filter(partition_filter)
            logger.debug("Partition filter applied successfully")
        except Exception as filter_exc:
            logger.warning(
                "filter() failed for partition_filter '{}': {}. Trying where() fallback.",
                partition_filter,
                filter_exc,
            )
            try:
                dataframe = dataframe.where(partition_filter)
            except Exception as where_exc:
                raise ReadOperationError(
                    f"Both filter() and where() failed for partition_filter "
                    f"'{partition_filter}': {where_exc}"
                ) from where_exc

        return dataframe

    def _spark_read(self, format_name: str, filepath: str, config: Dict[str, Any]) -> Any:
        """Read data using Spark with format-specific handling."""
        spark = self._ctx_spark()
        if spark is None:
            raise ReadOperationError(
                f"Spark session is not available in context; cannot read {format_name.upper()} from {filepath}"
            ) from None
        logger.info("Reading {} data from: {}", format_name.upper(), filepath)
        try:
            reader = spark.read.options(**config.get("options", {})).format(format_name)
            dataframe = reader.load(filepath)
            logger.debug("Successfully loaded {} from {}", format_name.upper(), filepath)
            return self._apply_partition_filter(dataframe, config)
        except Exception as error:
            raise ReadOperationError(
                f"Spark failed to read {format_name.upper()} from {filepath}: {error}"
            ) from error


class ParquetReader(SparkReaderBase):
    def read(self, source: str, config: Dict[str, Any]) -> Any:
        return self._spark_read("parquet", source, config)


class JSONReader(SparkReaderBase):
    def read(self, source: str, config: Dict[str, Any]) -> Any:
        options = config.get("options", {})
        if "encoding" not in options:
            options = {**options, "encoding": DEFAULT_ENCODING}
            config = {**config, "options": options}
        return self._spark_read("json", source, config)


class CSVReader(SparkReaderBase):
    def read(self, source: str, config: Dict[str, Any]) -> Any:
        options = {**DEFAULT_CSV_OPTIONS, **config.get("options", {})}
        if "encoding" not in options:
            options["encoding"] = DEFAULT_ENCODING
        config_with_defaults = {**config, "options": options}
        return self._spark_read("csv", source, config_with_defaults)


class DeltaReader(SparkReaderBase):
    def read(self, source: str, config: Dict[str, Any]) -> Any:
        spark = self._ctx_spark()
        if spark is None:
            raise ReadOperationError(
                f"Spark session is not available in context; cannot read DELTA from {source}"
            ) from None

        reader = spark.read.options(**config.get("options", {})).format("delta")

        version = config.get("versionAsOf") or config.get("version")
        timestamp = config.get("timestampAsOf") or config.get("timestamp")

        if version is not None:
            logger.info("Loading Delta with versionAsOf={}", version)
            dataframe = reader.option("versionAsOf", version).load(source)
        elif timestamp is not None:
            logger.info("Loading Delta with timestampAsOf={}", timestamp)
            dataframe = reader.option("timestampAsOf", timestamp).load(source)
        else:
            dataframe = reader.load(source)

        return self._apply_partition_filter(dataframe, config)


class PickleReader(SparkReaderBase):
    """Reader for Pickle format with built-in memory safety."""

    DEFAULT_MAX_RECORDS = 10000
    ABSOLUTE_MAX_RECORDS = 1_000_000

    def read(self, source: str, config: Dict[str, Any]) -> Any:
        """Read Pickle data from source."""
        if not config.get("allow_untrusted_pickle", False):
            raise ReadOperationError(
                "Reading pickle requires allow_untrusted_pickle=True due to security risks (arbitrary code execution)."
            ) from None

        use_pandas = config.get("use_pandas", False)
        spark = self._ctx_spark()

        if spark is None or use_pandas:
            return self._read_local_pickle(source, config)
        return self._read_distributed_pickle(source, config)

    def _read_local_pickle(self, source: str, config: Dict[str, Any]) -> Any:
        """Read pickle file locally."""
        try:
            with open(source, "rb") as file_handle:
                data = pickle.load(file_handle)
        except FileNotFoundError:
            raise ReadOperationError(f"Pickle file not found: {source}") from None
        except (IOError, OSError) as error:
            raise ReadOperationError(f"Failed to read pickle file {source}: {error}") from error

        if not config.get("use_pandas", False):
            try:
                import pandas as pd  # type: ignore

                if isinstance(data, pd.DataFrame):
                    spark = self._ctx_spark()
                    if spark is not None:
                        return spark.createDataFrame(data)
            except Exception:
                pass
        return data

    def _read_distributed_pickle(self, source: str, config: Dict[str, Any]) -> Any:
        """Read pickle files using Spark distributed processing with memory safety."""
        spark = self._ctx_spark()
        to_dataframe = config.get("to_dataframe", True)

        max_records = self._get_safe_max_records(config)

        logger.info("Reading distributed pickle with max_records={}", max_records)

        try:
            binary_file_dataframe = spark.read.format("binaryFile").load(source)

            if max_records and max_records > 0:
                logger.info(
                    "Limiting distributed pickle read to {} records to prevent driver OOM. "
                    "(Override with config['max_records']=0 to read all)",
                    max_records,
                )
                binary_file_dataframe = binary_file_dataframe.limit(max_records)
        except Exception as error:
            raise ReadOperationError(
                f"binaryFile datasource is unavailable; cannot read pickle(s): {error}"
            ) from error

        try:
            rdd = binary_file_dataframe.select("content").rdd.map(
                lambda row: pickle.loads(bytes(row[0]))
            )
        except Exception as error:
            raise ReadOperationError(f"Failed to prepare RDD for unpickling: {error}") from error

        if not to_dataframe:
            try:
                return rdd.collect()
            except Exception as error:
                raise ReadOperationError(f"Failed to collect unpickled objects: {error}") from error

        try:
            return spark.createDataFrame(rdd)
        except Exception as error:
            raise ReadOperationError(
                f"Failed to create DataFrame from pickled objects. "
                f"Ensure pickled objects are dicts/Rows or set to_dataframe=False. Error: {error}"
            ) from error

    def _get_safe_max_records(self, config: Dict[str, Any]) -> int:
        """Calculate safe max_records value with validation and warnings."""
        try:
            raw_max = int(config.get("max_records", -1))
        except (ValueError, TypeError):
            raw_max = -1

        if raw_max < 0:
            logger.warning(
                "No 'max_records' specified for distributed pickle read. "
                "Applying default limit of {} records to avoid driver OOM. "
                "Set config['max_records']=0 to read all, or a positive integer to customize.",
                self.DEFAULT_MAX_RECORDS,
            )
            return self.DEFAULT_MAX_RECORDS
        elif raw_max == 0:
            logger.critical(
                "Reading ALL pickle records without limit (max_records=0). "
                "This may cause driver Out-Of-Memory errors with large datasets. "
                "Consider setting a reasonable limit or increasing driver memory."
            )
            return 0  # no limit
        elif raw_max > self.ABSOLUTE_MAX_RECORDS:
            logger.error(
                "Requested max_records={} exceeds absolute limit of {}. "
                "Using limit of {} to prevent OOM.",
                raw_max,
                self.ABSOLUTE_MAX_RECORDS,
                self.ABSOLUTE_MAX_RECORDS,
            )
            return self.ABSOLUTE_MAX_RECORDS
        else:
            return raw_max


class AvroReader(SparkReaderBase):
    """Reader for Avro format."""

    def read(self, source: str, config: Dict[str, Any]) -> Any:
        return self._spark_read("avro", source, config)


class ORCReader(SparkReaderBase):
    """Reader for ORC format."""

    def read(self, source: str, config: Dict[str, Any]) -> Any:
        return self._spark_read("orc", source, config)


class XMLReader(SparkReaderBase):
    """Reader for XML format."""

    def read(self, source: str, config: Dict[str, Any]) -> Any:
        row_tag = config.get("rowTag", "row")
        spark = self._ctx_spark()
        if spark is None:
            raise ReadOperationError(
                f"Spark session is not available in context; cannot read XML from {source}"
            ) from None
        try:
            # Validate XML package availability
            _xml_package_check = spark._jvm.com.databricks.spark.xml
            logger.warning(f"availability: {_xml_package_check}")
        except Exception as error:
            raise ConfigurationError(
                "XML reader requires the com.databricks:spark-xml package. Install the jar or add --packages com.databricks:spark-xml:latest_2.12"
            ) from error
        logger.info("Reading XML file with row tag '{}': {}", row_tag, source)
        return (
            spark.read.format("com.databricks.spark.xml")
            .option("rowTag", row_tag)
            .options(**config.get("options", {}))
            .load(source)
        )


class QueryReader(BaseIO):
    """Reader for executing SQL queries in Spark."""

    def read(self, _source: str, config: Dict[str, Any]) -> Any:
        """Execute SQL query and return results."""
        try:
            query = (config or {}).get("query")
            if not query or not str(query).strip():
                raise ConfigurationError(
                    "Query format specified without SQL query or query is empty"
                ) from None

            if not self._spark_available():
                raise ReadOperationError("Spark session is required to execute queries") from None

            sanitized = self.sanitize_sql_query(str(query))

            spark = self._ctx_spark()
            return spark.sql(sanitized)

        except ConfigurationError as error:
            raise ReadOperationError(str(error)) from error
        except ReadOperationError:
            raise
        except Exception as error:
            raise ReadOperationError(f"Failed to execute query: {error}") from error
