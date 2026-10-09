"""Which rows a check fails on."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.api.services.failing_rows import failing_rows

DF = pd.DataFrame(
    {
        "id": [1, 2, 2, 4],
        "age": [15, 22, 17, None],
        "higher": ["yes", "maybe", "no", "yes"],
    }
)


def test_range_and_nulls():
    assert [
        r["id"] for r in failing_rows(DF, "range", {"column": "age", "min": 15, "max": 18})["rows"]
    ] == [2]
    out = failing_rows(DF, "null_rate", {"columns": ["age"]})
    assert out["failing"] == 1 and out["scanned"] == 4


def test_duplicates_keep_every_copy():
    assert failing_rows(DF, "duplicates", {"columns": ["id"]})["failing"] == 2


def test_sql_rules_find_the_rows_that_break_them():
    out = failing_rows(
        DF, "business_rules", {"rule_type": "sql", "rules": ["higher IN ('yes', 'no')"]}
    )
    assert [r["higher"] for r in out["rows"]] == ["maybe"]


def test_a_check_about_the_whole_dataset_says_so():
    with pytest.raises(ValueError, match="row_count"):
        failing_rows(DF, "row_count", {"min": 10})
