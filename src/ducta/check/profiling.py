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

Assay a dataset and propose the spec it already satisfies.

Every check in ``ducta.check`` asserts a threshold the user had to know in
advance. That is backwards for a dataset nobody has characterised yet: you
cannot write ``null_rate: 0.02`` until you know what the null rate *is*. This
module runs the same measurements the checks run, but reads them out instead of
comparing them, and emits a configuration in the shape ``ducta.check`` already
consumes — so a proposed spec is executable without translation.

Two rules the inference follows, both load-bearing:

* **A proposed spec must pass on the data it was inferred from.** Every bound is
  derived at or beyond what was observed. A spec that fails immediately teaches
  the user to distrust the tool.
* **Nothing is invented.** A check that needs another dataset or a business rule
  (``referential_integrity``, ``business_rules``, ``drift_detection``…) is left
  out and *named* in the generated file, rather than emitted with a guessed
  threshold that would look authoritative.

All measurement goes through :class:`ducta.check.core.DFAdapter`, so this works
on Spark, pandas and polars frames without a line of engine-specific code here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.check.core import DFAdapter

#: How far a proposed bound sits from what was observed.
STRICTNESS_LEVELS = ("strict", "balanced", "lax")
DEFAULT_STRICTNESS = "balanced"

#: Fraction of the observed row count proposed as ``row_count.min``. Even
#: "strict" leaves headroom: a row count is naturally variable, and a spec
#: asserting today's exact count fails on tomorrow's data, which makes it
#: useless rather than strict.
_ROW_COUNT_FLOOR = {"strict": 0.95, "balanced": 0.80, "lax": 0.50}

#: Headroom added to an observed null rate before proposing it as a threshold.
_NULL_RATE_HEADROOM = {"strict": 0.0, "balanced": 0.02, "lax": 0.05}

#: Ceiling on the distinct-value scan. Past this we report "unknown" rather than
#: collecting an unbounded set from a large frame.
DEFAULT_DISTINCT_CAP = 50_000

#: Checks this module can derive from a single dataset, and those it cannot.
INFERABLE_CHECKS = ("empty_dataset", "schema", "row_count", "null_rate", "range", "duplicates")
NOT_INFERABLE_CHECKS = (
    "business_rules",
    "referential_integrity",
    "cross_table_referential",
    "drift_detection",
    "schema_drift",
    "anomaly_detection",
    "incremental_volume",
    "dataset_completeness",
    "freshness",
    "statistical",
)

_NUMERIC_HINTS = ("int", "float", "double", "decimal", "long", "short", "byte", "number")
_TEMPORAL_HINTS = ("date", "time")
_BOOLEAN_HINTS = ("bool",)


def classify_dtype(dtype: str) -> str:
    """Map an engine-reported type string to a kind this module reasons about.

    ``DFAdapter.get_schema`` returns whatever the engine calls the type —
    ``int64`` on pandas, ``IntegerType()`` on Spark — so the comparison is on
    substrings rather than an enumeration nobody can keep complete.
    """
    lowered = (dtype or "").lower()
    # Order matters: a Spark ``TimestampType`` contains neither "int" nor
    # "float", but pandas' ``datetime64[ns]`` contains "64" and would match a
    # naive numeric test, so temporal is decided first.
    if any(hint in lowered for hint in _TEMPORAL_HINTS):
        return "temporal"
    if any(hint in lowered for hint in _BOOLEAN_HINTS):
        return "boolean"
    if any(hint in lowered for hint in _NUMERIC_HINTS):
        return "numeric"
    return "categorical"


@dataclass
class ColumnProfile:
    """What one pass over a column observed."""

    name: str
    dtype: str
    kind: str
    null_count: int = 0
    null_rate: float = 0.0
    #: None when the column had more distinct values than the scan cap, so
    #: "how many" is genuinely unknown rather than equal to the cap.
    distinct_count: Optional[int] = None
    is_key_candidate: bool = False
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    p01: Optional[float] = None
    p99: Optional[float] = None
    mean: Optional[float] = None
    stddev: Optional[float] = None
    top_values: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "kind": self.kind,
            "null_count": self.null_count,
            "null_rate": round(self.null_rate, 6),
            "distinct_count": self.distinct_count,
            "is_key_candidate": self.is_key_candidate,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "p01": self.p01,
            "p99": self.p99,
            "mean": self.mean,
            "stddev": self.stddev,
            "top_values": dict(self.top_values),
        }


