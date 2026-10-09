"""Diagnosing a failed run: what kind, where in the project's code, what changed."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.api.services.diagnosis import classify, diagnose, first_user_frame, what_changed


@pytest.mark.parametrize(
    "text, kind",
    [
        ("Quality gate 'quality_gate' blocked dataset 'x'", "quality_gate"),
        ("Missing credentials for ducta_connect", "infra"),
        ("java.lang.OutOfMemoryError: Java heap space", "infra"),
        ("AnalysisException: cannot resolve 'G4' given input columns", "data"),
        ("The project configuration is invalid", "config"),
        ("Traceback (most recent call last): KeyError: 'G3'", "code"),
        ("", "unknown"),
    ],
)
def test_classify(text, kind):
    assert classify(text) == kind


def test_the_innermost_frame_of_the_projects_own_code(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    tb = (
        "Traceback (most recent call last):\n"
        '  File "/env/lib/python3.13/site-packages/ducta/core/execution/runner.py", line 10, in run\n'
        f'  File "{root}/src/silver.py", line 42, in clean_student\n'
        f'  File "{root}/src/helpers.py", line 7, in _validate_range\n'
        '  File "/env/lib/python3.13/site-packages/pyspark/sql/column.py", line 99, in between\n'
        "KeyError: 'G3'\n"
    )
    assert first_user_frame(tb, root) == {
        "file": "src/helpers.py",
        "line": 7,
        "function": "_validate_range",
    }
    assert first_user_frame("no frames here", root) is None


def test_what_changed_names_code_data_and_config():
    ok = {
        "run_id": "ok1",
        "started_at": "t0",
        "config_fingerprint": "c1",
        "code": {"nodes": {"src.m.a": {"source_hash": "h1"}, "src.m.b": {"source_hash": "h2"}}},
        "inputs": {"raw": {"fingerprint": "f1"}, "other": {"fingerprint": "f2"}},
        "environment": {"git_commit": "abc"},
    }
    failed = {
        "config_fingerprint": "c1",
        "code": {
            "nodes": {"src.m.a": {"source_hash": "h1"}, "src.m.b": {"source_hash": "CHANGED"}}
        },
        "inputs": {"raw": {"fingerprint": "NEW"}, "other": {"fingerprint": "f2"}},
    }
    changed = what_changed(failed, ok)
    assert changed["code"] == ["src.m.b"]
    assert changed["data"] == ["raw"]
    assert changed["config"] is False
    assert changed["since_commit"] == "abc"


def test_diagnose_puts_it_together(tmp_path):
    result = diagnose(
        {"id": "e1", "status": "failed", "error_message": "Quality gate blocked dataset x"},
        [{"node_id": "silver.clean", "message": "1 ERROR failure(s)", "traceback": ""}],
        Path(tmp_path),
        None,
        None,
    )
    assert result["kind"] == "quality_gate"
    assert result["node"] == "silver.clean"
    assert result["what_changed"] is None
    assert any("quality report" in s for s in result["suggestions"])


def test_a_spark_column_error_is_data_even_with_java_in_the_trace():
    text = (
        "py4j.protocol.Py4JJavaError java.lang.Thread AnalysisException: [UNRESOLVED_COLUMN] `G4`"
    )
    assert classify(text) == "data"


def test_the_node_is_read_from_the_message_when_the_log_has_none():
    r = diagnose({"error_message": "node 'silver.clean' raised KeyError"}, [], None, None, None)
    assert r["node"] == "silver.clean"


def test_a_partial_run_does_not_blame_nodes_it_did_not_run():
    from ducta.api.services.diagnosis import what_changed

    last_ok = {
        "code": {"nodes": {"a": {"source_hash": "1"}, "b": {"source_hash": "2"}}},
        "inputs": {"x": {"fingerprint": "f"}, "y": {"fingerprint": "g"}},
    }
    failed = {"code": {"nodes": {"a": {"source_hash": "1"}}}, "inputs": {"x": {"fingerprint": "f"}}}
    changed = what_changed(failed, last_ok)
    assert changed["code"] == [] and changed["data"] == []
