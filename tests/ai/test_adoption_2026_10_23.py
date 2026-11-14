"""AI adoption review (2026-10-23): measurement, cost, robustness, policy, structure."""

from __future__ import annotations

import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import List

import httpx
import pytest

from ducta.ai.config import AIConfig, build_config
from ducta.ai.drafts import Attempt, add_usage, usage_line
from ducta.ai.errors import AIConfigError, AIError, AIPolicyError
from ducta.ai.providers import (
    AnthropicProvider,
    ChatMessage,
    Completion,
    OpenAICompatibleProvider,
    claude_version,
    takes_effort,
    takes_fallbacks,
)
from tests.ai.test_builder import GOOD, _project


class Canned:
    """Answers in order, with usage and an optional cut-off flag per answer."""

    def __init__(self, *answers, config: AIConfig = None):
        self.config = config or AIConfig(
            provider="ollama", model="fake", base_url="http://localhost:1/v1"
        )
        self.answers = list(answers)
        self.calls: List[List[ChatMessage]] = []

    def complete(self, system, messages):
        self.calls.append(list(messages))
        if not self.answers:
            raise AIError("no more answers")
        answer = self.answers.pop(0)
        text, truncated = answer if isinstance(answer, tuple) else (answer, False)
        return Completion(text, "fake", truncated, {"input_tokens": 100, "output_tokens": 10})

    def list_models(self):
        return ["fake"]


REMOTE = AIConfig(provider="openai", model="gpt", base_url="https://api.openai.com/v1")


# ── structure: loop and drafts are their own modules ────────────────────────


def test_builder_keeps_its_documented_names():
    import ducta.ai.builder as builder

    for name in builder.__all__:
        assert hasattr(builder, name), name
    from ducta.ai.drafts import Draft
    from ducta.ai.loop import parse_answer

    assert builder.Draft is Draft and builder.parse_answer is parse_answer


def test_run_loop_needs_an_assembler():
    import inspect

    from ducta.ai.loop import run_loop

    assert inspect.signature(run_loop).parameters["assembler"].default is inspect.Parameter.empty


def test_install_hints_name_only_the_ai_extra():
    root = Path(__file__).resolve().parents[2] / "src" / "ducta" / "ai"
    for path in root.rglob("*.py"):
        assert "ducta[api,ai]" not in path.read_text(encoding="utf-8"), path


# ── usage and prompt versions ───────────────────────────────────────────────


def test_usage_adds_up_and_reads_in_words():
    total = add_usage({"input_tokens": 10, "output_tokens": 2}, {"input_tokens": 5}, {})
    assert total == {"input_tokens": 15, "output_tokens": 2}
    assert usage_line({}) == ""
    line = usage_line({"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 7})
    assert line == "1,000 tokens in (900 cached) · 7 out"


def test_a_draft_adds_up_its_attempts_and_records_its_prompt(tmp_path):
    from ducta.ai.builder import SYSTEM_PROMPT, generate
    from ducta.ai.loop import prompt_version

    bad = GOOD.replace("def totals(orders, **kwargs):", "def totals(df):")
    draft = generate(_project(tmp_path), "totals", Canned(bad, GOOD))
    assert draft.ok and len(draft.attempts) == 2
    assert draft.usage == {"input_tokens": 200, "output_tokens": 20}
    assert draft.prompt_version == prompt_version(SYSTEM_PROMPT) and len(draft.prompt_version) == 12


def test_the_api_summary_carries_usage_and_prompt_version():
    from ducta.ai.drafts import Draft
    from ducta_server.routes.ai import _summary

    draft = Draft(
        id="20261023-000000-abcdef",
        request="r",
        provider="ollama",
        model="m",
        created_at="now",
        ok=True,
        files={},
        base={},
        problems=[],
        attempts=[Attempt(1, [], 0, 0, [], {"input_tokens": 3})],
        prompt_version="abc",
    )
    summary = _summary(draft)
    assert summary.usage == {"input_tokens": 3} and summary.prompt_version == "abc"


# ── OpenAI-compatible: retries what the server turns away for now ───────────


def _provider(responses, sleeps):
    config = build_config("openai_compatible", base_url="https://api.groq.com/openai/v1", model="m")
    queue = list(responses)
    client = httpx.Client(
        base_url=config.base_url, transport=httpx.MockTransport(lambda request: queue.pop(0))
    )
    provider = OpenAICompatibleProvider(config, client=client)
    provider._sleep = sleeps.append
    return provider, queue


OK = httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "hi"}}]})


