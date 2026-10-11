"""Drafting a pipeline: parse the answer, keep it additive, validate, retry, apply."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from ducta.ai.builder import (
    apply_draft,
    fix,
    generate,
    list_drafts,
    load_draft,
    parse_answer,
    save_draft,
)
from ducta.ai.config import AIConfig
from ducta.ai.errors import AIError
from ducta.ai.providers import ChatMessage, Completion

GOOD = """Here it is.

```yaml file=pipelines/silver.totals.yaml
description: Order totals
requires_dates: false
nodes:
  silver.totals:
    run: src.totals:totals
    inputs: {orders: raw}
    outputs: [silver.sales.totals]
```

```yaml catalog
silver.sales.totals: {format: parquet, path: d/totals}
```

```python file=src/totals.py
def totals(orders, **kwargs):
    return orders
```
"""

#: The function takes ``df``, not the ``orders`` input: the validator says so.
BAD_SIGNATURE = GOOD.replace("def totals(orders, **kwargs):", "def totals(df):")


def _project(tmp_path: Path, catalog_dir: bool = False) -> Path:
    (tmp_path / "ducta.yaml").write_text("version: 2\nproject: p\npaths: {input: d, output: d}\n")
    entries = "raw: {format: csv, path: d/raw.csv}\nclean: {format: parquet, path: d/clean}\n"
    if catalog_dir:
        (tmp_path / "catalog").mkdir()
        (tmp_path / "catalog" / "base.yaml").write_text(entries)
    else:
        (tmp_path / "catalog.yaml").write_text("# hand-written\n" + entries)
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "etl.yaml").write_text(
        "nodes:\n  etl.clean:\n    run: src.m:clean\n    inputs: {orders: raw}\n    outputs: [clean]\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("def clean(orders):\n    return orders\n")
    return tmp_path


class FakeProvider:
    def __init__(self, *answers: str):
        self.config = AIConfig(provider="ollama", model="fake", base_url="http://localhost:1/v1")
        self.answers = list(answers)
        self.calls: List[List[ChatMessage]] = []

    def complete(self, system: str, messages: List[ChatMessage]) -> Completion:
        self.calls.append(list(messages))
        if not self.answers:
            raise AIError("the fake model has no more answers")
        return Completion(text=self.answers.pop(0), model="fake")

    def list_models(self) -> List[str]:
        return ["fake"]


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_reads_named_blocks_catalog_and_notes():
    answer = parse_answer(GOOD)
    assert set(answer.files) == {"pipelines/silver.totals.yaml", "src/totals.py"}
    assert "silver.sales.totals" in answer.catalog
    assert answer.notes == "Here it is."


def test_parse_accepts_a_header_comment_instead_of_an_info_string():
    answer = parse_answer("```python\n# file: src/x.py\ndef f():\n    pass\n```")
    assert answer.files == {"src/x.py": "def f():\n    pass\n"}


# ── the loop ─────────────────────────────────────────────────────────────────


def test_a_valid_answer_is_a_valid_draft_and_nothing_is_written(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals per order", FakeProvider(GOOD))
    assert draft.ok, draft.problems
    assert set(draft.files) == {"pipelines/silver.totals.yaml", "src/totals.py", "catalog.yaml"}
    assert draft.new_datasets == ["silver.sales.totals"]
    assert not (root / "pipelines" / "silver.totals.yaml").exists()
    # The catalog is appended to, comments and all.
    assert draft.files["catalog.yaml"].startswith("# hand-written\nraw:")


def test_validation_problems_go_back_to_the_model(tmp_path):
    root = _project(tmp_path)
    provider = FakeProvider(BAD_SIGNATURE, GOOD)
    draft = generate(root, "totals", provider)
    assert draft.ok
    assert [a.errors for a in draft.attempts] == [1, 0]
    feedback = provider.calls[1][-1].content
    assert "orders" in feedback and "no parameter" in feedback


def test_attempts_run_out_with_the_last_draft_and_its_problems(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(BAD_SIGNATURE, BAD_SIGNATURE), max_attempts=2)
    assert not draft.ok
    assert len(draft.attempts) == 2
    assert any(p["code"] == "input_not_a_parameter" for p in draft.errors)


def test_existing_files_are_never_rewritten(tmp_path):
    root = _project(tmp_path)
    answer = GOOD.replace("file=src/totals.py", "file=src/m.py").replace(
        "src.totals:totals", "src.m:totals"
    )
    draft = generate(root, "totals", FakeProvider(answer), max_attempts=1)
    assert not draft.ok
    assert "src/m.py" not in draft.files
    assert any("already exists" in p["message"] for p in draft.errors)


def test_only_pipelines_code_and_catalog_may_be_added(tmp_path):
    root = _project(tmp_path)
    answer = GOOD + "\n```yaml file=ducta.yaml\nversion: 2\n```\n"
    draft = generate(root, "totals", FakeProvider(answer), max_attempts=1)
    assert "ducta.yaml" not in draft.files
    assert any("may only add" in p["message"] for p in draft.errors)


def test_an_existing_dataset_is_not_redeclared(tmp_path):
    root = _project(tmp_path)
    answer = GOOD.replace("silver.sales.totals: {", "raw: {format: csv}\nsilver.sales.totals: {")
    draft = generate(root, "totals", FakeProvider(answer), max_attempts=1)
    assert any("do not redeclare: raw" in p["message"] for p in draft.errors)
    assert draft.files["catalog.yaml"].count("raw:") == 1


def test_a_catalog_folder_gets_a_new_file(tmp_path):
    root = _project(tmp_path, catalog_dir=True)
    draft = generate(root, "totals", FakeProvider(GOOD))
    assert draft.ok, draft.problems
    assert "catalog/silver.totals.yaml" in draft.files


def test_unnamed_blocks_are_placed_from_their_content(tmp_path):
    root = _project(tmp_path)
    answer = (
        GOOD.replace("```yaml file=pipelines/silver.totals.yaml", "```yaml")
        .replace("```yaml catalog", "```yaml")
        .replace("```python file=src/totals.py", "```python")
    )
    draft = generate(root, "totals", FakeProvider(answer))
    assert draft.ok, draft.problems
    # Named after its first node; the code goes to the one new module `run:` names.
    assert set(draft.files) == {"pipelines/silver.totals.yaml", "src/totals.py", "catalog.yaml"}


def test_one_pipeline_per_draft(tmp_path):
    root = _project(tmp_path)
    extra = "\n```yaml file=pipelines/other.yaml\nnodes: {}\n```\n"
    draft = generate(root, "totals", FakeProvider(GOOD + extra), max_attempts=1)
    assert "pipelines/other.yaml" not in draft.files
    assert any("ONE new pipeline" in p["message"] for p in draft.errors)


def test_a_project_that_does_not_validate_is_refused_before_calling_the_model(tmp_path):
    root = _project(tmp_path)
    (root / "pipelines" / "etl.yaml").write_text("nodes: [not, a, mapping]\n")
    provider = FakeProvider(GOOD)
    with pytest.raises(AIError, match="does not validate"):
        generate(root, "totals", provider)
    assert provider.calls == []


# ── saving and applying ──────────────────────────────────────────────────────


def test_a_saved_draft_applies(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(GOOD))
    save_draft(root, draft)
    loaded = load_draft(root, draft.id[:10])
    written = apply_draft(root, loaded)
    assert set(written) == set(draft.files)
    assert "silver.sales.totals" in (root / "catalog.yaml").read_text()
    assert (root / "src" / "totals.py").exists()


def test_apply_refuses_when_a_file_changed_since(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(GOOD))
    (root / "catalog.yaml").write_text("raw: {format: csv, path: d/raw.csv}\n")
    with pytest.raises(AIError, match="changed after the draft"):
        apply_draft(root, draft)
    assert not (root / "src" / "totals.py").exists()


# ── fixing ───────────────────────────────────────────────────────────────────

FIXED_MODULE = (
    "```python file=src/m.py\ndef clean(orders):\n    return orders\n```\nRenamed the parameter."
)


def _broken(tmp_path: Path) -> Path:
    root = _project(tmp_path)
    (root / "src" / "m.py").write_text("def clean(df):\n    return df\n")
    return root


def test_a_fix_rewrites_the_pipelines_own_module(tmp_path):
    root = _broken(tmp_path)
    provider = FakeProvider(FIXED_MODULE)
    draft = fix(root, "etl", provider)
    assert draft.ok, draft.blocking
    assert (draft.kind, draft.pipeline) == ("fix", "etl")
    assert set(draft.files) == {"src/m.py"}
    assert "-def clean(df):" in draft.diff(root) and "+def clean(orders):" in draft.diff(root)
    # The model saw the file and the problem.
    first = provider.calls[0][0].content
    assert "```python file=src/m.py" in first and "no parameter" in first


def test_a_fix_may_not_touch_other_pipelines(tmp_path):
    root = _broken(tmp_path)
    (root / "pipelines" / "other.yaml").write_text("nodes: {}\n")
    answer = FIXED_MODULE + "\n```yaml file=pipelines/other.yaml\nnodes: {}\ndescription: x\n```\n"
    draft = fix(root, "etl", FakeProvider(answer), max_attempts=1)
    assert "pipelines/other.yaml" not in draft.files
    assert any("only" in p["message"] for p in draft.blocking)


def test_a_fix_that_leaves_the_problem_is_not_ok(tmp_path):
    root = _broken(tmp_path)
    same_problem = "```python file=src/m.py\ndef clean(df, x=1):\n    return df\n```"
    draft = fix(root, "etl", FakeProvider(same_problem, same_problem), max_attempts=2)
    assert not draft.ok
    assert any(p.get("code") == "input_not_a_parameter" for p in draft.blocking)


def test_nothing_to_fix_is_said_before_calling_the_model(tmp_path):
    root = _project(tmp_path)
    provider = FakeProvider(FIXED_MODULE)
    with pytest.raises(AIError, match="nothing to fix"):
        fix(root, "etl", provider)
    assert provider.calls == []


def test_a_run_error_is_enough_to_ask_for_a_fix(tmp_path):
    root = _project(tmp_path)
    answer = "```python file=src/m.py\ndef clean(orders):\n    return orders.dropna()\n```"
    provider = FakeProvider(answer)
    draft = fix(root, "etl", provider, error="KeyError: 'amount'")
    assert draft.ok
    assert "KeyError: 'amount'" in provider.calls[0][0].content


def test_an_unknown_pipeline_is_named(tmp_path):
    with pytest.raises(AIError, match="No pipeline 'nope'"):
        fix(_project(tmp_path), "nope", FakeProvider())


def test_problems_the_project_already_had_do_not_block_a_new_pipeline(tmp_path):
    root = _broken(tmp_path)  # etl already has an error
    draft = generate(root, "totals", FakeProvider(GOOD))
    assert draft.ok, draft.blocking
    assert any(p.get("code") == "input_not_a_parameter" for p in draft.problems)


def test_drafts_are_listed_newest_first_and_applied_once(tmp_path):
    root = _project(tmp_path)
    first = generate(root, "a", FakeProvider(GOOD))
    save_draft(root, first)
    second = generate(root, "b", FakeProvider(GOOD.replace("totals", "sums")))
    second.id = "z" + second.id  # sorts after the first
    save_draft(root, second)
    assert [d.request for d in list_drafts(root)] == ["b", "a"]
    apply_draft(root, load_draft(root, first.id))
    assert load_draft(root, first.id).applied_at
    with pytest.raises(AIError, match="already applied"):
        apply_draft(root, load_draft(root, first.id))


def test_a_model_that_fails_later_keeps_the_last_draft(tmp_path):
    root = _project(tmp_path)
    bad = GOOD.replace("def totals(orders, **kwargs):", "def totals(df):")
    draft = generate(root, "x", FakeProvider(bad), max_attempts=3)  # 2nd call has no answer
    assert len(draft.attempts) == 1 and draft.files
    assert "Attempt 2 did not complete" in draft.notes


def test_a_model_that_fails_at_once_raises(tmp_path):
    with pytest.raises(AIError):
        generate(_project(tmp_path), "x", FakeProvider())


# ── revising ─────────────────────────────────────────────────────────────────


def test_a_revision_continues_the_conversation_with_the_change(tmp_path):
    from ducta.ai.builder import revise

    root = _project(tmp_path)
    first = generate(root, "totals", FakeProvider(GOOD))
    provider = FakeProvider(GOOD.replace("Order totals", "Order totals per day"))
    second = revise(root, first, "describe it per day", provider)
    assert second.ok and second.revision_of == first.id
    sent = provider.calls[0]
    assert [m.role for m in sent] == ["user", "assistant", "user"]
    assert sent[0].content == first.prompt and sent[1].content == first.raw_answer
    assert "describe it per day" in sent[2].content
    assert "per day" in second.files["pipelines/silver.totals.yaml"]
    assert second.request == "totals — describe it per day"


def test_a_fix_is_revised_within_its_scope(tmp_path):
    from ducta.ai.builder import revise

    root = _broken(tmp_path)
    first = fix(root, "etl", FakeProvider(FIXED_MODULE))
    again = FIXED_MODULE.replace("return orders", "return orders.copy()")
    second = revise(root, first, "copy it", FakeProvider(again))
    assert second.ok and second.kind == "fix" and set(second.files) == {"src/m.py"}


def test_an_applied_or_empty_revision_is_refused(tmp_path):
    from ducta.ai.builder import revise

    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(GOOD))
    with pytest.raises(AIError, match="Say what to change"):
        revise(root, draft, "  ", FakeProvider())
    apply_draft(root, draft)
    with pytest.raises(AIError, match="already applied"):
        revise(root, draft, "more", FakeProvider())


def test_a_revision_refuses_when_a_file_its_prompt_showed_changed(tmp_path):
    from ducta.ai.builder import revise

    root = _broken(tmp_path)
    first = fix(root, "etl", FakeProvider(FIXED_MODULE))
    (root / "src" / "m.py").write_text("def clean(df):\n    # edited by hand\n    return df\n")
    provider = FakeProvider(FIXED_MODULE)
    with pytest.raises(AIError, match="changed after draft"):
        revise(root, first, "copy it", provider)
    assert provider.calls == []


def test_a_file_edited_while_the_model_answers_is_not_overwritten(tmp_path):
    root = _broken(tmp_path)

    class EditsMeanwhile(FakeProvider):
        def complete(self, system: str, messages: List[ChatMessage]) -> Completion:
            (root / "src" / "m.py").write_text(
                "def clean(df):\n    # edited by hand\n    return df\n"
            )
            return super().complete(system, messages)

    draft = fix(root, "etl", EditsMeanwhile(FIXED_MODULE))
    with pytest.raises(AIError, match="changed after the draft"):
        apply_draft(root, draft)
    assert "edited by hand" in (root / "src" / "m.py").read_text()


@pytest.mark.parametrize("path", [".", "./", "/", "/etc/x.py", "src/../../x.py"])
def test_an_empty_or_outside_path_is_sent_back_not_a_crash(tmp_path, path):
    root = _project(tmp_path)
    answer = f"```python file={path}\ndef f():\n    pass\n```\n" + GOOD
    draft = generate(root, "totals", FakeProvider(answer, GOOD), max_attempts=2)
    assert draft.ok and len(draft.attempts) == 2
    assert all(not rel.startswith("/") and ".." not in rel for rel in draft.files)


def test_only_a_leading_dot_slash_is_dropped_from_a_path():
    answer = parse_answer(
        "```python file=./src/a.py\npass\n```\n```python file=.hidden/b.py\npass\n```"
    )
    assert set(answer.files) == {"src/a.py", ".hidden/b.py"}


def test_files_python_runs_on_its_own_are_not_added(tmp_path):
    root = _project(tmp_path)
    answer = GOOD + "\n```python file=conftest.py\nimport os\n```\n"
    draft = generate(root, "totals", FakeProvider(answer), max_attempts=1)
    assert "conftest.py" not in draft.files
    assert any("conftest.py" in p["message"] for p in draft.blocking)


def test_a_fence_inside_a_line_does_not_end_the_block():
    code = 'def f():\n    return "```"\n'
    answer = parse_answer(f"```python file=src/a.py\n{code}```\nDone.")
    assert answer.files == {"src/a.py": code}
    assert answer.notes == "Done."


def test_apply_refuses_a_draft_whose_paths_were_tampered_with(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(GOOD))
    draft.files["../outside.py"] = "x = 1\n"
    draft.base["../outside.py"] = None
    with pytest.raises(AIError, match="inside the project"):
        apply_draft(root, draft)
    assert not (tmp_path.parent / "outside.py").exists()
    assert not (root / "src" / "totals.py").exists()


def test_apply_writes_nothing_when_one_file_fails(tmp_path, monkeypatch):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(GOOD))
    before = (root / "catalog.yaml").read_text()
    real = Path.write_text

    def fail_on_code(self, *args, **kwargs):
        if self.name.startswith(".totals.py"):
            raise OSError("disk full")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_code)
    with pytest.raises(AIError, match="disk full"):
        apply_draft(root, draft)
    monkeypatch.undo()
    assert (root / "catalog.yaml").read_text() == before
    assert not (root / "src" / "totals.py").exists()
    assert not list(root.rglob("*.tmp"))
    assert draft.applied_at is None


def test_a_run_error_is_sent_without_its_credentials(tmp_path):
    root = _project(tmp_path)
    answer = "```python file=src/m.py\ndef clean(orders):\n    return orders.dropna()\n```"
    provider = FakeProvider(answer)
    error = "OperationalError: postgresql://etl:s3cr3t@db:5432/x password=hunter2 failed"
    fix(root, "etl", provider, error=error)
    sent = provider.calls[0][0].content
    assert "s3cr3t" not in sent and "hunter2" not in sent
    assert "postgresql://etl:***@db:5432/x" in sent
