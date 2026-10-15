"""Choosing a model: presets, the config file, keys, and the two wire protocols."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from ducta.ai import secrets
from ducta.ai.config import build_config, load_config, save_config
from ducta.ai.errors import AIError
from ducta.ai.providers import (
    AnthropicProvider,
    ChatMessage,
    OllamaProvider,
    OpenAICompatibleProvider,
    make_provider,
)
from ducta.ai.secrets import mask, require_key, resolve_key

# ── config ───────────────────────────────────────────────────────────────────


def test_a_preset_fills_in_where_to_reach_it(tmp_path):
    config = build_config("ollama", model="qwen2.5-coder:14b")
    assert config.base_url == "http://localhost:11434/v1"
    assert config.is_local
    path = save_config(config, tmp_path / "ai.toml")
    # Only what differs from the preset is written; never a key.
    assert path.read_text() == 'provider = "ollama"\nmodel = "qwen2.5-coder:14b"\n'
    assert load_config(path, env={}).base_url == "http://localhost:11434/v1"


def test_remote_providers_are_not_local():
    assert not build_config("anthropic").is_local
    assert build_config("anthropic").model == "claude-opus-5-5"
    assert not build_config("openai", model="m").is_local
    assert build_config("openai_compatible", base_url="http://127.0.0.1:8000/v1/").is_local


def test_environment_overrides_the_file(tmp_path):
    path = save_config(build_config("ollama", model="a"), tmp_path / "ai.toml")
    assert load_config(path, env={"DUCTA_AI_MODEL": "b"}).model == "b"
    # Another provider starts from its own preset, not the file's URL.
    other = load_config(path, env={"DUCTA_AI_PROVIDER": "anthropic"})
    assert other.provider == "anthropic" and other.base_url is None


def test_no_config_says_how_to_make_one(tmp_path):
    with pytest.raises(AIError, match="ducta ai setup"):
        load_config(tmp_path / "missing.toml", env={})


def test_unknown_provider_and_missing_url_are_rejected():
    with pytest.raises(AIError, match="Unknown AI provider"):
        build_config("nope")
    with pytest.raises(AIError, match="needs a base URL"):
        build_config("openai_compatible")


# ── keys ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def no_keychain(monkeypatch):
    monkeypatch.setattr(secrets, "_keyring", lambda: None)


def test_the_environment_key_wins(no_keychain):
    config = build_config("anthropic")
    key = resolve_key(config, env={"ANTHROPIC_API_KEY": "sk-ant-1234567890abcd"})
    assert key.source == "env:ANTHROPIC_API_KEY"
    assert key.masked == "sk-…abcd"
    assert "1234567890" not in mask(key.value)


def test_the_keychain_is_next(monkeypatch):
    store = {}
    fake = SimpleNamespace(
        get_password=lambda s, u: store.get((s, u)),
        set_password=lambda s, u, k: store.__setitem__((s, u), k),
    )
    monkeypatch.setattr(secrets, "_keyring", lambda: fake)
    monkeypatch.setattr(secrets, "keychain_available", lambda: True)
    secrets.store_key("anthropic", "  sk-ant-from-keychain  ")
    key = resolve_key(build_config("anthropic"), env={})
    assert (key.value, key.source) == ("sk-ant-from-keychain", "keychain")


def test_a_remote_provider_without_a_key_says_how_to_add_one(no_keychain):
    with pytest.raises(AIError, match="ducta ai login"):
        require_key(build_config("anthropic"), env={})
    # A local model needs none.
    assert require_key(build_config("ollama", model="m"), env={}) is None


# ── OpenAI-compatible ────────────────────────────────────────────────────────


def _openai(handler, **config):
    config = build_config("ollama", model="m", **config)
    client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(config, client=client)


def test_openai_compatible_completion():
    seen = {}

    def handler(request):
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "hi"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    out = _openai(handler).complete("sys", [ChatMessage("user", "q")])
    assert (out.text, out.truncated, out.usage["input_tokens"]) == ("hi", True, 3)
    assert seen["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_compatible_lists_models():
    provider = _openai(lambda r: httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]}))
    assert provider.list_models() == ["a", "b"]


@pytest.mark.parametrize(
    "status, match",
    [(401, "rejected the API key"), (404, "does not serve model"), (500, "HTTP 500")],
)
def test_openai_compatible_errors_are_explained(status, match):
    provider = _openai(lambda r: httpx.Response(status, text="boom"))
    with pytest.raises(AIError, match=match):
        provider.complete("s", [ChatMessage("user", "q")])


def test_a_local_server_that_is_down_is_named():
    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(AIError, match="ollama serve"):
        _openai(refuse).list_models()


# ── Anthropic ────────────────────────────────────────────────────────────────


class _FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response

    @contextmanager
    def stream(self, **kwargs):
        self.kwargs, self.streamed = kwargs, True
        yield SimpleNamespace(get_final_message=lambda: self.response)


def _anthropic_response(stop_reason="end_turn", text="ok"):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(explanation="policy"),
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=10, output_tokens=2),
    )


@pytest.fixture
def fake_sdk(monkeypatch):
    module = types.ModuleType("anthropic")
    for name in (
        "AuthenticationError",
        "NotFoundError",
        "RateLimitError",
        "APIStatusError",
        "APIConnectionError",
    ):
        setattr(module, name, type(name, (Exception,), {}))
    module.APITimeoutError = type("APITimeoutError", (module.APIConnectionError,), {})
    monkeypatch.setitem(sys.modules, "anthropic", module)


def test_anthropic_uses_server_side_fallbacks_on_current_models(fake_sdk):
    beta = _FakeMessages(_anthropic_response())
    client = SimpleNamespace(beta=SimpleNamespace(messages=beta), messages=None)
    config = build_config("anthropic", effort="high")
    out = AnthropicProvider(config, "k", client=client).complete("sys", [ChatMessage("user", "q")])
    assert out.text == "ok"
    assert beta.kwargs["fallbacks"] == "default"
    assert beta.kwargs["output_config"] == {"effort": "high"}
    assert "temperature" not in beta.kwargs


def test_anthropic_other_models_use_the_plain_endpoint(fake_sdk):
    plain = _FakeMessages(_anthropic_response(stop_reason="max_tokens"))
    client = SimpleNamespace(messages=plain)
    config = build_config("anthropic", model="claude-haiku-4-5")
    out = AnthropicProvider(config, "k", client=client).complete("s", [ChatMessage("user", "q")])
    assert out.truncated and "fallbacks" not in plain.kwargs


def test_anthropic_refusal_is_an_error(fake_sdk):
    beta = _FakeMessages(_anthropic_response(stop_reason="refusal"))
    client = SimpleNamespace(beta=SimpleNamespace(messages=beta))
    with pytest.raises(AIError, match="declined"):
        AnthropicProvider(build_config("anthropic"), "k", client=client).complete(
            "s", [ChatMessage("user", "q")]
        )


def test_make_provider_picks_the_protocol(no_keychain, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    assert isinstance(make_provider(build_config("anthropic")), AnthropicProvider)
    assert isinstance(make_provider(build_config("ollama", model="m")), OllamaProvider)
    assert type(make_provider(build_config("lmstudio", model="m"))) is OpenAICompatibleProvider


def _ollama(handler, **config):
    config = build_config("ollama", model="m", **config)
    client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
    return OllamaProvider(config, client=client)


def test_ollama_asks_for_a_context_window_on_its_native_endpoint():
    import json

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "m",
                "message": {"content": "hi"},
                "prompt_eval_count": 900,
                "eval_count": 2,
                "done_reason": "stop",
            },
        )

    out = _ollama(handler).complete("sys", [ChatMessage("user", "q")])
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["body"]["options"]["num_ctx"] == 16384 and seen["body"]["stream"] is False
    assert (out.text, out.usage["input_tokens"]) == ("hi", 900)


def test_ollama_says_when_the_context_window_is_full():
    full = {"model": "m", "message": {"content": "x"}, "prompt_eval_count": 16384}
    with pytest.raises(AIError, match="context_tokens"):
        _ollama(lambda r: httpx.Response(200, json=full)).complete("s", [ChatMessage("user", "q")])
