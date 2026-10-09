"""Code binding: a node's inputs against its function's parameters, from the syntax tree."""

from __future__ import annotations

from pathlib import Path

from ducta.api.repositories.v2_store import V2ProjectStore
from ducta.api.services.draft_validation import validate_draft


def _project(tmp_path: Path, fn_source: str) -> V2ProjectStore:
    (tmp_path / "ducta.yaml").write_text("version: 2\nproject: p\npaths: {input: d, output: d}\n")
    (tmp_path / "catalog.yaml").write_text(
        "raw: {format: csv, path: d/raw.csv}\nclean: {format: parquet, path: d/clean}\n"
    )
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "etl.yaml").write_text(
        "nodes:\n  etl.clean:\n    run: src.m:clean\n    inputs: {orders: raw}\n    outputs: [clean]\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(fn_source)
    store = V2ProjectStore.detect(tmp_path)
    assert store is not None
    return store


def _codes(store, drafts=None):
    """Code and configuration problems — governance notices are tested on their own."""
    return {
        (p.code, p.severity)
        for p in validate_draft(store, drafts or {})
        if p.source != "governance"
    }


def test_governance_notices_come_with_validation(tmp_path):
    problems = validate_draft(_project(tmp_path, "def clean(orders):\n    return orders\n"), {})
    notices = [p for p in problems if p.source == "governance"]
    assert notices and {p.severity for p in notices} == {"info"}


def test_a_matching_signature_has_no_problem(tmp_path):
    assert _codes(_project(tmp_path, "def clean(orders):\n    return orders\n")) == set()


def test_an_input_the_function_does_not_take(tmp_path):
    codes = _codes(_project(tmp_path, "def clean(df):\n    return df\n"))
    assert ("input_not_a_parameter", "error") in codes
    assert ("parameter_not_given", "warning") in codes


def test_kwargs_accepts_any_input(tmp_path):
    assert _codes(_project(tmp_path, "def clean(df=None, **kwargs):\n    return df\n")) == set()


def test_a_draft_of_the_source_is_what_is_checked(tmp_path):
    store = _project(tmp_path, "def clean(orders):\n    return orders\n")
    codes = _codes(store, {"src/m.py": "def other(orders):\n    return orders\n"})
    assert ("function_not_found", "error") in codes
    # … and nothing was written.
    assert "def clean" in (tmp_path / "src" / "m.py").read_text()