@dataclass
class DatasetProfile:
    """The assay of one dataset."""

    dataset_name: str
    engine: str
    row_count: int
    columns: List[ColumnProfile] = field(default_factory=list)
    #: True when per-column statistics came from a sample. ``row_count`` is
    #: always the real count; the rest are estimates, and the generated spec
    #: says so rather than presenting them as exact.
    sampled: bool = False
    sample_rows: Optional[int] = None
    #: Columns whose measurement raised, with the reason. An assay that could
    #: not read a column must say which, not quietly omit it — the same
    #: principle the run certificate's ``evidence_gaps`` follows.
    gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "engine": self.engine,
            "row_count": self.row_count,
            "sampled": self.sampled,
            "sample_rows": self.sample_rows,
            "columns": [c.to_dict() for c in self.columns],
            "gaps": list(self.gaps),
        }


def profile_dataset(
    df: Any,
    *,
    dataset_name: str = "dataset",
    sample_rows: Optional[int] = None,
    distinct_cap: int = DEFAULT_DISTINCT_CAP,
) -> DatasetProfile:
    """Measure *df* column by column and return the assay.

    ``sample_rows`` bounds the cost on a large frame: the row count is always
    taken from the full dataset, and only the per-column statistics run against
    the sample. The profile records that it did so.
    """
    adapter = DFAdapter(df)
    row_count = adapter.count()

    profile = DatasetProfile(
        dataset_name=dataset_name,
        engine=adapter.engine,
        row_count=row_count,
    )

    stats_adapter = adapter
    if sample_rows and row_count > sample_rows:
        try:
            stats_adapter = DFAdapter(adapter.sample(sample_rows))
            profile.sampled = True
            profile.sample_rows = sample_rows
            logger.info(
                "Profiling '{}' from a {}-row sample of {} rows; per-column figures are estimates",
                dataset_name,
                sample_rows,
                row_count,
            )
        except Exception as e:  # noqa: BLE001 — sampling is an optimization
            logger.debug("Could not sample '{}', profiling in full: {}", dataset_name, e)

    stats_rows = stats_adapter.count() if profile.sampled else row_count
    schema = stats_adapter.get_schema()

    for column, dtype in schema.items():
        try:
            profile.columns.append(
                _profile_column(stats_adapter, column, dtype, stats_rows, distinct_cap)
            )
        except Exception as e:  # noqa: BLE001 — one unreadable column must not lose the rest
            profile.gaps.append(f"column '{column}': {e}")
            logger.warning("Could not profile column '{}': {}", column, e)

    if row_count == 0:
        logger.warning(
            "Dataset '{}' is empty; the proposed spec can only assert that it has columns",
            dataset_name,
        )
    return profile


