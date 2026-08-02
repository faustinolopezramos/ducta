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

from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.check.core import (
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    register_check,
)


class _BaseReferentialIntegrityCheck(BaseQualityCheck):
    """Shared implementation for referential integrity checks."""

    def run(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute referential integrity check."""
        try:
            if not getattr(config, "enabled", True):
                return self._create_result(True, "Check disabled")

            column = config.column if hasattr(config, "column") else None
            reference_dataset = (
                config.reference_dataset if hasattr(config, "reference_dataset") else None
            )
            reference_column = (
                config.reference_column if hasattr(config, "reference_column") else None
            )
            allow_null = config.allow_null if hasattr(config, "allow_null") else False

            if not column or not reference_dataset or not reference_column:
                return self._create_result(
                    False,
                    "Missing required config: column, reference_dataset, reference_column",
                    {},
                )

            ref_adapter = self._get_context_adapter(reference_dataset, context_datasets)
            if ref_adapter is None:
                return self._create_result(
                    False,
                    f"Reference dataset '{reference_dataset}' not available",
                    {},
                )

            try:
                violations_count = adapter.anti_join(
                    column, ref_adapter, reference_column, allow_null=allow_null
                )

                if violations_count > 0:
                    return self._create_result(
                        False,
                        f"Referential integrity violation: {violations_count} row(s) "
                        f"in '{column}' not found in '{reference_dataset}.{reference_column}'",
                        {
                            "violations_count": violations_count,
                            "allow_null": allow_null,
                        },
                    )

                return self._create_result(
                    True,
                    "All foreign key values exist in reference table",
                    {},
                )
            except Exception as e:
                logger.exception(f"Error in referential integrity check: {e}")
                return self._create_result(
                    False, f"Check execution failed: {str(e)}", {"error": str(e)}
                )

        except Exception as e:
            logger.exception(f"Error executing referential integrity check: {e}")
            return self._create_result(
                False, f"Check execution failed: {str(e)}", {"error": str(e)}
            )


@register_check("cross_table_referential")
class CrossTableReferentialIntegrityCheck(_BaseReferentialIntegrityCheck):
    """Validates foreign key constraints across tables (post-execution check)."""

    def __init__(self) -> None:
        super().__init__("cross_table_referential", CheckSeverity.ERROR)


@register_check("dataset_completeness")
class DatasetCompletenessCheck(BaseQualityCheck):
    """Validates coverage: all IDs from one dataset exist in another."""

    def __init__(self) -> None:
        super().__init__("dataset_completeness", CheckSeverity.ERROR)

    def run(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute dataset completeness check."""
        try:
            if not getattr(config, "enabled", True):
                return self._create_result(True, "Check disabled")

            column = config.column if hasattr(config, "column") else None
            reference_dataset = (
                config.reference_dataset if hasattr(config, "reference_dataset") else None
            )
            reference_column = (
                config.reference_column if hasattr(config, "reference_column") else None
            )
            direction = config.direction if hasattr(config, "direction") else "a->b"
            distinct_limit = config.distinct_limit if hasattr(config, "distinct_limit") else None

            if not column or not reference_dataset or not reference_column:
                return self._create_result(
                    False,
                    "Missing required config: column, reference_dataset, reference_column",
                    {},
                )

            # Get reference adapter
            ref_adapter = self._get_context_adapter(reference_dataset, context_datasets)
            if ref_adapter is None:
                return self._create_result(
                    False,
                    f"Reference dataset '{reference_dataset}' not available",
                    {},
                )

            try:
                main_values = set(adapter.distinct_values(column, limit=distinct_limit))
                ref_values = set(
                    ref_adapter.distinct_values(reference_column, limit=distinct_limit)
                )

                a_to_b_missing = main_values - ref_values
                b_to_a_missing = ref_values - main_values

                details = {
                    "main_distinct_count": len(main_values),
                    "reference_distinct_count": len(ref_values),
                    "a_to_b_missing_count": len(a_to_b_missing),
                    "b_to_a_missing_count": len(b_to_a_missing),
                    "direction": direction,
                }

                failed = False
                messages = []

                if direction in ("a->b", "bidirectional") and a_to_b_missing:
                    failed = True
                    messages.append(
                        f"{len(a_to_b_missing)} values in main dataset not in reference"
                    )

                if direction in ("b->a", "bidirectional") and b_to_a_missing:
                    failed = True
                    messages.append(
                        f"{len(b_to_a_missing)} values in reference dataset not in main"
                    )

                if failed:
                    return self._create_result(
                        False,
                        f"Dataset completeness check failed: {'; '.join(messages)}",
                        details,
                    )

                return self._create_result(
                    True,
                    "Datasets are complete in specified direction(s)",
                    details,
                )
            except Exception as e:
                logger.exception(f"Error in completeness check: {e}")
                return self._create_result(
                    False, f"Check execution failed: {str(e)}", {"error": str(e)}
                )

        except Exception as e:
            logger.exception(f"Error executing dataset completeness check: {e}")
            return self._create_result(
                False, f"Check execution failed: {str(e)}", {"error": str(e)}
            )
