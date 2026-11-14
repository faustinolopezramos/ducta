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

The rows a quality check objects to. Checks report counts and rates; when
something fails, the next question is "which rows?" — answered here for the
checks whose verdict is about rows, on the dataset as materialized.

SQL business rules are evaluated with sqlglot's executor over the sampled
rows (a SQL WHERE clause, the same text the Spark run evaluates).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

#: Checks whose failures are rows, and what makes a row fail.
SUPPORTED = ("null_rate", "range", "duplicates", "prediction_contract", "business_rules")


def _cols(value: Any) -> List[str]:
    return [value] if isinstance(value, str) else list(value or [])


def failing_mask(df: Any, check: str, params: Dict[str, Any]) -> Any:
    """A boolean Series: True where the row fails *check*. Raises ValueError when unsupported."""
    import pandas as pd

    if check == "null_rate":
        cols = _cols(params.get("columns"))
        return df[cols].isna().any(axis=1)
    if check in ("range", "prediction_contract"):
        col = params.get("column")
        lo = params.get("min", params.get("min_val"))
        hi = params.get("max", params.get("max_val"))
        s = pd.to_numeric(df[col], errors="coerce")
        mask = pd.Series(False, index=df.index)
        if lo is not None:
            mask |= s < float(lo)
        if hi is not None:
            mask |= s > float(hi)
        if check == "prediction_contract" and not params.get("allow_null", False):
            mask |= df[col].isna()
        return mask
    if check == "duplicates":
        cols = _cols(params.get("columns")) or list(df.columns)
        return df.duplicated(subset=cols, keep=False)
    if check == "business_rules":
        if (params.get("rule_type") or "sql") != "sql":
            raise ValueError("Only SQL business rules can show their failing rows here")
        from sqlglot.executor import execute

        records = json.loads(df.to_json(orient="records", date_format="iso"))
        for i, r in enumerate(records):
            r["__row"] = i
        failing: set = set()
        for rule in params.get("rules") or []:
            result = execute(f"SELECT __row FROM t WHERE NOT ({rule})", tables={"t": records})
            failing.update(row[0] for row in result.rows)
        return pd.Series([i in failing for i in range(len(df))], index=df.index)
    raise ValueError(f"'{check}' does not judge rows one by one")


def failing_rows(df: Any, check: str, params: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
    mask = failing_mask(df, check, params)
    bad = df[mask]
    return {
        "check": check,
        "failing": int(mask.sum()),
        "scanned": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "rows": json.loads(bad.head(limit).to_json(orient="records", date_format="iso")),
    }