def _profile_column(
    adapter: DFAdapter,
    column: str,
    dtype: str,
    row_count: int,
    distinct_cap: int,
) -> ColumnProfile:
    """Measure a single column. Numeric statistics run only on numeric columns."""
    kind = classify_dtype(dtype)
    null_count = adapter.null_count(column)
    profile = ColumnProfile(
        name=column,
        dtype=dtype,
        kind=kind,
        null_count=null_count,
        null_rate=(null_count / row_count) if row_count else 0.0,
    )

    distinct = _distinct_count(adapter, column, distinct_cap)
    profile.distinct_count = distinct
    # A key candidate is unique *and* complete. Both halves matter: a column
    # full of distinct values but carrying nulls is not something to key on.
    profile.is_key_candidate = (
        distinct is not None and row_count > 0 and distinct == row_count and null_count == 0
    )

    if kind == "numeric" and row_count > 0 and null_count < row_count:
        _measure_numeric(adapter, column, profile)
    elif kind in ("categorical", "boolean") and row_count > 0:
        try:
            profile.top_values = {
                str(k): int(v) for k, v in adapter.value_counts(column, 10).items()
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not read top values for '{}': {}", column, e)

    return profile


def _distinct_count(adapter: DFAdapter, column: str, cap: int) -> Optional[int]:
    """Exact distinct count, or None when it exceeded *cap*.

    Asking for ``cap + 1`` values is what makes the answer honest: getting fewer
    back means the count is exact, and getting the full request back means only
    that there are at least that many — which is not a count, so None is
    returned rather than the cap masquerading as one.
    """
    try:
        values = adapter.distinct_values(column, limit=cap + 1)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not count distinct values for '{}': {}", column, e)
        return None
    return len(values) if len(values) <= cap else None


def _measure_numeric(adapter: DFAdapter, column: str, profile: ColumnProfile) -> None:
    """Fill in the numeric statistics, each guarded on its own."""
    try:
        profile.minimum, profile.maximum = adapter.min_max(column)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not read min/max for '{}': {}", column, e)
    try:
        profile.p01 = adapter.percentile(column, 1.0)
        profile.p99 = adapter.percentile(column, 99.0)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not read percentiles for '{}': {}", column, e)
    try:
        profile.mean, profile.stddev = adapter.mean_std(column)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not read mean/stddev for '{}': {}", column, e)


def infer_spec(profile: DatasetProfile, strictness: str = DEFAULT_STRICTNESS) -> Dict[str, Any]:
    """Propose the checks *profile* already satisfies, as a ``{"checks": {...}}`` dict.

    The shape is the one ``ValidationPhaseRunner`` consumes, so the result runs
    as-is. Where a check takes a single column (``range``), one entry per column
    is emitted using the ``type`` key that ``QualityCheckEntrySchema`` provides
    for exactly this.
    """
    if strictness not in STRICTNESS_LEVELS:
        logger.warning(
            "Unknown strictness {!r}; expected one of {}. Using {!r}.",
            strictness,
            ", ".join(STRICTNESS_LEVELS),
            DEFAULT_STRICTNESS,
        )
        strictness = DEFAULT_STRICTNESS

    checks: Dict[str, Any] = {"empty_dataset": {"enabled": True}}

    columns = [c.name for c in profile.columns]
    if columns:
        checks["schema"] = {"enabled": True, "expected_columns": columns}

    if profile.row_count > 0:
        floor = int(profile.row_count * _ROW_COUNT_FLOOR[strictness])
        checks["row_count"] = {"enabled": True, "min": max(1, floor)}

    _add_null_rate_checks(checks, profile, strictness)
    _add_range_checks(checks, profile, strictness)
    _add_duplicate_checks(checks, profile)

    return {"checks": checks}


def _add_null_rate_checks(checks: Dict[str, Any], profile: DatasetProfile, strictness: str) -> None:
    """One grouped entry for the complete columns, one entry per column with nulls."""
    complete = [c.name for c in profile.columns if c.null_count == 0]
    if complete:
        checks["null_rate"] = {"enabled": True, "columns": complete, "threshold": 0.0}

    headroom = _NULL_RATE_HEADROOM[strictness]
    for column in profile.columns:
        if column.null_count == 0:
            continue
        # Rounded *up*, so the proposed threshold can never sit below what was
        # measured — the spec has to pass on the data it came from.
        threshold = min(1.0, _ceil_to(column.null_rate + headroom, 4))
        checks[f"null_rate_{column.name}"] = {
            "type": "null_rate",
            "enabled": True,
            "columns": [column.name],
            "threshold": threshold,
        }


def _add_range_checks(checks: Dict[str, Any], profile: DatasetProfile, strictness: str) -> None:
    """A range entry per numeric column. ``lax`` widens to the p01–p99 band."""
    for column in profile.columns:
        if column.kind != "numeric" or column.minimum is None or column.maximum is None:
            continue
        low, high = column.minimum, column.maximum
        if strictness == "lax" and column.p01 is not None and column.p99 is not None:
            # Deliberately *outside* the observed extremes, never inside them:
            # a band tighter than the data would reject the very rows it was
            # derived from.
            span = (column.p99 - column.p01) or abs(high - low) or 1.0
            low, high = low - span * 0.1, high + span * 0.1
        checks[f"range_{column.name}"] = {
            "type": "range",
            "enabled": True,
            "column": column.name,
            "min": _round(low),
            "max": _round(high),
        }


def _add_duplicate_checks(checks: Dict[str, Any], profile: DatasetProfile) -> None:
    """Propose a uniqueness check only where uniqueness was actually observed."""
    keys = [c.name for c in profile.columns if c.is_key_candidate]
    if not keys:
        return
    checks["duplicates"] = {
        "enabled": True,
        "columns": keys,
        "max_duplicate_rate": 0.0,
    }


def _ceil_to(value: float, digits: int) -> float:
    import math

    factor = 10**digits
    return math.ceil(value * factor) / factor


def _round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return value


def spec_to_yaml(
    profile: DatasetProfile,
    spec: Dict[str, Any],
    strictness: str = DEFAULT_STRICTNESS,
) -> str:
    """Render *spec* as YAML annotated with where each bound came from.

    Written by hand rather than through ``yaml.dump`` because the comments are
    the point: a generated threshold the user cannot trace back to an
    observation is a number they have to either trust blindly or delete. The
    header also names the checks that were *not* inferred, so their absence
    reads as a decision rather than an oversight.
    """
    lines: List[str] = [
        f"# Spec proposed by `ducta profile` for '{profile.dataset_name}'.",
        "#",
        "# These bounds describe the data as it was on this run - they are a starting",
        "# point to review, not a contract to accept unread. Every one of them is set",
        "# at or beyond what was measured, so this spec passes on the data it came from;",
        "# tighten what you know should be tighter.",
        "#",
        f"#   rows observed : {profile.row_count}",
        f"#   engine        : {profile.engine}",
        f"#   strictness    : {strictness}",
    ]
    if profile.sampled:
        lines.append(
            f"#   sampled       : yes ({profile.sample_rows} rows) - per-column figures "
            "below are estimates"
        )
    if profile.gaps:
        lines.append("#   NOT MEASURED  : " + "; ".join(profile.gaps))
    lines += [
        "#",
        "# Not inferable from one dataset alone, so deliberately absent rather than",
        "# guessed - add them by hand where they apply:",
        "#   " + ", ".join(NOT_INFERABLE_CHECKS),
        "",
        "checks:",
    ]

    by_column = {c.name: c for c in profile.columns}
    for name, config in spec.get("checks", {}).items():
        note = _provenance_note(name, config, profile, by_column)
        if note:
            lines.append(f"  # {note}")
        lines.append(f"  {name}:")
        for key, value in config.items():
            lines.append(f"    {key}: {_yaml_scalar(value)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _provenance_note(
    name: str,
    config: Dict[str, Any],
    profile: DatasetProfile,
    by_column: Dict[str, ColumnProfile],
) -> str:
    """One line saying which observation produced this check."""
    if name == "row_count":
        return f"{profile.row_count} rows observed"
    if name == "schema":
        return f"{len(profile.columns)} columns observed"
    if name == "empty_dataset":
        return "always proposed: a dataset with no rows fails everything downstream"
    if name == "duplicates":
        columns = ", ".join(config.get("columns", []))
        return f"unique and non-null across all {profile.row_count} rows: {columns}"
    if name.startswith("null_rate"):
        columns = config.get("columns") or []
        if config.get("threshold") == 0.0:
            return f"no nulls observed in {len(columns)} column(s)"
        column = by_column.get(columns[0]) if columns else None
        if column is not None:
            return (
                f"{column.null_count}/{profile.row_count} nulls observed "
                f"({column.null_rate:.4f}); threshold left above it"
            )
    if name.startswith("range"):
        column = by_column.get(config.get("column", ""))
        if column is not None:
            return f"observed {column.minimum} to {column.maximum}"
    return ""


def _yaml_scalar(value: Any) -> str:
    """Render a scalar or flat list the way the config loaders expect to read it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_yaml_scalar(v) for v in value) + "]"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


__all__ = [
    "ColumnProfile",
    "DatasetProfile",
    "INFERABLE_CHECKS",
    "NOT_INFERABLE_CHECKS",
    "STRICTNESS_LEVELS",
    "classify_dtype",
    "infer_spec",
    "profile_dataset",
    "spec_to_yaml",
]
