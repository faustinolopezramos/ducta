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

import re
from datetime import datetime
from typing import Any, Dict, List

from loguru import logger  # type: ignore

from ducta.gate.exceptions import ConfigurationError, DataValidationError

DATAFRAME_EMPTY = "DataFrame is empty"
VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class ConfigValidator:
    """Validates configuration objects."""

    @staticmethod
    def validate_name_component(value: str, field_name: str = "component") -> str:
        """Validate a single path/name component (schema, table, artifact
        name, version, ...): non-empty and alphanumeric/underscore/hyphen
        only — rejects `..`, `/`, and anything else that could escape a
        directory built from it.
        """
        if not value or not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"Empty component in '{field_name}'")
        if not VALID_NAME_PATTERN.match(value):
            raise ConfigurationError(
                f"Invalid characters in '{field_name}': '{value}'. "
                "Use only alphanumeric, underscores, and hyphens."
            )
        return value

    def validate_output_key(self, output_key: str) -> Dict[str, str]:
        """Parse and validate output key format."""
        if not output_key or not isinstance(output_key, str):
            raise ConfigurationError("Output key must be a non-empty string")

        key_string = output_key.strip()
        if ":" in key_string:
            key_string = key_string.split(":", 1)[1].strip()

        parts = [part.strip() for part in key_string.replace("/", ".").split(".") if part.strip()]

        if len(parts) != 3:
            raise ConfigurationError(
                f"Invalid format: {output_key}. Must be schema.sub_folder.table_name or schema/sub_folder/table_name"
            )

        result = {"schema": parts[0], "sub_folder": parts[1], "table_name": parts[2]}

        for key, value in result.items():
            self.validate_name_component(value, key)

        logger.debug("Output key parsed: {} -> {}", output_key, result)
        return result

    @staticmethod
    def validate_date_format(date_str: str) -> bool:
        """Validate date format (YYYY-MM-DD)."""
        if not date_str or not isinstance(date_str, str):
            return False

        if not re.match(DATE_PATTERN, date_str):
            return False

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False


class DataValidator:
    """Validates data objects (DataFrames, etc.)."""

    def validate_dataframe(self, dataframe: Any, allow_empty: bool = False) -> None:
        """Validate that the DataFrame is not None and optionally not empty."""
        if dataframe is None:
            raise DataValidationError("DataFrame cannot be None")

        if allow_empty:
            return

        # Check Spark DataFrame
        if hasattr(dataframe, "isEmpty"):
            try:
                is_empty = dataframe.isEmpty()  # type: ignore[attr-defined]
            except Exception as e:
                # A real Spark failure here (lost executor, bad query, ...)
                # used to be swallowed and fall through to the pandas/polars
                # checks below (which this object isn't), silently returning
                # as if the DataFrame were validated — we genuinely don't
                # know whether it's empty, which is not the same as "it's
                # not empty".
                raise DataValidationError(f"Could not determine if DataFrame is empty: {e}") from e
            if is_empty:
                raise DataValidationError(DATAFRAME_EMPTY)
            return

        # Check Pandas DataFrame
        try:
            import pandas as pd  # type: ignore

            if isinstance(dataframe, pd.DataFrame):
                if dataframe.empty:
                    raise DataValidationError(DATAFRAME_EMPTY)
                return
        except ImportError:
            pass

        # Check Polars DataFrame
        try:
            import polars as pl  # type: ignore

            if isinstance(dataframe, pl.DataFrame):
                if dataframe.height == 0:
                    raise DataValidationError(DATAFRAME_EMPTY)
                return
        except ImportError:
            pass

    def validate_columns_exist(self, dataframe: Any, columns: List[str]) -> None:
        """Validate that specified columns exist in DataFrame."""
        if not hasattr(dataframe, "columns"):
            raise DataValidationError("Object does not have columns attribute")

        available_column_names = self._get_columns(dataframe)

        missing_columns = [column for column in columns if column not in available_column_names]
        if missing_columns:
            raise DataValidationError(
                f"Columns not found in DataFrame: {missing_columns}. Available columns: {available_column_names}"
            )

    @staticmethod
    def _get_columns(dataframe: Any) -> List[str]:
        """Extract column names from various DataFrame types."""
        try:
            return list(dataframe.columns)
        except Exception:
            pass

        try:
            if hasattr(dataframe, "schema") and hasattr(dataframe.schema, "names"):
                return list(dataframe.schema.names)  # type: ignore[attr-defined]
        except Exception:
            pass

        return []
