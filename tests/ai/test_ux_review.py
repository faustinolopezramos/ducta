"""The UX/DX review of ``ducta ai`` and ``ducta skill`` (2026-10-11).

Each test is a problem found by using the commands on a real project: the
draft that could not put its code where the template keeps it, the model the
setup picked, the exit codes, a hidden folder read as part of the project.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.ai.builder import code_folder, generate
from ducta.ai.errors import AIConfigError, AIError, AINotFoundError
from ducta.console.commands.ai_cmds import AICommands, pick_model

sys.path.insert(0, str(Path(__file__).parent))
from test_builder import FakeProvider, _project  # noqa: E402

# ── where the code goes ─────────────────────────────────────────────────────


def _template_layout(root: Path) -> Path:
    """Code next to the pipeline files, as ``ducta template`` lays it out."""
    root = _project(root)
    (root / "pipelines" / "__init__.py").write_text("")
    (root / "pipelines" / "etl.py").write_text("def clean(orders):\n    return orders\n")
    (root / "pipelines" / "etl.yaml").write_text(
        "nodes:\n  etl.clean:\n    run: pipelines.etl:clean\n"
        "    inputs: {orders: raw}\n    outputs: [clean]\n"
    )
    return root


IN_PIPELINES = """```yaml file=pipelines/gold.totals.yaml
description: Totals
requires_dates: false
nodes:
  gold.totals:
    run: pipelines.gold_totals:totals
    inputs: {clean: clean}
    outputs: [gold.sales.totals]
```

```yaml catalog
gold.sales.totals: {format: parquet, path: d/totals}
```

```python file=pipelines/gold_totals.py
def totals(clean, **kwargs):
    return clean
```
"""


def test_the_code_folder_is_where_the_project_keeps_its_code(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    assert code_folder(_project(tmp_path / "a")) == "src"
    assert code_folder(_template_layout(tmp_path / "b")) == "pipelines"
    empty = tmp_path / "c"
    (empty / "pipelines").mkdir(parents=True)
    assert code_folder(empty) == "src"


def test_a_draft_may_put_its_module_in_pipelines_when_the_project_does(tmp_path):
    root = _template_layout(tmp_path)
    provider = FakeProvider(IN_PIPELINES)
    draft = generate(root, "totals", provider)
    assert draft.ok, draft.blocking
    assert set(draft.files) >= {"pipelines/gold.totals.yaml", "pipelines/gold_totals.py"}
    # The model was told where code goes in this project.
    first = provider.calls[0][0].content
    assert "New modules go in `pipelines/`" in first


def test_a_module_in_pipelines_is_refused_when_it_is_not_a_package(tmp_path):
    root = _project(tmp_path)  # code in src/, pipelines/ is not a package
    draft = generate(root, "totals", FakeProvider(IN_PIPELINES, IN_PIPELINES, IN_PIPELINES))
    assert not draft.ok
    assert any("pipelines/gold_totals.py" in p["message"] for p in draft.blocking)


def test_each_attempt_keeps_what_was_wrong(tmp_path):
    root = _template_layout(tmp_path)
    no_module = IN_PIPELINES.split("```python")[0]
    draft = generate(root, "totals", FakeProvider(no_module, IN_PIPELINES))
    assert draft.ok
    first = draft.attempts[0]
    assert first.errors and first.messages
    assert "gold_totals" in first.messages[0]
    assert draft.attempts[1].messages == []


# ── setup picks a model that can draft ───────────────────────────────────────


@pytest.mark.parametrize(
    "models, chosen",
    [
        (["llama3.2:latest", "qwen2.5-coder:7b"], "qwen2.5-coder:7b"),
        (["qwen2.5-coder:7b", "qwen2.5-coder:14b", "llama3.2"], "qwen2.5-coder:14b"),
        (["deepseek-coder-v2:16b", "codestral:22b"], "codestral:22b"),
        (["llama3.2:latest", "mistral:7b"], "llama3.2:latest"),
    ],
)
def test_setup_prefers_the_largest_code_model(models, chosen):
    assert pick_model(models) == chosen


# ── exit codes ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error, code",
    [
        (AIConfigError("no provider"), 2),
        (AIError("cannot reach"), 5),
        (AINotFoundError("no draft"), 1),
    ],
)
def test_ai_errors_exit_with_what_went_wrong(monkeypatch, error, code):
    def boom(_args):
        raise error

    monkeypatch.setattr(AICommands, "doctor", staticmethod(boom))
    assert AICommands.handle(SimpleNamespace(ai_command="doctor")) == code


def test_login_with_nothing_configured_says_what_to_run(tmp_path, monkeypatch):
    from ducta.console.commands.ai_cmds import _key_target

    monkeypatch.setenv("DUCTA_HOME", str(tmp_path))
    for var in ("DUCTA_AI_PROVIDER", "DUCTA_AI_MODEL", "DUCTA_AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(AIConfigError, match="ducta ai setup --provider"):
        _key_target(SimpleNamespace(provider=None))


# ── hidden folders are not the project ──────────────────────────────────────


def test_a_hidden_folder_in_pipelines_is_not_read(tmp_path):
    from ducta.setting.project_loader import read_project

    root = _project(tmp_path)
    hidden = root / "pipelines" / ".claude" / "skills" / "ducta" / "examples"
    hidden.mkdir(parents=True)
    (hidden / "broken.yaml").write_text("nodes: [not, a, mapping]\n")
    project = read_project(root)
    assert set(project.pipeline_files) == {"etl"}
