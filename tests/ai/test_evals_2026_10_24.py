"""``ducta ai eval`` matured: repeats, three more cases, a history and comparisons."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import List

import pytest

from ducta.ai.config import AIConfig
from ducta.ai.errors import AICancelledError, AIConfigError, AIError, AINotFoundError
from ducta.ai.providers import Completion

GOOD_EXPLANATION = (
    "**What happened** transform failed.\n**Why** column amount_usd is missing.\n"
    "**What to do** use amount."
)

DAILY = """```yaml file=pipelines/gold_daily.yaml
description: Amount per day
requires_dates: false
nodes:
  daily:
    run: pipelines.gold_daily:daily
    inputs: {clean_data: silver.etl.clean_data}
    outputs: [gold.etl.daily]
```

```yaml catalog
gold.etl.daily: {description: Amount per day}
```

```python file=pipelines/gold_daily.py
def daily(clean_data, **kwargs):
    return clean_data
```
"""

DAILY_REVISED = DAILY.replace(
    "outputs: [gold.etl.daily]", "outputs: [gold.etl.daily]\n    description: sum and order_count"
)

BLUEPRINT = """```yaml blueprint
name: category_revenue
goal: Amount per category
datasets:
  gold.etl.category_revenue:
    description: Amount per category
    columns: {category: string, amount: double}
pipelines:
  gold.categories:
    description: Amount per category
    owner: data-team
    nodes:
      category_revenue:
        inputs: {clean_data: silver.etl.clean_data}
        outputs: [gold.etl.category_revenue]
        logic: sum amount by category
```
One pipeline.
"""


class Canned:
    """Answers in order; each takes 100 tokens in and 10 out."""

    def __init__(self, *answers, model: str = "fake", provider: str = "ollama"):
        self.config = AIConfig(provider=provider, model=model, base_url="http://localhost:1/v1")
        self.answers = list(answers)

    def complete(self, system, messages):
        if not self.answers:
            raise AIError("no more answers")
        return Completion(
            self.answers.pop(0), "fake", False, {"input_tokens": 100, "output_tokens": 10}
        )

    def list_models(self):
        return ["fake"]


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """Reports go to a throw-away DUCTA_HOME."""
    monkeypatch.setenv("DUCTA_HOME", str(tmp_path / "home"))


def _extend_answer(root) -> str:
    original = (root / "pipelines" / "etl.yaml").read_text()
    node = (
        "\n  per_category:\n    run: pipelines.etl:per_category\n"
        "    inputs: {clean_data: silver.etl.clean_data}\n    outputs: [gold.etl.per_category]\n"
    )
    module = (root / "pipelines" / "etl.py").read_text()
    return (
        f"```yaml file=pipelines/etl.yaml\n{original}{node}```\n\n"
        "```yaml catalog\ngold.etl.per_category: {description: Orders per category}\n```\n\n"
        f"```python file=pipelines/etl.py\n{module}\n\n"
        "def per_category(clean_data, **kwargs):\n    return clean_data\n```\n"
    )


# ── the three new cases ─────────────────────────────────────────────────────


def test_there_are_ten_cases_and_every_kind_is_known():
    from ducta.ai.evals import CASES, DRAFT_KINDS

    assert len(CASES) == 10
    assert {c.kind for c in CASES} == set(DRAFT_KINDS) | {"review", "explain"}


def test_extend_passes_when_a_node_is_added(tmp_path):
    from ducta.ai.evals import make_template, run_case, select

    root = make_template(tmp_path)
    result = run_case(root, select(["extend-add-node"])[0], Canned(_extend_answer(root)))
    assert result.passed, result.misses
    assert result.attempts == 1


def test_extend_fails_when_the_draft_changes_an_existing_node(tmp_path):
    from ducta.ai.evals import make_template, run_case, select

    root = make_template(tmp_path)
    answer = _extend_answer(root).replace("run: pipelines.etl:load", "run: pipelines.etl:other")
    result = run_case(root, select(["extend-add-node"])[0], Canned(answer, answer, answer))
    assert not result.passed and result.misses


def test_revise_passes_when_the_change_asked_for_is_there(tmp_path):
    from ducta.ai.evals import make_template, run_case, select

    root = make_template(tmp_path)
    result = run_case(root, select(["revise-draft"])[0], Canned(DAILY, DAILY_REVISED))
    assert result.passed, result.misses
    assert result.attempts == 2 and result.usage["input_tokens"] == 200


def test_revise_fails_when_the_change_is_missing(tmp_path):
    from ducta.ai.evals import make_template, run_case, select

    root = make_template(tmp_path)
    result = run_case(root, select(["revise-draft"])[0], Canned(DAILY, DAILY))
    assert not result.passed
    assert "the pipeline does not mention order_count" in result.misses


def test_architect_passes_on_a_checked_blueprint(tmp_path):
    from ducta.ai.evals import make_template, run_case, select

    root = make_template(tmp_path)
    result = run_case(root, select(["architect-plan"])[0], Canned(BLUEPRINT))
    assert result.passed, result.misses


def test_architect_fails_on_a_blueprint_that_reads_nothing_real(tmp_path):
    from ducta.ai.evals import make_template, run_case, select

    root = make_template(tmp_path)
    bad = BLUEPRINT.replace("silver.etl.clean_data", "silver.etl.nope")
    result = run_case(root, select(["architect-plan"])[0], Canned(bad, bad, bad))
    assert not result.passed and result.misses


# ── repeats ─────────────────────────────────────────────────────────────────


def test_a_case_passes_only_when_every_run_does_and_is_flaky_otherwise():
    from ducta.ai.evals import run_eval, select

    provider = Canned(GOOD_EXPLANATION, "nothing useful", GOOD_EXPLANATION)
    report = run_eval(provider, select(["explain-keyerror"]), repeat=3)
    (result,) = report.results
    assert (result.runs, result.passes, result.passed, result.flaky) == (3, 2, False, True)
    assert report.summary()["flaky"] == ["explain-keyerror"]
    assert result.usage["input_tokens"] == 300


def test_repeat_out_of_range_is_refused():
    from ducta.ai.evals import run_eval

    with pytest.raises(AIConfigError, match="--repeat"):
        run_eval(Canned(), repeat=0)


def test_should_stop_ends_the_evaluation_before_the_next_run():
    from ducta.ai.evals import run_eval, select

    asked: List[int] = []

    def stop() -> bool:
        asked.append(1)
        return len(asked) > 1

    with pytest.raises(AICancelledError):
        run_eval(Canned(GOOD_EXPLANATION), select(["explain-keyerror"]), repeat=2, should_stop=stop)


# ── history and comparison ──────────────────────────────────────────────────


def _report(model: str, created_at: str, passed: List[bool]):
    from ducta.ai.evals import EvalReport, EvalResult

    return EvalReport(
        provider="ollama",
        model=model,
        created_at=created_at,
        results=[
            EvalResult(f"case-{i}", "new", ok, 1.0, attempts=1, passes=int(ok), prompt_version="p1")
            for i, ok in enumerate(passed)
        ],
    )


def test_reports_are_kept_listed_loaded_and_pruned(monkeypatch):
    from ducta.ai import evals

    monkeypatch.setattr(evals, "MAX_REPORTS", 2)
    first = _report("qwen:14b", "2026-10-24T10:00:00+00:00", [True])
    path = evals.save_report(first)
    assert first.id == "20261024T100000Z-qwen-14b" and path.is_file()
    again = _report("qwen:14b", "2026-10-24T10:00:00+00:00", [True])
    evals.save_report(again)
    assert again.id == "20261024T100000Z-qwen-14b-2"
    evals.save_report(_report("qwen:14b", "2026-10-24T11:00:00+00:00", [False]))
    kept = evals.list_reports()
    assert [r.created_at[11:13] for r in kept] == ["11", "10"] and len(kept) == 2
    loaded = evals.load_report(kept[0].id)
    assert loaded.results[0].passed is False
    assert evals.load_report(str(path.parent / f"{kept[1].id}.json")).id == kept[1].id
    with pytest.raises(AINotFoundError):
        evals.load_report("20990101T000000Z-nope")


def test_a_report_without_the_new_fields_still_loads(tmp_path):
    from ducta.ai.evals import load_report

    old = {
        "provider": "groq",
        "model": "m",
        "created_at": "2026-10-23T09:00:00+00:00",
        "results": [{"case": "new-spanish", "kind": "new", "passed": True, "seconds": 3.0}],
    }
    path = tmp_path / "old.json"
    path.write_text(json.dumps(old))
    report = load_report(str(path))
    assert report.repeat == 1 and report.results[0].runs == 1 and report.passed == 1


def test_compare_says_which_cases_were_gained_and_lost():
    from ducta.ai.evals import compare

    a = _report("m", "2026-10-24T10:00:00+00:00", [True, False, True])
    b = _report("m", "2026-10-24T11:00:00+00:00", [False, True, True])
    b.results[2].prompt_version = "p2"
    b.results.append(_report("m", "x", [True]).results[0].__class__("extra", "new", True, 1.0))
    out = compare(a, b)
    changes = {c["case"]: c["change"] for c in out["cases"]}
    assert changes == {"case-0": "lost", "case-1": "gained", "case-2": "same", "extra": "added"}
    assert [c["case"] for c in out["cases"] if c["prompt_changed"]] == ["case-2"]
    assert out["pass_rate"] == round(3 / 4 - 2 / 3, 3)


def test_previous_report_is_the_same_models_earlier_one():
    from ducta.ai import evals

    old = _report("m", "2026-10-24T10:00:00+00:00", [True])
    other = _report("other", "2026-10-24T10:30:00+00:00", [True])
    new = _report("m", "2026-10-24T11:00:00+00:00", [True])
    for r in (old, other, new):
        evals.save_report(r)
    assert evals.previous_report(new).id == old.id
    assert evals.previous_report(old) is None


# ── the command ─────────────────────────────────────────────────────────────


def _args(**kw):
    base = dict(
        ai_command="eval",
        case=None,
        out=None,
        yes=True,
        output_format="json",
        repeat=1,
        list=False,
        compare=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_command_keeps_the_report_and_lists_it(monkeypatch, capsys):
    from ducta.ai import evals
    from ducta.console.commands import ai_cmds

    local = AIConfig(provider="ollama", model="fake", base_url="http://localhost:1/v1")
    monkeypatch.setattr("ducta.ai.config.load_config", lambda: local)
    monkeypatch.setattr("ducta.ai.providers.make_provider", lambda config: Canned(GOOD_EXPLANATION))
    assert ai_cmds.AICommands.handle(_args(case=["explain-keyerror"])) == 0
    capsys.readouterr()
    assert len(evals.list_reports()) == 1
    assert ai_cmds.AICommands.handle(_args(list=True)) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["model"] == "fake" and listed[0]["passed"] == 1


def test_compare_with_one_report_uses_the_previous_one(capsys):
    from ducta.ai import evals
    from ducta.console.commands import ai_cmds

    old = _report("m", "2026-10-24T10:00:00+00:00", [False])
    new = _report("m", "2026-10-24T11:00:00+00:00", [True])
    evals.save_report(old)
    evals.save_report(new)
    assert ai_cmds.AICommands.handle(_args(compare=[new.id])) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["a"]["id"] == old.id and out["cases"][0]["change"] == "gained"
    assert ai_cmds.AICommands.handle(_args(compare=[old.id])) != 0  # nothing earlier


def test_list_and_compare_do_not_need_a_model(monkeypatch):
    from ducta.console.commands import ai_cmds

    def no_model():
        raise AssertionError("no model is needed")

    monkeypatch.setattr("ducta.ai.config.load_config", no_model)
    assert ai_cmds.AICommands.handle(_args(list=True)) == 0


def test_the_parser_takes_the_new_options():
    from ducta.console.parser import UnifiedArgumentParser

    parser = UnifiedArgumentParser.create()
    args = parser.parse_args(["ai", "eval", "--repeat", "3", "--case", "revise-draft"])
    assert args.repeat == 3 and args.case == ["revise-draft"]
    assert parser.parse_args(["ai", "eval", "--list"]).list is True
    assert parser.parse_args(["ai", "eval", "--compare", "a", "b"]).compare == ["a", "b"]


def test_every_case_says_what_it_is_about():
    from ducta.ai.evals import CASES

    assert all(c.about for c in CASES)


def test_the_command_records_that_the_cli_ran_it(monkeypatch, capsys):
    from ducta.ai import evals
    from ducta.console.commands import ai_cmds

    local = AIConfig(provider="ollama", model="fake", base_url="http://localhost:1/v1")
    monkeypatch.setattr("ducta.ai.config.load_config", lambda: local)
    monkeypatch.setattr("ducta.ai.providers.make_provider", lambda config: Canned(GOOD_EXPLANATION))
    assert ai_cmds.AICommands.handle(_args(case=["explain-keyerror"])) == 0
    (report,) = evals.list_reports()
    assert report.source == "cli" and report.head()["source"] == "cli"


def test_a_case_the_model_never_answered_is_not_a_prompt_change():
    from ducta.ai.evals import compare

    a = _report("m", "2026-10-24T10:00:00+00:00", [True])
    b = _report("m", "2026-10-24T11:00:00+00:00", [False])
    b.results[0].prompt_version = ""  # the model could not be reached
    assert compare(a, b)["cases"][0]["prompt_changed"] is False
