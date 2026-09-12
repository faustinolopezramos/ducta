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

Structural quality checks.
"""

from typing import Any, ClassVar, Dict, FrozenSet, Optional

from loguru import logger

from ducta.check.checks.cross_table import _BaseReferentialIntegrityCheck
from ducta.check.core import (
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    register_check,
)


def _format_bounds(low: Any, high: Any) -> str:
    """Render an inclusive ``[low, high]`` interval, unset bounds as infinities.

    An explicit ``0`` is a real bound, but the previous ``low or '-∞'`` treated
    it as absent: ``min: 0`` printed ``-∞``, and ``row_count`` used ``'∞'`` for
    *both* ends, so a ``max: 0`` fell the same way. The check logic was right in
    every case — only the message named a bound it was not enforcing.
    """
    return f"[{'-∞' if low is None else low}, {'+∞' if high is None else high}]"


@register_check("empty_dataset")
class EmptyDatasetCheck(BaseQualityCheck):
    """Check if dataset is empty (0 rows)."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset()

    def __init__(self) -> None:
        super().__init__("empty_dataset", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute empty dataset check."""
        row_count = adapter.count()
        passed = row_count > 0

        return self._create_result(
            passed,
            f"Dataset has {row_count} rows" if passed else "Dataset is empty (0 rows)",
            {"row_count": row_count},
        )


@register_check("null_rate")
class NullRateCheck(BaseQualityCheck):
    """Check if null rate in columns exceeds threshold."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset({"columns", "threshold"})

    def __init__(self) -> None:
        super().__init__("null_rate", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute null rate check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        threshold = config.threshold if hasattr(config, "threshold") else 0.05
        columns = config.columns if hasattr(config, "columns") else None

        if not columns:
            columns = adapter.get_columns()

        total_rows = adapter.count()
        if total_rows == 0:
            return self._create_result(
                False,
                "Cannot calculate null rate on empty dataset",
                {},
            )

        failures = {}
        for col in columns:
            try:
                null_count = adapter.null_count(col)
                rate = null_count / total_rows

                if rate > threshold:
                    failures[col] = {
                        "null_count": null_count,
                        "rate": round(rate, 4),
                    }
            except Exception as e:
                logger.warning(f"Error checking nulls in column '{col}': {e}")

        if failures:
            return self._create_result(
                False,
                f"Null rate exceeds {threshold * 100:.1f}% in {len(failures)} column(s)",
                failures,
            )

        return self._create_result(
            True,
            f"All checked columns within null rate threshold {threshold * 100:.1f}%",
            {},
        )


@register_check("schema")
class SchemaCheck(BaseQualityCheck):
    """Check if expected columns exist in DataFrame."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset(
        {"expected_columns", "expected_schema", "strict"}
    )

    def __init__(self) -> None:
        super().__init__("schema", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute schema check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        expected = set(
            config.expected_columns
            if hasattr(config, "expected_columns")
            else list((config.expected_schema if hasattr(config, "expected_schema") else {}).keys())
        )
        actual = set(adapter.get_columns())
        strict = config.strict if hasattr(config, "strict") else False

        missing = expected - actual
        extra = actual - expected

        if missing:
            return self._create_result(
                False,
                f"Missing {len(missing)} expected column(s): {sorted(missing)}",
                {
                    "missing": sorted(missing),
                    "extra": sorted(extra),
                },
            )

        if strict and extra:
            return self._create_result(
                False,
                f"Found {len(extra)} unexpected column(s) in strict mode: {sorted(extra)}",
                {"extra": sorted(extra)},
                severity=CheckSeverity.WARNING,
            )

        if extra and not strict:
            logger.warning(f"Found extra columns (non-strict mode): {sorted(extra)}")

        return self._create_result(
            True,
            f"Schema matches expected {len(expected)} columns",
            {},
        )


@register_check("row_count")
class RowCountCheck(BaseQualityCheck):
    """Check if row count is within min/max bounds."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset({"max", "min"})

    def __init__(self) -> None:
        super().__init__("row_count", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute row count check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        min_rows = config.min if hasattr(config, "min") else None
        max_rows = config.max if hasattr(config, "max") else None
        count = adapter.count()

        if min_rows is not None and count < min_rows:
            return self._create_result(
                False,
                f"Row count {count} is below minimum {min_rows}",
                {"count": count, "min": min_rows, "max": max_rows},
            )

        if max_rows is not None and count > max_rows:
            return self._create_result(
                False,
                f"Row count {count} exceeds maximum {max_rows}",
                {"count": count, "min": min_rows, "max": max_rows},
            )

        return self._create_result(
            True,
            f"Row count {count} within {_format_bounds(min_rows, max_rows)}",
            {"count": count},
        )


@register_check("duplicates")
class DuplicateCheck(BaseQualityCheck):
    """Check for duplicate rows by given columns."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset({"columns", "max_duplicate_rate"})

    def __init__(self) -> None:
        super().__init__("duplicates", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute duplicate check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        columns = config.columns if hasattr(config, "columns") else []
        max_duplicate_rate = (
            config.max_duplicate_rate if hasattr(config, "max_duplicate_rate") else 0.0
        )

        if not columns:
            return self._create_result(True, "No columns specified for duplicate check", {})

        # Count duplicates
        if adapter.engine == "spark":
            # Single-pass approach: count total vs deduped together
            # using cache to avoid materialising the DF twice.
            df_cached = df.cache()
            try:
                total_count = df_cached.count()
                dedup_count = df_cached.dropDuplicates(subset=columns).count()
            finally:
                df_cached.unpersist()
            dup_count = total_count - dedup_count
        else:
            total_count = adapter.count()
            pdf = adapter.to_pandas()
            dup_count = pdf.duplicated(subset=columns).sum()

        if total_count == 0:
            dup_rate = 0.0
        else:
            dup_rate = dup_count / total_count

        if dup_rate > max_duplicate_rate:
            return self._create_result(
                False,
                f"Duplicate rate {dup_rate:.2%} exceeds threshold {max_duplicate_rate:.2%} "
                f"({int(dup_count)} rows by columns {columns})",
                {
                    "duplicates_count": int(dup_count),
                    "duplicate_rate": float(dup_rate),
                    "max_duplicate_rate": float(max_duplicate_rate),
                    "columns": columns,
                },
            )

        # Report the measured rate even on a pass. This branch used to say
        # "No duplicate rows found" and drop the count it had just computed,
        # so a dataset passing *within tolerance* was indistinguishable from
        # one with no duplicates at all — and the persisted report carried
        # nothing to trend the rate against over time.
        return self._create_result(
            True,
            f"{int(dup_count)} duplicate row(s) ({dup_rate:.2%}) by columns {columns}, "
            f"within threshold {max_duplicate_rate:.2%}",
            {
                "duplicates_count": int(dup_count),
                "duplicate_rate": float(dup_rate),
                "max_duplicate_rate": float(max_duplicate_rate),
                "columns": columns,
            },
        )


@register_check("range")
class RangeCheck(BaseQualityCheck):
    """Check if numeric column values are within min/max range."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset(
        {"column", "max", "max_val", "min", "min_val"}
    )

    def __init__(self) -> None:
        super().__init__("range", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute range check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        column = config.column if hasattr(config, "column") else None
        # 'min'/'max' are the documented keys (README.md, docs/quality.rst) and match
        # RowCountCheck's convention; 'min_val'/'max_val' are kept as a compatibility
        # alias for existing configs written against the original implementation.
        min_val = (
            config.min
            if hasattr(config, "min")
            else (config.min_val if hasattr(config, "min_val") else None)
        )
        max_val = (
            config.max
            if hasattr(config, "max")
            else (config.max_val if hasattr(config, "max_val") else None)
        )

        if not column:
            return self._create_result(False, "Range check requires 'column' parameter", {})

        actual_min, actual_max = adapter.min_max(column)

        if min_val is not None and actual_min is not None and actual_min < min_val:
            return self._create_result(
                False,
                f"Column '{column}' minimum {actual_min} is below {min_val}",
                {
                    "actual_min": actual_min,
                    "actual_max": actual_max,
                    "min_val": min_val,
                    "max_val": max_val,
                },
            )

        if max_val is not None and actual_max is not None and actual_max > max_val:
            return self._create_result(
                False,
                f"Column '{column}' maximum {actual_max} exceeds {max_val}",
                {
                    "actual_min": actual_min,
                    "actual_max": actual_max,
                    "min_val": min_val,
                    "max_val": max_val,
                },
            )

        return self._create_result(
            True,
            f"Column '{column}' values within range {_format_bounds(min_val, max_val)}",
            {
                "actual_min": actual_min,
                "actual_max": actual_max,
            },
        )


@register_check("referential_integrity")
class ReferentialIntegrityCheck(_BaseReferentialIntegrityCheck):
    """Check foreign key constraints: all values exist in reference dataset."""

    def __init__(self) -> None:
        super().__init__("referential_integrity", CheckSeverity.ERROR)


@register_check("schema_drift")
class SchemaDriftCheck(BaseQualityCheck):
    """Detect schema drift by comparing current schema against baseline from last successful run."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset(
        {"allow_type_changes", "baseline_schema", "detect_missing_cols", "detect_new_cols"}
    )

    def __init__(self) -> None:
        super().__init__("schema_drift", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute schema drift check.

        Compares the current DataFrame schema against a baseline schema.
        The baseline is typically stored from a previous successful run.

        Config options:
          - baseline_schema: Dict[col_name, col_type] to compare against
          - detect_missing_cols: bool (default=True) — fail if columns disappeared
          - detect_new_cols: bool (default=False) — fail if new columns appeared
          - allow_type_changes: bool (default=False) — allow type changes if True
        """
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        current_schema = adapter.get_schema()
        if not current_schema:
            return self._create_result(
                False,
                "Could not extract schema from DataFrame",
                {},
            )

        baseline_schema = getattr(config, "baseline_schema", None) or {}
        if not baseline_schema:
            return self._create_result(
                True,
                "No baseline schema defined (first run?); storing as baseline",
                {"current_columns": sorted(current_schema.keys())},
            )

        current_cols = set(current_schema.keys())
        baseline_cols = set(baseline_schema.keys())

        detect_missing = getattr(config, "detect_missing_cols", True)
        detect_new = getattr(config, "detect_new_cols", False)
        allow_type_changes = getattr(config, "allow_type_changes", False)

        missing_cols = baseline_cols - current_cols
        new_cols = current_cols - baseline_cols
        type_changes = {}

        for col in current_cols & baseline_cols:
            current_type = str(current_schema[col])
            baseline_type = str(baseline_schema.get(col, "unknown"))
            if current_type != baseline_type and not allow_type_changes:
                type_changes[col] = {
                    "baseline": baseline_type,
                    "current": current_type,
                }

        issues = []
        details = {
            "baseline_columns": sorted(baseline_cols),
            "current_columns": sorted(current_cols),
        }

        if missing_cols and detect_missing:
            issues.append(f"Columns missing: {sorted(missing_cols)}")
            details["missing_columns"] = sorted(missing_cols)

        if new_cols and detect_new:
            issues.append(f"New columns detected: {sorted(new_cols)}")
            details["new_columns"] = sorted(new_cols)

        if type_changes:
            issues.append(f"Type changes in {len(type_changes)} column(s)")
            details["type_changes"] = type_changes

        if issues:
            return self._create_result(
                False,
                f"Schema drift detected: {'; '.join(issues)}",
                details,
            )

        return self._create_result(
            True,
            f"Schema matches baseline ({len(current_cols)} columns, no type changes)",
            details,
        )