def test_a_rate_limit_is_retried_after_what_the_server_says():
    sleeps: List[float] = []
    provider, queue = _provider(
        [httpx.Response(429, headers={"retry-after": "7"}, json={"error": "slow down"}), OK], sleeps
    )
    assert provider.complete("s", [ChatMessage("user", "q")]).text == "hi"
    assert sleeps == [7.0] and not queue


def test_an_overloaded_server_is_retried_with_backoff():
    sleeps: List[float] = []
    provider, _ = _provider([httpx.Response(503), httpx.Response(502), OK], sleeps)
    assert provider.complete("s", [ChatMessage("user", "q")]).text == "hi"
    assert sleeps == [2.0, 4.0]


def test_a_rate_limit_that_lasts_says_so():
    sleeps: List[float] = []
    provider, _ = _provider([httpx.Response(429, json={"error": "limit"})] * 3, sleeps)
    with pytest.raises(AIError, match="HTTP 429") as e:
        provider.complete("s", [ChatMessage("user", "q")])
    assert "retried up to 2 times" in e.value.message and len(sleeps) == 2


def test_a_long_retry_after_is_not_waited_for():
    sleeps: List[float] = []
    provider, queue = _provider(
        [httpx.Response(429, headers={"retry-after": "3600"}, json={"error": "daily"}), OK], sleeps
    )
    with pytest.raises(AIError, match="HTTP 429"):
        provider.complete("s", [ChatMessage("user", "q")])
    assert sleeps == [] and queue == [OK]


def test_a_client_error_is_not_retried():
    sleeps: List[float] = []
    provider, queue = _provider([httpx.Response(400, json={"error": "bad"}), OK], sleeps)
    with pytest.raises(AIError, match="HTTP 400"):
        provider.complete("s", [ChatMessage("user", "q")])
    assert sleeps == [] and queue == [OK]


# ── Anthropic: options by version, learnt from a 400 ────────────────────────


@pytest.mark.parametrize(
    "model, version, effort, fallbacks",
    [
        ("claude-opus-5-5", ("opus", 5, 5), True, True),
        ("claude-sonnet-5-5", ("sonnet", 5, 5), True, True),
        ("claude-haiku-5-5", ("haiku", 5, 5), True, False),
        ("claude-opus-6", ("opus", 6, 0), True, True),
        ("claude-opus-4-7", ("opus", 4, 7), True, False),
        ("claude-opus-4-1", ("opus", 4, 1), False, False),
        ("claude-sonnet-4-20250514", ("sonnet", 4, 0), False, False),
        ("claude-haiku-4-5", ("haiku", 4, 5), False, False),
        ("claude-3-5-haiku-latest", ("haiku", 3, 5), False, False),
        ("my-gateway-model", None, True, False),
    ],
)
def test_claude_options_follow_the_version(model, version, effort, fallbacks):
    assert claude_version(model) == version
    assert takes_effort(model) is effort
    assert takes_fallbacks(model) is fallbacks


class _Messages:
    def __init__(self, reject: str = ""):
        self.reject, self.calls = reject, []

    @contextmanager
    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject and self.reject in json.dumps(kwargs):
            error = sys.modules["anthropic"].APIStatusError(f"{self.reject}: not supported")
            error.status_code, error.message = 400, f"{self.reject}: Extra inputs not permitted"
            raise error
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            stop_reason="end_turn",
            model="m",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        yield SimpleNamespace(get_final_message=lambda: response)


@pytest.fixture
def fake_anthropic(monkeypatch):
    module = types.ModuleType("anthropic")
    for name in ("AuthenticationError", "NotFoundError", "RateLimitError", "APIConnectionError"):
        setattr(module, name, type(name, (Exception,), {}))
    module.APIStatusError = type("APIStatusError", (Exception,), {})
    module.APITimeoutError = type("APITimeoutError", (module.APIConnectionError,), {})
    monkeypatch.setitem(sys.modules, "anthropic", module)


def test_a_model_that_rejects_effort_is_asked_again_without_it(fake_anthropic):
    messages = _Messages(reject="output_config")
    config = build_config("anthropic", model="claude-opus-6", base_url="https://gw.example/v1")
    provider = AnthropicProvider(config, "k", client=SimpleNamespace(messages=messages))
    assert provider.complete("s", [ChatMessage("user", "q")]).text == "ok"
    assert "output_config" in messages.calls[0] and "output_config" not in messages.calls[1]
    provider.complete("s", [ChatMessage("user", "q")])
    assert "output_config" not in messages.calls[2]  # remembered


