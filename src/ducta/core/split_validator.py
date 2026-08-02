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

from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore


class SplitValidationError(Exception):
    """Raised when split validation fails."""

    pass


# Kept in sync with ducta.mlrun.split.VALID_METHODS — the actual runtime
# implementation this preflight check exists to catch mismatches for.
VALID_METHODS = ("random", "stratified", "temporal", "group")


def validate_split_config(split_config: Dict[str, Any], dataset_size: int) -> None:
    """Validate split configuration before execution."""
    method = split_config.get("method", "random")
    test_size = split_config.get("test_size", 0.2)
    val_size = split_config.get("val_size")

    if method not in VALID_METHODS:
        raise SplitValidationError(f"Unknown split method '{method}'. Valid: {VALID_METHODS}")

    if not 0 < test_size < 1:
        raise SplitValidationError(f"test_size must be in (0, 1), got {test_size}")

    if val_size is not None:
        if not 0 < val_size < 1:
            raise SplitValidationError(f"val_size must be in (0, 1), got {val_size}")
        if val_size + test_size >= 1:
            raise SplitValidationError(
                f"val_size + test_size must be < 1, got {val_size} + {test_size} = {val_size + test_size}"
            )

    min_test_rows = max(1, int(dataset_size * test_size))
    min_train_rows = max(1, dataset_size - min_test_rows)

    if min_train_rows < 2:
        logger.warning(
            f"Split results in {min_train_rows} train rows (test_size={test_size}, "
            f"dataset_size={dataset_size}). May be too small for model training."
        )

    if method == "stratified":
        stratify_col = split_config.get("stratify_col")
        if not stratify_col:
            raise SplitValidationError(
                "method='stratified' requires 'stratify_col' (target label column)"
            )

    elif method == "temporal":
        time_col = split_config.get("time_col")
        if not time_col:
            raise SplitValidationError(
                "method='temporal' requires 'time_col' (timestamp column). "
                "This is critical to prevent look-ahead bias."
            )

    elif method == "group":
        group_col = split_config.get("group_col")
        if not group_col:
            raise SplitValidationError(
                "method='group' requires 'group_col' (entity identifier). "
                "Each entity will appear in only one of train/test."
            )

    logger.info(
        "Split config validated: method={}, test_size={}, val_size={}, "
        "dataset_size={}, min_train_rows={}",
        method,
        test_size,
        val_size,
        dataset_size,
        min_train_rows,
    )


def log_split_leakage_checks(
    train_data: Any,
    test_data: Any,
    adapter_class: Any,
    time_col: Optional[str] = None,
    group_col: Optional[str] = None,
) -> List[str]:
    """Post-split validation: check for common data leakage patterns."""
    warnings = []
    train_adapter = adapter_class(train_data)
    test_adapter = adapter_class(test_data)

    train_size = train_adapter.count()
    test_size = test_adapter.count()

    if train_size < 10:
        warnings.append(
            f"Train set has only {train_size} rows; may be too small for reliable models."
        )

    if test_size < 5:
        warnings.append(f"Test set has only {test_size} rows; statistical power is low.")

    if time_col:
        try:
            train_min, train_max = train_adapter.min_max(time_col)
            test_min, test_max = test_adapter.min_max(time_col)

            if train_max is not None and test_min is not None:
                if train_max > test_min:
                    warnings.append(
                        f"LEAKAGE: train.{time_col}.max ({train_max}) > test.{time_col}.min ({test_min}). "
                        "Time ranges overlap! Check temporal split correctness."
                    )
        except Exception as e:
            logger.debug(f"Could not validate temporal split: {e}")

    if group_col:
        try:
            train_groups = set(train_adapter.distinct_values(group_col, limit=None))
            test_groups = set(test_adapter.distinct_values(group_col, limit=None))
            overlap = train_groups & test_groups

            if overlap:
                warnings.append(
                    f"LEAKAGE: {len(overlap)} group(s) appear in BOTH train and test: {list(overlap)[:5]}... "
                    "Group split failed; entities not properly isolated."
                )
        except Exception as e:
            logger.debug(f"Could not validate group split: {e}")

    for warning in warnings:
        logger.warning(warning)

    return warnings


def document_split_semantics(split_config: Dict[str, Any]) -> str:
    """Return human-readable documentation of split semantics for this config."""
    method = split_config.get("method", "random")
    test_size = split_config.get("test_size", 0.2)
    val_size = split_config.get("val_size")

    docs = [
        f"SPLIT SEMANTICS ({method.upper()}):",
        f"  test_size={test_size} ({test_size * 100:.1f}%)",
    ]

    if val_size:
        docs.append(f"  val_size={val_size} ({val_size * 100:.1f}%)")

    if method == "random":
        docs.append("  • Shuffles rows randomly; assumes no temporal or entity dependencies.")
        docs.append("    ⚠️ WARNING: Use only if data is i.i.d. (no time/user ordering)")

    elif method == "stratified":
        col = split_config.get("stratify_col", "?")
        docs.append(f"  • Maintains distribution of '{col}' in both train and test.")
        docs.append("    ✓ Recommended for imbalanced classification.")

    elif method == "temporal":
        col = split_config.get("time_col", "?")
        docs.append(f"  • Time-forward split on '{col}'.")
        docs.append(f"    Train: all rows with {col} <= cutoff")
        docs.append(f"    Test: all rows with {col} > cutoff")
        docs.append("    ✓ Prevents look-ahead bias.")

    elif method == "group":
        col = split_config.get("group_col", "?")
        docs.append(f"  • Each group ('{col}') appears in exactly one of train or test.")
        docs.append("    ✓ Use for user/item/entity data to avoid leakage.")

    docs.append("\n  IMPORTANT: Train node must apply split BEFORE preprocessing!")
    docs.append("  See ducta.core.split_validator for examples.")

    return "\n".join(docs)
