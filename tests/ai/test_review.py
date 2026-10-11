"""Reviewing a node: what Ducta is sure of, and the model's findings checked against the code.

A finding of the model's reaches the person only when it points at something
real — a line of the node's function (quoted as it is) or a setting the node
has. These tests hold the review to that, and to changing nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.ai import review as rv
from ducta.ai.review import check_finding, load_review, review_facts, review_node, save_review

sys.path.insert(0, str(Path(__file__).parent))
from test_builder import FakeProvider, _project  # noqa: E402

CODE = """def clean(orders):
    rows = orders.collect()
    orders.write.parquet("/tmp/out")
    return orders
"""


def _node(tmp_path: Path, code: str = CODE, node_extra: str = "", catalog_extra: str = "") -> Path:
    root = _project(tmp_path)
    (root / "src" / "m.py").write_text(code)
    (root / "pipelines" / "etl.yaml").write_text(
        "nodes:\n  etl.clean:\n    run: src.m:clean\n    inputs: {orders: raw}\n"
        f"    outputs: [clean]\n{node_extra}"
    )
    if catalog_extra:
        (root / "catalog.yaml").write_text("raw: {format: csv, path: d/raw.csv}\n" + catalog_extra)
    return root


def _titles(found) -> list:
    return [(f.severity, f.title) for f in found]


# ── Ducta's own checks ───────────────────────────────────────────────────────


def test_ducta_finds_pulls_and_io_inside_the_function_with_their_lines(tmp_path):
    found = review_node(_node(tmp_path), "etl", "etl.clean", None).findings
    by_title = {f.title: f for f in found}
    pull = by_title["`collect()` brings every row to one machine"]
    assert (pull.file, pull.line, pull.code, pull.source) == (
        "src/m.py",
        2,
        "rows = orders.collect()",
        "ducta",
    )
    write = by_title["The function writes a DataFrame itself (`.write`)"]
    assert write.line == 3


def test_a_retried_node_that_appends_is_a_high_finding(tmp_path):
    root = _node(
        tmp_path,
        code="def clean(orders):\n    return orders\n",
        node_extra="    retry: 2\n",
        catalog_extra="clean: {format: parquet, path: d/clean, write: {mode: append}}\n",
    )
    found = review_node(root, "etl", "etl.clean", None).findings
    assert ("high", "A retried node appends: a retry can duplicate rows") in _titles(found)
    assert found[0].key == "retry"


def test_runs_near_the_timeout_are_reported_from_the_certificates(tmp_path, monkeypatch):
    root = _node(
        tmp_path,
        code="def clean(orders):\n    return orders\n",
        node_extra="    timeout_seconds: 100\n",
    )
    monkeypatch.setattr(rv, "_durations", lambda *a: [95.0, 40.0])
    found = review_node(root, "etl", "etl.clean", None).findings
    near = [f for f in found if f.key == "timeout_seconds"]
    assert near and "95 s of a 100 s limit" in near[0].detail


def test_dates_the_function_cannot_receive(tmp_path):
    root = _node(tmp_path, code="def clean(orders):\n    return orders\n")
    pipeline = root / "pipelines" / "etl.yaml"
    pipeline.write_text("requires_dates: true\n" + pipeline.read_text())
    found = review_node(root, "etl", "etl.clean", None).findings
    assert any(f.key == "requires_dates" and f.line == 1 for f in found)


def test_a_credential_in_the_code_is_a_security_finding(tmp_path):
    code = 'TOKEN = "ghp_0123456789abcdefghijklmnopqrstuvwxyz"\ndef clean(orders):\n    key = "sk-ant-0123456789abcdefghij"\n    return orders\n'
    found = review_node(_node(tmp_path, code=code), "etl", "etl.clean", None).findings
    assert any(f.area == "security" and f.severity == "high" for f in found)


def test_a_clean_node_has_nothing_to_report(tmp_path):
    root = _node(tmp_path, code="def clean(orders):\n    return orders.dropna()\n")
    assert review_node(root, "etl", "etl.clean", None).findings == []


def test_an_unknown_node_names_the_ones_there_are(tmp_path):
    with pytest.raises(Exception, match="its nodes: etl.clean"):
        review_facts(_node(tmp_path), "etl", "nope")


# ── the model's findings, checked ───────────────────────────────────────────


def test_a_finding_must_point_at_a_real_line_quoted_as_it_is(tmp_path):
    facts = review_facts(_node(tmp_path), "etl", "etl.clean")
    good = {
        "severity": "medium",
        "area": "code",
        "title": "x",
        "line": 3,
        "code": 'orders.write.parquet("/tmp/out")',
    }
    assert check_finding(good, facts).line == 3
    assert check_finding({**good, "line": 40}, facts) is None  # not in the function
    assert (
        check_finding({**good, "code": "orders.groupBy('region')"}, facts) is None
    )  # not on that line
    assert (
        check_finding({**good, "line": None, "code": None}, facts) is None
    )  # code finding, no place
    assert check_finding({**good, "severity": "urgent"}, facts) is None


def test_a_finding_about_settings_must_name_a_real_one(tmp_path):
    facts = review_facts(_node(tmp_path), "etl", "etl.clean")
    base = {"severity": "low", "area": "config", "title": "x"}
    assert check_finding({**base, "key": "timeout_seconds"}, facts).key == "timeout_seconds"
    assert check_finding({**base, "key": "settings.shuffle_partitions"}, facts) is not None
    assert check_finding({**base, "key": "max_memory_gb"}, facts) is None
    assert check_finding({**base, "key": "settings.turbo"}, facts) is None


ANSWER = """```yaml review
findings:
  - severity: high
    area: code
    title: Returns the input unchanged after writing it
    line: 4
    code: return orders
    detail: The write already happened; the output is the raw input.
    suggestion: Return the transformed frame.
  - severity: medium
    area: performance
    title: Hallucinated line
    line: 99
    code: df.cache()
  - severity: low
    area: performance
    title: collect again
    line: 2
  - severity: low
    area: config
    title: Unknown knob
    key: turbo_mode
```
"""


def test_the_models_findings_are_kept_only_when_real_and_new(tmp_path):
    root = _node(tmp_path)
    provider = FakeProvider(ANSWER)
    result = review_node(root, "etl", "etl.clean", provider, note="it got slow")
    ai = [f for f in result.findings if f.source == "ai"]
    assert [f.title for f in ai] == ["Returns the input unchanged after writing it"]
    assert result.dropped == 2  # line 99 and turbo_mode; line 2 repeats Ducta's, not counted
    assert result.model == "fake"
    sent = provider.calls[0][0].content
    assert "   2  " in sent and "rows = orders.collect()" in sent  # the numbered code
    assert "Ducta already found" in sent and "it got slow" in sent
    assert result.findings[0].severity == "high"


def test_an_unreadable_answer_keeps_ductas_findings(tmp_path):
    result = review_node(_node(tmp_path), "etl", "etl.clean", FakeProvider("I think it is fine."))
    assert result.findings and all(f.source == "ducta" for f in result.findings)
    assert "could not be read" in result.notes


def test_a_review_changes_nothing_and_is_kept(tmp_path):
    root = _node(tmp_path)
    before = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
    result = review_node(root, "etl", "etl.clean", FakeProvider(ANSWER))
    assert {p: p.read_text() for p in root.rglob("*") if p.is_file()} == before
    save_review(root, result)
    again = load_review(root, "etl", "etl.clean")
    assert again is not None and again.to_dict() == result.to_dict()
    assert load_review(root, "etl", "other") is None


# ── the command ──────────────────────────────────────────────────────────────


def test_ducta_ai_review_without_a_model_and_failing_on_high(tmp_path, capsys):
    from ducta.console.commands.ai_cmds import AICommands

    root = _node(
        tmp_path,
        node_extra="    retry: 1\n",
        catalog_extra="clean: {format: parquet, path: d/clean, write: {mode: append}}\n",
    )
    args = SimpleNamespace(
        ai_command="review",
        pipeline="etl",
        node="etl.clean",
        env="dev",
        note=None,
        no_ai=True,
        fail_on="high",
        base_path=str(root),
        output_format="json",
    )
    assert AICommands.handle(args) == 3
    doc = json.loads(capsys.readouterr().out)
    assert doc["model"] is None and doc["findings"][0]["severity"] == "high"
    args.fail_on = None
    assert AICommands.handle(args) == 0
