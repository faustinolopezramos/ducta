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

Temporal quality checks.
"""

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, FrozenSet, List, Optional

from loguru import logger

from ducta.check.core import (
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    register_check,
)


@register_check("anomaly_detection")
class AnomalyDetectionCheck(BaseQualityCheck):
    """Detects anomalies in numeric columns using z-score against historical baseline."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset({"columns", "z_score_threshold"})

    def __init__(self) -> None:
        super().__init__("anomaly_detection", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute anomaly detection check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        columns = config.columns if hasattr(config, "columns") else []
        if not columns:
            return self._create_result(True, "No columns configured for anomaly detection", {})

        missing = self._missing_columns_result(columns, adapter)
        if missing is not None:
            return missing

        z_score_threshold = (
            config.z_score_threshold if hasattr(config, "z_score_threshold") else 3.0
        )

        # Load historical baseline
        baseline = getattr(config, "_baseline", None)
        if not baseline:
            return self._create_result(
                True, "No baseline available, first run creates baseline", {}
            )

        anomalies = []
        details: Dict[str, Any] = {}
        column_errors: Dict[str, str] = {}
        columns_evaluated = 0

        for column in columns:
            try:
                mean, std = adapter.mean_std(column)
                if mean is None or std is None or std == 0:
                    continue

                baseline_mean = baseline.get(column, {}).get("mean")
                baseline_std = baseline.get(column, {}).get("std")

                if baseline_mean is None or baseline_std is None:
                    continue

                # Calculate z-score
                z_score = abs((mean - baseline_mean) / (baseline_std + 1e-9))
                columns_evaluated += 1

                details[column] = {
                    "current_mean": float(mean),
                    "baseline_mean": float(baseline_mean),
                    "z_score": float(z_score),
                    "threshold": float(z_score_threshold),
                }

                if z_score > z_score_threshold:
                    anomalies.append(
                        f"Column '{column}': z-score {z_score:.2f} > threshold {z_score_threshold}"
                    )
            except Exception as e:
                logger.exception(f"Error detecting anomaly in column '{column}': {e}")
                column_errors[column] = str(e)

        details["_columns_evaluated"] = columns_evaluated
        details["_columns_configured"] = len(columns)

        if anomalies:
            if column_errors:
                details["_column_errors"] = column_errors
            return self._create_result(
                False,
                f"Anomalies detected in {len(anomalies)} column(s): {'; '.join(anomalies)}",
                details,
            )

        errored = self._column_errors_result(column_errors, details)
        if errored is not None:
            return errored

        if columns_evaluated == 0:
            # `passed=True` here used to report a clean pass with zero
            # signal behind it (no baseline meant nothing was actually
            # checked) — `report.passed`/`errors_count` never reflected
            # that this check evaluated nothing. WARNING severity keeps
            # it from hard-failing the pipeline (not an ERROR), but
            # `passed=False` makes it visible instead of silently "ok".
            return self._create_result(
                False,
                f"No columns could be evaluated (0/{len(columns)} had a usable "
                "baseline/non-zero std) — inconclusive, not a pass",
                details,
                severity=CheckSeverity.WARNING,
            )

        return self._create_result(True, "No anomalies detected", details)


@register_check("incremental_volume")
class IncrementalVolumeCheck(BaseQualityCheck):
    """Detects incomplete data loads by comparing to historical average row count."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset(
        {"min_historical_samples", "min_threshold_ratio"}
    )

    def __init__(self) -> None:
        super().__init__("incremental_volume", CheckSeverity.WARNING)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute incremental volume check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        current_count = adapter.count()
        min_threshold_ratio = (
            config.min_threshold_ratio if hasattr(config, "min_threshold_ratio") else 0.5
        )
        min_historical_samples = (
            config.min_historical_samples if hasattr(config, "min_historical_samples") else 5
        )

        # Load historical history
        history = getattr(config, "_history", [])
        if len(history) < min_historical_samples:
            return self._create_result(
                True,
                f"Insufficient history samples ({len(history)} < {min_historical_samples})",
                {},
            )

        # Calculate historical average
        historical_counts = [h.get("row_count", 0) for h in history]
        historical_mean = (
            sum(historical_counts) / len(historical_counts) if historical_counts else 0
        )

        if historical_mean == 0:
            return self._create_result(True, "Historical mean is zero", {})

        ratio = current_count / historical_mean

        details = {
            "current_count": current_count,
            "historical_mean": float(historical_mean),
            "ratio": float(ratio),
            "min_threshold_ratio": float(min_threshold_ratio),
        }

        if ratio < min_threshold_ratio:
            return self._create_result(
                False,
                f"Row count {current_count} is {ratio:.2%} of historical mean {historical_mean:.0f} (threshold {min_threshold_ratio:.0%})",
                details,
            )

        return self._create_result(
            True,
            f"Row count {current_count} is {ratio:.2%} of historical mean (threshold {min_threshold_ratio:.0%})",
            details,
        )


@register_check("freshness")
class FreshnessCheck(BaseQualityCheck):
    """Validates data freshness (simple or business calendar mode)."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset(
        {
            "column",
            "holidays",
            "max_age_business_days",
            "max_age_hours",
            "timestamp_column",
            "weekends_included",
        }
    )

    def __init__(self) -> None:
        super().__init__("freshness", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute freshness check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        column = (
            config.column
            if hasattr(config, "column")
            else getattr(config, "timestamp_column", None)
        )
        if not column:
            return self._create_result(False, "Freshness check requires 'column' parameter", {})

        max_date = self._get_max_date_value(adapter, column)
        if max_date is None:
            return self._create_result(False, f"Column '{column}' has no dates", {})

        # Simple mode: max_age_hours
        if hasattr(config, "max_age_hours"):
            max_age_hours = config.max_age_hours
            now = datetime.now(timezone.utc)
            max_date_utc = (
                max_date.replace(tzinfo=timezone.utc) if max_date.tzinfo is None else max_date
            )
            age_hours = (now - max_date_utc).total_seconds() / 3600

            details = {
                "max_date": max_date.isoformat(),
                "age_hours": float(age_hours),
                "max_age_hours": float(max_age_hours),
            }

            if age_hours > max_age_hours:
                return self._create_result(
                    False,
                    f"Data age {age_hours:.1f}h exceeds threshold {max_age_hours}h",
                    details,
                )

            return self._create_result(
                True,
                f"Data is fresh: {age_hours:.1f}h old (max {max_age_hours}h)",
                details,
            )

        # Business calendar mode: max_age_business_days
        if hasattr(config, "max_age_business_days"):
            max_age_business_days = config.max_age_business_days
            holidays = config.holidays if hasattr(config, "holidays") else []
            weekends_included = (
                config.weekends_included if hasattr(config, "weekends_included") else False
            )

            now = datetime.now(timezone.utc)
            max_date_utc = (
                max_date.replace(tzinfo=timezone.utc) if max_date.tzinfo is None else max_date
            )

            business_days = self._count_business_days(
                max_date_utc.date(),
                now.date(),
                holidays,
                weekends_included,
            )

            details = {
                "max_date": max_date.isoformat(),
                "business_days_old": business_days,
                "max_age_business_days": max_age_business_days,
            }

            if business_days > max_age_business_days:
                return self._create_result(
                    False,
                    f"Data age {business_days} business days exceeds threshold {max_age_business_days}",
                    details,
                )

            return self._create_result(
                True,
                f"Data is fresh: {business_days} business days old",
                details,
            )

        return self._create_result(
            False,
            "Freshness check requires max_age_hours or max_age_business_days",
            {},
        )

    @staticmethod
    def _count_business_days(
        start_date: "datetime.date",
        end_date: "datetime.date",
        holidays: List[str],
        include_weekends: bool,
    ) -> int:
        """Count business days between two dates (excluding weekends/holidays)."""
        from datetime import timedelta as td

        # Parse holidays
        holiday_dates = set()
        for h in holidays:
            try:
                holiday_dates.add(datetime.fromisoformat(h).date())
            except (ValueError, TypeError):
                pass

        count = 0
        current = start_date
        while current < end_date:
            is_weekend = current.weekday() >= 5
            is_holiday = current in holiday_dates

            if not is_weekend or include_weekends:
                if not is_holiday:
                    count += 1

            current += td(days=1)

        return count

    @staticmethod
    def _get_max_date_value(adapter: DFAdapter, column: str) -> Optional[datetime]:
        """Get maximum date value from *column* without a full Pandas conversion.

        Uses the engine-native ``min_max`` aggregation (a single-pass query)
        instead of pulling the entire DataFrame to the driver just to compute
        ``max()``.  The result is normalised to a ``datetime`` object so the
        rest of the check is engine-agnostic.
        """
        try:
            _, max_val = adapter.min_max(column)
            if max_val is None:
                return None
            # Pandas Timestamp
            if hasattr(max_val, "to_pydatetime"):
                return max_val.to_pydatetime()
            # Already a datetime
            if isinstance(max_val, datetime):
                return max_val
            # Spark / Polars may return a date object — promote to datetime
            if hasattr(max_val, "year") and not isinstance(max_val, datetime):
                return datetime(max_val.year, max_val.month, max_val.day)
            # String fallback (ISO-8601)
            if isinstance(max_val, str):
                return datetime.fromisoformat(max_val)
            return max_val  # type: ignore[return-value]
        except Exception as e:
            logger.warning(f"Failed to get max date from column '{column}': {e}")
            return None
