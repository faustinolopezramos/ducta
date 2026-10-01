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

Parameters of the built-in quality checks, as JSON-Schema fragments.

One table, read in three places: ``ducta config validate`` rejects a wrong
type or an unknown parameter *with its file and line*, ``ducta config schema``
publishes it so editors complete ``row_count: {min: ...}``, and tests assert it
agrees with each check's ``CONFIG_PARAMS``. A third-party check gets the same
treatment by declaring ``CONFIG_SCHEMA`` (a ``{param: fragment}`` mapping) on
its class; one that declares nothing is accepted as before.

Only the JSON-Schema keywords checked here are used: ``type``, ``enum``,
``minimum`` / ``maximum``, ``exclusiveMinimum`` and ``items``.
"""

from typing import Any, Dict, List, Optional

_STRINGS = {"type": "array", "items": {"type": "string"}}
_RATE = {"type": "number", "minimum": 0, "maximum": 1}
_BOUND = {"type": ["number", "string"]}


def _p(fragment: Dict[str, Any], description: str) -> Dict[str, Any]:
    return {**fragment, "description": description}


#: ``{check name: {parameter: JSON-Schema fragment}}`` for the built-in checks.
CHECK_PARAMS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "empty_dataset": {},
    "null_rate": {
        "columns": _p(_STRINGS, "Columns to check (default: all)"),
        "threshold": _p(_RATE, "Largest allowed share of nulls per column (default 0.05)"),
    },
    "schema": {
        "expected_columns": _p(_STRINGS, "Columns the dataset must have"),
        "expected_schema": _p(
            {"type": "object"}, "{column: type}; the columns it must have, with their types"
        ),
        "strict": _p({"type": "boolean"}, "Fail on columns that are not expected"),
    },
    "row_count": {
        "min": _p({"type": "integer", "minimum": 0}, "Fewest rows allowed"),
        "max": _p({"type": "integer", "minimum": 0}, "Most rows allowed"),
    },
    "duplicates": {
        "columns": _p(_STRINGS, "Columns that identify a row"),
        "max_duplicate_rate": _p(_RATE, "Largest allowed share of duplicate rows (default 0)"),
    },
    "range": {
        "column": _p({"type": "string"}, "The column to check"),
        "min": _p(_BOUND, "Smallest allowed value"),
        "max": _p(_BOUND, "Largest allowed value"),
        "min_val": _p(_BOUND, "Alias of min"),
        "max_val": _p(_BOUND, "Alias of max"),
    },
    "referential_integrity": {
        "column": _p({"type": "string"}, "Column in this dataset"),
        "reference_dataset": _p({"type": "string"}, "Dataset it must exist in"),
        "reference_column": _p({"type": "string"}, "Column in the reference dataset"),
        "allow_null": _p({"type": "boolean"}, "Nulls are not violations"),
    },
    "cross_table_referential": {
        "column": _p({"type": "string"}, "Column in this dataset"),
        "reference_dataset": _p({"type": "string"}, "Dataset it must exist in"),
        "reference_column": _p({"type": "string"}, "Column in the reference dataset"),
        "allow_null": _p({"type": "boolean"}, "Nulls are not violations"),
    },
    "schema_drift": {
        "baseline_schema": _p({"type": "object"}, "{column: type} to compare against"),
        "detect_missing_cols": _p({"type": "boolean"}, "Fail when a baseline column is gone"),
        "detect_new_cols": _p({"type": "boolean"}, "Fail when a column is new"),
        "allow_type_changes": _p({"type": "boolean"}, "Tolerate a changed column type"),
    },
    "anomaly_detection": {
        "columns": _p(_STRINGS, "Numeric columns to compare with their history"),
        "z_score_threshold": _p(
            {"type": "number", "exclusiveMinimum": 0}, "Standard deviations that make an outlier"
        ),
    },
    "incremental_volume": {
        "min_threshold_ratio": _p(_RATE, "Smallest share of the historical average to accept"),
        "min_historical_samples": _p({"type": "integer", "minimum": 1}, "Runs needed first"),
    },
    "freshness": {
        "column": _p({"type": "string"}, "Timestamp column"),
        "timestamp_column": _p({"type": "string"}, "Alias of column"),
        "max_age_hours": _p({"type": "number", "exclusiveMinimum": 0}, "Oldest allowed data"),
        "max_age_business_days": _p({"type": "integer", "minimum": 0}, "In business days"),
        "holidays": _p({"type": "array"}, "Dates that are not business days"),
        "weekends_included": _p({"type": "boolean"}, "Count weekends as business days"),
    },
    "drift_detection": {
        "columns": _p(_STRINGS, "Columns to compare with the baseline"),
        "jensen_shannon_threshold": _p(_RATE, "Largest allowed divergence (default 0.1)"),
        "use_scipy": _p({"type": "boolean"}, "Use SciPy for the divergence"),
        "min_categories": _p({"type": "integer", "minimum": 1}, "Fewest categories to compare"),
        "topk_categories": _p({"type": "integer", "minimum": 1}, "Categories kept per column"),
    },
    "statistical": {
        "test_type": _p({"type": "string"}, "The test to run (default shapiro)"),
        "columns": _p(_STRINGS, "Columns to test"),
        "alpha": _p({"type": "number", "exclusiveMinimum": 0, "maximum": 1}, "Significance level"),
        "min_samples": _p({"type": "integer", "minimum": 1}, "Fewest rows to run the test"),
        "max_rows": _p({"type": "integer", "minimum": 1}, "Sample size cap"),
    },
    "business_rules": {
        "rules": _p({"type": "array", "items": {"type": "string"}}, "One expression per rule"),
        "rule_type": _p({"type": "string", "enum": ["sql", "python"]}, "How rules are evaluated"),
        "max_failures_allowed": _p({"type": "integer", "minimum": 0}, "Violating rows tolerated"),
    },
    "dataset_completeness": {
        "column": _p({"type": "string"}, "Column in this dataset"),
        "reference_dataset": _p({"type": "string"}, "The dataset to compare with"),
        "reference_column": _p({"type": "string"}, "Column in the reference dataset"),
        "direction": _p(
            {"type": "string", "enum": ["a->b", "b->a", "bidirectional"]}, "Which side must cover"
        ),
        "distinct_limit": _p({"type": "integer", "minimum": 1}, "Cap on distinct values compared"),
    },
}

#: Keys every check entry accepts, next to its own parameters.
COMMON_PARAMS: Dict[str, Dict[str, Any]] = {
    "enabled": {"type": "boolean", "description": "false switches the check off"},
    "severity": {"type": "string", "description": "Overrides the check's own severity"},
    "type": {
        "type": "string",
        "description": "Check implementation, when it differs from the name",
    },
}

_TYPES = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def schema_for(
    name: str, check_class: Optional[type] = None
) -> Optional[Dict[str, Dict[str, Any]]]:
    """The declared parameters of check ``name``, or None when it declares none."""
    declared = getattr(check_class, "CONFIG_SCHEMA", None) if check_class is not None else None
    return declared if declared is not None else CHECK_PARAMS.get(name)


def _is(value: Any, type_name: str) -> bool:
    if type_name in ("number", "integer") and isinstance(value, bool):
        return False  # True is an int in Python, and never a threshold
    return isinstance(value, _TYPES[type_name])


def problems_in(value: Any, fragment: Dict[str, Any], label: str) -> List[str]:
    """What is wrong with ``value`` against one fragment (empty when it is fine)."""
    wanted = fragment.get("type")
    if wanted is not None:
        names = [wanted] if isinstance(wanted, str) else list(wanted)
        if not any(_is(value, n) for n in names):
            pretty = " or ".join(names)
            return [f"{label} must be {pretty}, got {type(value).__name__} ({value!r})"]
    if "enum" in fragment and value not in fragment["enum"]:
        return [f"{label} must be one of {fragment['enum']}, got {value!r}"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = fragment.get("minimum"), fragment.get("maximum")
        if lo is not None and value < lo:
            return [f"{label} must be >= {lo}, got {value!r}"]
        if hi is not None and value > hi:
            return [f"{label} must be <= {hi}, got {value!r}"]
        if "exclusiveMinimum" in fragment and value <= fragment["exclusiveMinimum"]:
            return [f"{label} must be > {fragment['exclusiveMinimum']}, got {value!r}"]
    if isinstance(value, (list, tuple)) and "items" in fragment:
        found: List[str] = []
        for i, item in enumerate(value):
            found += problems_in(item, fragment["items"], f"{label}[{i}]")
        return found
    return []


def json_schema_for_entry(name: str, params: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The editor schema of one check entry: ``true``/``false`` or a mapping of its parameters."""
    return {
        "anyOf": [
            {"type": "boolean"},
            {"type": "null"},
            {
                "type": "object",
                "properties": {**COMMON_PARAMS, **params},
                "additionalProperties": False,
            },
        ],
        "description": f"The '{name}' check",
    }