def test_another_400_is_an_error(fake_anthropic):
    messages = _Messages(reject="messages")
    config = build_config("anthropic", model="claude-opus-6", base_url="https://gw.example/v1")
    provider = AnthropicProvider(config, "k", client=SimpleNamespace(messages=messages))
    with pytest.raises(AIError, match="HTTP 400"):
        provider.complete("s", [ChatMessage("user", "q")])


# ── one-shot features: one more try when the answer is unreadable or cut ────


def test_ask_retries_an_unreadable_answer_and_adds_the_usage():
    from ducta.ai.loop import ask

    provider = Canned("no yaml here", "```yaml\nfindings: []\n```")
    completion, usage = ask(
        provider, "s", "m", readable=lambda t: "findings" in t, again="Only the block."
    )
    assert "findings" in completion.text and usage["input_tokens"] == 200
    assert provider.calls[1][-1].content == "Your answer could not be read. Only the block."


def test_ask_retries_a_cut_answer_and_keeps_the_first_if_the_retry_fails():
    from ducta.ai.loop import ask

    provider = Canned(("partial", True))
    completion, usage = ask(provider, "s", "m", readable=lambda t: True, again="Again.")
    assert completion.text == "partial" and usage["input_tokens"] == 100
    assert "cut off" in provider.calls[1][-1].content


def test_an_explanation_cut_short_says_so(tmp_path):
    from ducta.ai.explain import EXPLAIN_PROMPT, explain_failure
    from ducta.ai.loop import prompt_version

    diagnosis = {"kind": "code", "title": "KeyError", "message": "KeyError: 'x'"}
    out = explain_failure(_project(tmp_path), diagnosis, "", Canned(("a", True), ("b", True)))
    assert out.text.startswith("b") and "cut off" in out.text
    assert out.prompt_version == prompt_version(EXPLAIN_PROMPT)
    assert out.usage["input_tokens"] == 200


def test_an_explanation_that_cannot_fit_a_small_window_is_refused_before_asking(tmp_path):
    from ducta.ai.explain import explain_failure

    provider = Canned("never")
    provider.config = AIConfig(
        provider="ollama", model="m", base_url="http://localhost:1/v1", context_tokens=2000
    )
    diagnosis = {"kind": "code", "title": "t", "message": "m"}
    with pytest.raises(AIConfigError, match="context window"):
        explain_failure(_project(tmp_path), diagnosis, "x" * 9000, provider)
    assert provider.calls == []


def test_a_pipeline_review_tries_again_when_its_answer_cannot_be_read(tmp_path):
    from ducta.ai.pipeline_review import review_pipeline

    answer = "```yaml\nfindings: []\nideas: [a node that counts orders]\n```"
    review = review_pipeline(_project(tmp_path), "etl", Canned("sorry", answer))
    assert review.notes == "" and review.ideas == ["a node that counts orders"]
    assert review.usage["input_tokens"] == 200 and review.prompt_version


def test_a_node_review_notes_a_cut_answer(tmp_path):
    from ducta.ai.review import review_node

    review = review_node(_project(tmp_path), "etl", "etl.clean", Canned(("x", True), ("y", True)))
    assert "cut off" in review.notes


# ── the project's ai: block ─────────────────────────────────────────────────


def _with_ai(root: Path, block: str) -> Path:
    path = root / "ducta.yaml"
    path.write_text(path.read_text() + block)
    return root


def test_ai_off_stops_every_feature_before_any_request(tmp_path):
    from ducta.ai.builder import fix, generate
    from ducta.ai.explain import explain_failure
    from ducta.ai.pipeline_review import review_pipeline

    root = _with_ai(_project(tmp_path), "ai: {enabled: false}\n")
    provider = Canned(GOOD)
    for call in (
        lambda: generate(root, "totals", provider),
        lambda: fix(root, "etl", provider, note="n"),
        lambda: review_pipeline(root, "etl", provider),
        lambda: explain_failure(root, {"title": "t"}, "e", provider),
    ):
        with pytest.raises(AIPolicyError, match="ai.enabled: false"):
            call()
    assert provider.calls == []


def test_local_only_refuses_a_remote_model_and_accepts_a_local_one(tmp_path):
    from ducta.ai.builder import generate

    root = _with_ai(_project(tmp_path), "ai: {remote: false}\n")
    with pytest.raises(AIPolicyError, match="only a local model") as e:
        generate(root, "totals", Canned(GOOD, config=REMOTE))
    assert e.value.http_status == 403
    assert generate(root, "totals", Canned(GOOD)).ok


def test_an_unreadable_ai_block_allows_nothing(tmp_path):
    from ducta.ai.policy import project_policy

    root = _with_ai(_project(tmp_path), "ai: {remote: maybe}\n")
    with pytest.raises(AIPolicyError, match="ai.remote"):
        project_policy(root)


