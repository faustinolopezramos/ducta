"""Proposals (a node's checks, the project's descriptions) and run explanations.

The model proposes; Ducta writes. These tests hold Ducta to that: a proposal
only ever adds what it was asked for, keeps the file as its author wrote it,
and a quality check that fails on the measured data never reaches a draft.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ducta.ai import proposals
from ducta.ai.builder import load_draft, revise, save_draft
from ducta.ai.errors import AIConfigError
from ducta.ai.explain import (
    explain_failure,
    explanation_message,
    load_explanation,
    node_function,
    save_explanation,
)
from ducta.ai.proposals import QualityFacts, propose_docs, propose_quality, quality_assembler
from ducta.ai.yaml_edit import edit_yaml, mapping

sys.path.insert(0, str(Path(__file__).parent))
from test_builder import FakeProvider, _project  # noqa: E402

# ── editing YAML in place ────────────────────────────────────────────────────


def test_an_edit_keeps_comments_quotes_and_layout():
    text = (
        "# the orders\n"
        "nodes:\n"
        "  clean:   # cleans\n"
        '    run: "src.m:clean"\n'
        "    inputs: {orders: raw}\n"
        "\n"
        "  other:\n"
        "    run: src.m:other\n"
    )

    def put(doc):
        doc["nodes"]["clean"]["quality"] = mapping(
            {"row_count": {"min": 1}, "gate": {"max_errors": 0}}
        )

    out = edit_yaml(text, put)
    assert out.startswith("# the orders\nnodes:\n  clean:   # cleans\n")
    assert '    run: "src.m:clean"\n    inputs: {orders: raw}\n' in out
    assert "      row_count: {min: 1}\n      gate: {max_errors: 0}\n" in out
    assert "\n\n  other:\n" in out  # the blank line between nodes stays


# ── quality ──────────────────────────────────────────────────────────────────

FRAME = pd.DataFrame({"order_id": [1, 2, 3, 4], "amount": [10.0, 20.0, None, 40.0]})


def _facts(root: Path, frame=FRAME) -> QualityFacts:
    return QualityFacts(
        pipeline="etl",
        pipeline_rel="pipelines/etl.yaml",
        node="etl.clean",
        dataset="clean",
        env="dev",
        current=None,
        rows=len(frame),
        measured_rows=len(frame),
        columns=[{"name": "order_id"}, {"name": "amount"}],
        frame=frame,
    )


def _answer(block: str) -> str:
    return f"```yaml quality\n{block}```\nKeys never null.\n"


PASSES = "null_rate: {columns: [order_id], threshold: 0.0}\nrange: {column: amount, min: 0}\ngate: {max_errors: 0}\n"
FAILS = "null_rate: {columns: [amount], threshold: 0.0}\n"


@pytest.fixture
def measured(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr(proposals, "quality_facts", lambda *a, **k: _facts(root))
    return root


def test_a_check_that_fails_on_the_data_goes_back_to_the_model(measured):
    provider = FakeProvider(_answer(FAILS), _answer(PASSES))
    draft = propose_quality(measured, "etl", "etl.clean", provider)
    assert draft.ok, draft.blocking
    assert (draft.kind, draft.pipeline, draft.target, draft.env) == (
        "quality",
        "etl",
        "etl.clean",
        "dev",
    )
    assert draft.evidence == "Proven on 4 rows of dev."
    first = draft.attempts[0]
    assert first.rejected and "fails on the measured data" in first.rejected[0]
    # The model was told why, in its own conversation.
    assert "fails on the measured data" in provider.calls[1][-1].content
    # Only the node's quality block was added, in the file as written.
    assert set(draft.files) == {"pipelines/etl.yaml"}
    text = draft.files["pipelines/etl.yaml"]
    assert (
        "run: src.m:clean" in text
        and "      null_rate: {columns: [order_id], threshold: 0.0}" in text
    )


def test_a_proposal_may_use_only_checks_it_can_prove(measured):
    unknown = _answer("business_rules: {rules: ['amount > 0']}\n")
    missing = _answer("null_rate: {columns: [customer_id], threshold: 0.0}\n")
    draft = propose_quality(measured, "etl", "etl.clean", FakeProvider(unknown, missing, missing))
    assert not draft.ok
    messages = [m for a in draft.attempts for m in a.rejected]
    assert any("only schema, row_count" in m for m in messages)
    assert any("customer_id, not a column of clean" in m for m in messages)


def test_a_quality_draft_is_revised_in_the_same_conversation(measured, monkeypatch):
    draft = propose_quality(measured, "etl", "etl.clean", FakeProvider(_answer(PASSES)))
    save_draft(measured, draft)
    more = "null_rate: {columns: [order_id], threshold: 0.0}\nduplicates: {columns: [order_id]}\n"
    provider = FakeProvider(_answer(more))
    again = revise(measured, load_draft(measured, draft.id), "no duplicate ids", provider)
    assert again.ok and again.kind == "quality" and again.revision_of == draft.id
    assert "duplicates: {columns: [order_id]}" in again.files["pipelines/etl.yaml"]
    assert "no duplicate ids" in provider.calls[0][-1].content


def test_without_data_the_draft_says_it_was_not_proven(tmp_path, monkeypatch):
    root = _project(tmp_path)
    facts = _facts(root)
    facts.frame, facts.unmeasured, facts.columns = (
        None,
        "Not materialized in this environment yet",
        [],
    )
    monkeypatch.setattr(proposals, "quality_facts", lambda *a, **k: facts)
    draft = propose_quality(root, "etl", "etl.clean", FakeProvider(_answer(PASSES)))
    assert draft.ok and draft.evidence.startswith("Not checked against data")


def test_quality_facts_measure_the_output_without_sending_values(tmp_path, monkeypatch):
    root = _project(tmp_path)
    frame = pd.DataFrame({"order_id": [1, 2, 3], "name": ["Ada", "Bob", "Cy"]})
    monkeypatch.setattr(
        "ducta.api.services.dataset_preview.dataset_location", lambda *a, **k: ("x", "parquet")
    )
    monkeypatch.setattr(
        "ducta.api.services.dataset_preview.read_frame", lambda *a, **k: (frame, [], 3)
    )
    facts = proposals.quality_facts(root, "etl", "etl.clean")
    assert facts.dataset == "clean" and facts.rows == 3
    rendered = facts.render()
    assert '"name": "order_id"' in rendered
    assert "Ada" not in rendered and "Bob" not in rendered  # no values of a text column


def test_an_unknown_node_names_the_ones_there_are(tmp_path):
    with pytest.raises(Exception, match="its nodes: etl.clean"):
        proposals.quality_facts(_project(tmp_path), "etl", "nope")


def test_the_assembler_refuses_the_current_block(tmp_path):
    root = _project(tmp_path)
    (root / "pipelines" / "etl.yaml").write_text(
        "nodes:\n  etl.clean:\n    run: src.m:clean\n    inputs: {orders: raw}\n"
        "    outputs: [clean]\n    quality:\n      empty_dataset: true\n"
    )
    from ducta.ai.builder import parse_answer

    out = quality_assembler(root, _facts(root))(parse_answer(_answer("empty_dataset: true\n")))
    assert out.rejected and "current block" in out.rejected[0]


# ── documentation ────────────────────────────────────────────────────────────

DOCS = """```yaml docs
datasets:
  raw: {description: One order as the shop exported it, pii: [email]}
  clean: {description: One valid order}
pipelines:
  etl:
    description: Cleans the orders
    nodes: {etl.clean: Drops incomplete orders}
```
"""


def _documentable(tmp_path: Path) -> Path:
    root = _project(tmp_path)
    (root / "catalog.yaml").write_text(
        "# hand-written\n"
        "raw: {format: csv, path: d/raw.csv, schema: {columns: [order_id, email]}}\n"
        "clean: {format: parquet, path: d/clean}\n"
    )
    return root


def test_docs_add_only_what_is_missing_and_keep_the_files(tmp_path):
    root = _documentable(tmp_path)
    draft = propose_docs(root, FakeProvider(DOCS))
    assert draft.ok, draft.blocking
    assert draft.kind == "docs"
    catalog = draft.files["catalog.yaml"]
    assert catalog.startswith("# hand-written\n")
    assert "description: One order as the shop exported it" in catalog
    assert "pii: [email]" in catalog
    pipeline = draft.files["pipelines/etl.yaml"]
    assert pipeline.startswith("description: Cleans the orders\n")
    assert "description: Drops incomplete orders" in pipeline
    # What the model was told: names and columns, nothing else.
    sent = draft.prompt
    assert '"raw"' in sent and "email" in sent


def test_docs_refuse_what_was_not_asked_for(tmp_path):
    root = _documentable(tmp_path)
    stray = DOCS.replace("raw: {description", "nope: {description").replace("[email]", "[email]")
    bad_pii = DOCS.replace("[email]", "[phone]")
    draft = propose_docs(root, FakeProvider(stray, bad_pii, bad_pii))
    messages = [m for a in draft.attempts for m in a.rejected]
    assert any("'nope' was not asked for" in m for m in messages)
    assert any("phone is not one of its columns" in m for m in messages)


def test_a_documented_project_has_nothing_to_propose(tmp_path):
    root = _documentable(tmp_path)
    draft = propose_docs(root, FakeProvider(DOCS))
    from ducta.ai.builder import apply_draft

    apply_draft(root, draft)
    with pytest.raises(AIConfigError, match="already has a description"):
        propose_docs(root, FakeProvider(DOCS))


# ── explaining a failed run ──────────────────────────────────────────────────


def test_the_explanation_sees_the_code_around_the_error_line(tmp_path):
    root = _project(tmp_path)
    diagnosis = {
        "kind": "code",
        "title": "The node's code raised an error",
        "node": "etl.clean",
        "frame": {"file": "src/m.py", "line": 2, "function": "clean"},
    }
    text = explanation_message(root, diagnosis, "KeyError: 'region'", remote=True)
    assert "   2>     return orders" in text
    assert "KeyError: 'region'" in text


def test_without_a_traceback_the_failing_nodes_function_is_sent(tmp_path):
    root = _project(tmp_path)
    assert node_function(root, "etl.clean") == {
        "file": "src/m.py",
        "line": 1,
        "end": 2,
        "function": "clean",
        "pipeline": "etl",
    }
    text = explanation_message(root, {"node": "etl.clean"}, "TypeError: boom", remote=False)
    assert "The failing node's function: clean in src/m.py (lines 1–2" in text


def test_a_credential_in_the_code_never_reaches_a_remote_model(tmp_path):
    root = _project(tmp_path)
    (root / "src" / "m.py").write_text(
        'PASSWORD = "hunter2-very-secret"\ndef clean(orders):\n    return orders\n'
    )
    frame = {"file": "src/m.py", "line": 3, "function": "clean"}
    remote = explanation_message(root, {"frame": frame}, "x", remote=True)
    assert "hunter2" not in remote
    assert "hunter2" in explanation_message(root, {"frame": frame}, "x", remote=False)


def test_an_explanation_is_kept_per_run(tmp_path):
    root = _project(tmp_path)
    explanation = explain_failure(
        root, {"kind": "code"}, "boom", FakeProvider("**What happened** x")
    )
    assert explanation.text == "**What happened** x" and explanation.model == "fake"
    save_explanation(root, "run-1", explanation)
    assert load_explanation(root, "run-1").text == "**What happened** x"
    # A run id cannot lead out of the folder.
    save_explanation(root, "../../evil", explanation)
    assert (root / ".ducta" / "ai" / "explanations" / "evil.json").is_file()
    assert not (root / ".ducta" / "evil.json").exists()
    assert load_explanation(root, "other") is None


def test_ducta_ai_explain_reads_the_error_and_changes_nothing(tmp_path, monkeypatch, capsys):
    from ducta.console.commands.ai_cmds import AICommands

    root = _project(tmp_path)
    error = tmp_path / "err.txt"
    error.write_text(
        f"Traceback:\n  File \"{root}/src/m.py\", line 2, in clean\nKeyError: 'region'\n"
    )
    provider = FakeProvider("**What happened** the column region is missing")
    monkeypatch.setattr("ducta.ai.providers.make_provider", lambda config: provider)
    monkeypatch.setattr(
        "ducta.ai.config.load_config",
        lambda: SimpleNamespace(
            require_model=lambda: "fake", is_local=True, model="fake", endpoint="local"
        ),
    )
    before = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
    args = SimpleNamespace(
        ai_command="explain",
        error_file=str(error),
        note=None,
        base_path=str(root),
        output_format="json",
    )
    assert AICommands.handle(args) == 0
    out = capsys.readouterr().out
    assert '"kind": "code"' in out and "region is missing" in out
    assert "return orders" in provider.calls[0][0].content  # the code around line 2
    assert {p: p.read_text() for p in root.rglob("*") if p.is_file()} == before


def test_a_project_under_a_folder_named_ducta_still_has_its_frames(tmp_path):
    from ducta.api.services.diagnosis import first_user_frame

    root = tmp_path / "ducta" / "projects" / "shop"
    (root / "pipelines").mkdir(parents=True)
    tb = f'File "{root}/pipelines/etl.py", line 9, in load\nKeyError'
    assert first_user_frame(tb, root) == {"file": "pipelines/etl.py", "line": 9, "function": "load"}
    venv = f'File "{root}/.venv/lib/site-packages/pandas/core.py", line 1, in get'
    assert first_user_frame(venv, root) is None
