"""Which rows a check fails on."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta_server.services.failing_rows import failing_rows

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


# ── 2026-11-20 security review: a rule is interpreted, never executed ──


def _payload(marker) -> str:
    # The request body that ran code in the server through sqlglot's executor
    # (it put a JSON path key unescaped into the Python it then eval'd).
    code = f"str(open('{marker}','w').write('owned'))".replace("'", "''")
    return f"JSON_EXTRACT(age, '$[\"'' + {code} + ''\"]') IS NULL"


def test_a_rule_crafted_to_run_code_is_refused_and_runs_nothing(tmp_path):
    marker = tmp_path / "owned.txt"
    with pytest.raises(ValueError, match="not evaluated here"):
        failing_rows(DF, "business_rules", {"rule_type": "sql", "rules": [_payload(marker)]})
    assert not marker.exists()


def test_sqlglot_executor_is_never_imported(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "sqlglot.executor", None)  # importing it now fails
    out = failing_rows(DF, "business_rules", {"rule_type": "sql", "rules": ["age <= 18"]})
    assert out["failing"] == 1


@pytest.mark.parametrize(
    "rule, failing_ids",
    [
        ("age IS NOT NULL", [4]),
        ("age BETWEEN 16 AND 30", [1]),
        ("higher NOT IN ('maybe')", [2]),
        ("higher LIKE 'y%' OR age < 16", [2, 2]),
        ("coalesce(age, 0) >= 0 AND length(trim(higher)) > 2", [2]),
        ("NOT (age > 20)", [2]),  # NULL age: the rule is NULL, the row does not break it
        ("10 / (age - 15) > 0", []),  # dividing by zero is NULL, as in Spark
        ("upper(higher) = 'YES'", [2, 2]),
    ],
)
def test_sql_rules_follow_sql_semantics(rule, failing_ids):
    out = failing_rows(DF, "business_rules", {"rule_type": "sql", "rules": [rule]})
    assert [r["id"] for r in out["rows"]] == failing_ids


@pytest.mark.parametrize(
    "rule, message",
    [
        ("age > (SELECT 1)", "subqueries"),
        ("t.age > 1", "names a table"),
        ("regexp_like(higher, 'x')", "not evaluated here"),
        ("missing = 1", "No column 'missing'"),
        ("age", "not a condition"),
        ("age > 1; DROP TABLE x", "security validation"),
    ],
)
def test_what_is_not_a_plain_row_rule_is_refused(rule, message):
    with pytest.raises(ValueError, match=message):
        failing_rows(DF, "business_rules", {"rule_type": "sql", "rules": [rule]})


def test_text_columns_compare_with_numbers_as_spark_does():
    # A CSV read without a schema: every column is text.
    df = pd.DataFrame({"amount": ["10", "-3", "n/a", None]})
    out = failing_rows(df, "business_rules", {"rule_type": "sql", "rules": ["amount > 0"]})
    assert [r["amount"] for r in out["rows"]] == ["-3"]  # 'n/a' and NULL: the rule is NULL