def test_the_policy_is_read_even_when_the_project_does_not_validate(tmp_path):
    from ducta.ai.policy import project_policy

    root = _with_ai(_project(tmp_path), "ai: {remote: false}\n")
    (root / "pipelines" / "etl.yaml").write_text("nodes: [broken")
    assert project_policy(root).remote is False


def test_the_ai_block_is_part_of_the_project_schema(tmp_path):
    from ducta.setting.project.loader import validate_project

    root = _with_ai(_project(tmp_path), "ai: {enabled: true, remote: false}\n")
    assert validate_project(root).project.ai.remote is False


def test_sentinel_notes_a_project_that_turns_ai_off(tmp_path):
    from ducta.ai.agents.sentinel.propose import propose

    root = _with_ai(_project(tmp_path), "ai: {enabled: false}\n")
    notes: List[str] = []
    incident = SimpleNamespace(
        runbook="propose_fix",
        last_run_id="r",
        id="i",
        links={},
        note=lambda actor, kind, text: notes.append(text),
    )
    event = SimpleNamespace(run_id="r", error="boom", pipeline="etl")
    policy = SimpleNamespace(propose=SimpleNamespace(explain=True, fix_draft=True, remote=False))
    out = propose(root, incident, event, {"title": "t"}, policy, Canned(), requested=True)
    assert out == {"explanation": None, "draft": None}
    assert any("ai.enabled: false" in n for n in notes)


# ── ducta ai eval ───────────────────────────────────────────────────────────


def test_eval_cases_are_known_and_unknown_ones_refused():
    from ducta.ai.evals import CASES, select

    assert len({c.id for c in CASES}) == len(CASES) >= 7
    assert [c.id for c in select(["review-pipeline"])] == ["review-pipeline"]
    with pytest.raises(AIConfigError, match="Unknown eval case"):
        select(["nope"])


def test_every_break_applies_to_the_template(tmp_path):
    from ducta.ai.evals import CASES, _break, make_template

    template = make_template(tmp_path)
    for case in CASES:
        if case.breaks:
            copy = tmp_path / case.id
            import shutil

            shutil.copytree(template, copy)
            _break(copy, case)


def test_eval_runs_cases_on_copies_and_reports(tmp_path):
    from ducta.ai.evals import run_eval, select

    good_explanation = (
        "**What happened** transform failed.\n**Why** column amount_usd is missing.\n"
        "**What to do** use amount."
    )
    provider = Canned(
        "```yaml\nfindings: []\nideas: []\n```",
        good_explanation,
        "I cannot help with that.",  # the explanation case of the second run: no parts
        "still nothing",
    )
    seen: List[str] = []
    report = run_eval(
        provider,
        select(["review-pipeline", "explain-keyerror"]),
        on_result=lambda r: seen.append(r.case),
    )
    assert seen == ["review-pipeline", "explain-keyerror"]
    assert report.passed == 2 and report.summary()["pass_rate"] == 1.0
    assert report.summary()["usage"]["input_tokens"] == 200
    assert all(r.prompt_version for r in report.results)

    failed = run_eval(provider, select(["explain-keyerror"]))
    assert failed.passed == 0 and "no 'What happened' part" in failed.results[0].misses


def test_a_fix_case_passes_when_the_draft_repairs_the_template(tmp_path):
    from ducta.ai.evals import make_template, run_case, select

    case = select(["fix-wrong-dataset"])[0]
    root = make_template(tmp_path)
    original = (root / "pipelines" / "etl.yaml").read_text()
    answer = f"```yaml file=pipelines/etl.yaml\n{original}```\nThe input was misspelt."
    result = run_case(root, case, Canned(answer))
    assert result.passed, result.misses
    assert result.attempts == 1 and result.usage["input_tokens"] == 100


def test_the_eval_command_asks_before_sending_the_template_to_a_remote_model(monkeypatch):
    from ducta.console.commands import ai_cmds

    monkeypatch.setattr("ducta.ai.config.load_config", lambda: REMOTE)
    monkeypatch.setattr("ducta.ai.providers.make_provider", lambda config: Canned(config=config))
    monkeypatch.setattr(ai_cmds.sys.stdin, "isatty", lambda: False)
    ran: List[int] = []
    monkeypatch.setattr("ducta.ai.evals.run_eval", lambda *a, **k: ran.append(1))
    args = SimpleNamespace(ai_command="eval", case=None, out=None, yes=False, output_format="rich")
    assert ai_cmds.AICommands.handle(args) != 0 and ran == []
