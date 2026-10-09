"""Tests from a run: the generated test, and pytest results with file:line."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ducta.api.services.node_tests import render_test, run_tests
from ducta.api.services.node_tests import tests_for as covering_tests


def test_render_pandas_keyword_inputs():
    text = render_test(
        node="silver.clean", module="src.silver", function="clean",
        inputs={"orders": "bronze.orders"}, columns=["id", "amount"], fixtures="silver_clean",
        env="dev", spark=False, spark_fixture=False, positional=False,
    )  # fmt: skip
    compile(text, "t.py", "exec")
    assert "from src.silver import clean" in text
    assert 'out = clean(orders=pd.read_parquet(FIXTURES / "orders.parquet"))' in text
    assert "EXPECTED_COLUMNS = ['id', 'amount']" in text


def test_render_spark_without_a_project_fixture_brings_its_own():
    text = render_test(
        node="n", module="src.m", function="f", inputs={"bronze.a": "bronze.a"},
        columns=["x"], fixtures="n", env="dev", spark=True, spark_fixture=False, positional=True,
    )  # fmt: skip
    compile(text, "t.py", "exec")
    assert "def spark():" in text
    assert 'f(spark.read.parquet(str(FIXTURES / "bronze_a.parquet")))' in text


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "m.py").write_text(
        "def f(x):\n    return x + 1\n\n\ndef g(x):\n    raise ValueError('boom')\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n")
    (tmp_path / "tests" / "test_m.py").write_text(
        textwrap.dedent(
            """
            from src.m import f, g

            def test_f():
                assert f(1) == 2

            def test_g():
                g(1)
            """
        )
    )
    return tmp_path


def test_run_reports_outcomes_and_where_it_failed(project):
    result = run_tests(project, ["tests/test_m.py"])
    assert result["ok"] is False
    assert result["summary"] == {"passed": 1, "failed": 1}
    failed = next(t for t in result["tests"] if t["outcome"] == "failed")
    assert (failed["file"], failed["line"]) == ("src/m.py", 6)
    passed = next(t for t in result["tests"] if t["outcome"] == "passed")
    assert passed["file"] == "tests/test_m.py"


def test_tests_for_finds_files_that_call_the_function(project):
    assert covering_tests(project, "silver.f", "f") == ["tests/test_m.py"]
    assert covering_tests(project, "x", "nothing_calls_me") == []
