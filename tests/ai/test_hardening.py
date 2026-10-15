"""What the 2026-10-11 review hardened: settings kept, keys bound to their
endpoint, re-validation on apply, catalog locations, module names, secrets in
what is sent, cancellation, and the providers' wire details."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ducta.ai import secrets
from ducta.ai.builder import apply_draft, assemble, fix, generate, parse_answer
from ducta.ai.config import AIConfig, build_config, load_config, save_config, update_config
from ducta.ai.context import build_context, find_secrets, redact_code
from ducta.ai.errors import AICancelledError, AIConfigError, AIError
from ducta.ai.providers import AnthropicProvider, ChatMessage, OpenAICompatibleProvider

sys.path.insert(0, str(Path(__file__).parent))
from test_builder import GOOD, FakeProvider, _broken, _project  # noqa: E402
from test_config_and_providers import (  # noqa: E402,F401
    _anthropic_response,
    _FakeMessages,
    fake_sdk,
)

# ── settings are merged, not rebuilt ────────────────────────────────────────


def test_saving_one_setting_keeps_the_others(tmp_path):
    path = tmp_path / "ai.toml"
    path.write_text(
        'provider = "ollama"\nmodel = "a"\ncontext_tokens = 32768\n'
        "timeout_seconds = 900.0\nmax_attempts = 5\nfuture_key = 1\n"
    )
    save_config(update_config("ollama", {"model": "b"}, path), path)
    config = load_config(path, env={})
    assert (config.model, config.context_tokens, config.timeout_seconds) == ("b", 32768, 900.0)
    assert config.max_attempts == 5 and config.extra == {"future_key": 1}


def test_switching_provider_drops_only_what_belonged_to_the_old_one(tmp_path):
    path = tmp_path / "ai.toml"
    path.write_text(
        'provider = "ollama"\nmodel = "qwen"\nbase_url = "http://gpu:11434/v1"\n'
        "timeout_seconds = 900.0\n"
    )
    config = update_config("anthropic", {}, path)
    assert config.model == "claude-opus-5-5" and config.base_url is None
    assert config.timeout_seconds == 900.0


def test_a_null_setting_goes_back_to_the_default(tmp_path):
    path = tmp_path / "ai.toml"
    path.write_text('provider = "ollama"\nmodel = "m"\nbase_url = "http://gpu:11434/v1"\n')
    assert update_config("ollama", {"base_url": None}, path).base_url == "http://localhost:11434/v1"


def test_a_base_url_must_be_http():
    with pytest.raises(AIConfigError, match="http"):
        build_config("openai_compatible", base_url="file:///etc/passwd")


# ── a stored key only goes where it was stored for ──────────────────────────


def test_a_keychain_key_is_bound_to_its_endpoint(monkeypatch):
    store = {}
    fake = SimpleNamespace(
        get_password=lambda s, u: store.get((s, u)),
        set_password=lambda s, u, k: store.__setitem__((s, u), k),
    )
    monkeypatch.setattr(secrets, "_keyring", lambda: fake)
    monkeypatch.setattr(secrets, "keychain_available", lambda: True)
    secrets.store_key("openai", "sk-the-real-openai-key")
    assert secrets.resolve_key(build_config("openai", model="m"), env={}).value
    elsewhere = build_config("openai", model="m", base_url="https://evil.example/v1")
    assert secrets.resolve_key(elsewhere, env={}).value is None
    assert secrets.keychain_user("openai", "https://evil.example/v1") == "openai@evil.example"


# ── apply checks the project as it is now ───────────────────────────────────


def test_apply_revalidates_against_the_current_project(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(GOOD))
    assert draft.ok
    # Meanwhile, someone else adds a node with the same name in another file.
    (root / "pipelines" / "other.yaml").write_text(
        "nodes:\n  silver.totals:\n    run: src.m:clean\n    inputs: {orders: raw}\n"
        "    outputs: [clean]\n"
    )
    with pytest.raises(AIConfigError, match="no longer validates"):
        apply_draft(root, draft)
    assert not (root / "src" / "totals.py").exists()
    assert apply_draft(root, draft, force=True)


def test_apply_refuses_an_invalid_draft_without_force(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(GOOD))
    draft.ok = False
    with pytest.raises(AIConfigError, match="does not validate"):
        apply_draft(root, draft)


# ── catalog entries cannot point at existing data ───────────────────────────


def _assembled(root: Path, catalog: str):
    answer = parse_answer(
        GOOD.replace("silver.sales.totals: {format: parquet, path: d/totals}", catalog)
    )
    return assemble(root, build_context(root), answer)


def test_a_new_dataset_cannot_reuse_an_existing_path(tmp_path):
    root = _project(tmp_path)
    out = _assembled(root, "silver.sales.totals: {format: parquet, path: ./d/clean/}")
    assert any("where clean lives" in r for r in out.rejected)
    assert "silver.sales.totals" not in out.new_datasets


def test_a_written_dataset_stays_inside_the_project(tmp_path):
    root = _project(tmp_path)
    for path in ("/var/data/x", "../x", "s3://bucket/x"):
        out = _assembled(root, f"silver.sales.totals: {{format: parquet, path: '{path}'}}")
        assert any("inside the project" in r for r in out.rejected), path


def test_unknown_catalog_keys_are_refused(tmp_path):
    root = _project(tmp_path)
    out = _assembled(root, "silver.sales.totals: {format: parquet, connection: prod}")
    assert any("unknown key" in r for r in out.rejected)


# ── new modules do not hide others ──────────────────────────────────────────


def test_a_new_module_cannot_shadow_the_standard_library(tmp_path):
    root = _project(tmp_path)
    answer = parse_answer(GOOD.replace("src/totals.py", "json.py"))
    out = assemble(root, build_context(root), answer)
    assert any("'json' is the name of a Python module" in r for r in out.rejected)
    answer = parse_answer(GOOD.replace("src/totals.py", "src/statistics.py"))
    out = assemble(root, build_context(root), answer)
    assert any("'statistics'" in r for r in out.rejected)


# ── secrets in what is sent ─────────────────────────────────────────────────


def test_code_secrets_are_found_and_masked_but_not_lookalikes():
    code = (
        'password = "hunter2-real"\ntoken = tokenize(x)\npw: "${DB_PASS}"\n'
        'url = "postgres://u:p4ss@h/db"\nsecret = "changeme"\n'
    )
    assert find_secrets(code) == [
        "a URL with a password",
        "a quoted password, secret, token or key",
    ]
    masked = redact_code(code)
    assert "hunter2" not in masked and "p4ss" not in masked
    assert "tokenize(x)" in masked and "${DB_PASS}" in masked


def test_a_fix_does_not_send_a_file_with_a_credential_to_a_remote_model(tmp_path):
    root = _broken(tmp_path)
    (root / "src" / "m.py").write_text(
        'KEY = "sk-abcdefghijklmnopqrstuvwxyz"\ndef clean(df):\n    return df\n'
    )
    remote = FakeProvider()
    remote.config = AIConfig(provider="anthropic", model="m")
    with pytest.raises(AIConfigError, match="credential"):
        fix(root, "etl", remote)
    assert remote.calls == []
    # A local model may see it: nothing leaves the machine.
    local = FakeProvider("no blocks")
    fix(root, "etl", local, max_attempts=1)
    assert "sk-abcdef" in local.calls[0][0].content


def test_the_example_function_is_sent_masked(tmp_path):
    root = _project(tmp_path)
    (root / "src" / "m.py").write_text(
        'def clean(orders, api_key="sk-abcdefghijklmnopqrstuvwxyz"):\n    return orders\n'
    )
    assert "sk-abcdef" not in build_context(root).render()


def test_a_fix_too_large_to_send_is_refused(tmp_path):
    root = _broken(tmp_path)
    (root / "src" / "m.py").write_text("def clean(df):\n    return df\n" + "# x\n" * 20_000)
    with pytest.raises(AIConfigError, match="too large"):
        fix(root, "etl", FakeProvider())


# ── stopping ────────────────────────────────────────────────────────────────


def test_a_stopped_draft_makes_no_more_requests(tmp_path):
    root = _project(tmp_path)
    provider = FakeProvider("nothing usable", GOOD)
    stops = iter([False, True])
    with pytest.raises(AICancelledError):
        generate(root, "totals", provider, should_stop=lambda: next(stops))
    assert len(provider.calls) == 1


# ── providers ───────────────────────────────────────────────────────────────


def test_openai_retries_without_temperature_when_the_model_refuses_it():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(
                400, json={"error": {"message": "Unsupported value: 'temperature'"}}
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    config = build_config("openai", model="o3")
    client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(config, "k", client=client)
    assert provider.complete("s", [ChatMessage("user", "q")]).text == "ok"
    assert provider.complete("s", [ChatMessage("user", "q")]).text == "ok"
    assert ["temperature" in b for b in bodies] == [True, False, False]


def test_an_error_page_is_not_echoed():
    config = build_config("openai_compatible", base_url="http://intranet:8080/v1", model="m")
    client = httpx.Client(
        base_url=config.base_url,
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="<html>admin</html>")),
    )
    with pytest.raises(AIError) as e:
        OpenAICompatibleProvider(config, client=client).complete("s", [ChatMessage("user", "q")])
    assert "admin" not in e.value.message


def test_anthropic_caches_the_context_and_defaults_to_high_effort(fake_sdk):  # noqa: F811
    beta = _FakeMessages(_anthropic_response())
    client = SimpleNamespace(beta=SimpleNamespace(messages=beta))
    AnthropicProvider(build_config("anthropic"), "k", client=client).complete(
        "sys", [ChatMessage("user", "context"), ChatMessage("assistant", "a")]
    )
    assert beta.kwargs["output_config"] == {"effort": "high"}
    assert beta.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    first = beta.kwargs["messages"][0]["content"][0]
    assert first["text"] == "context" and first["cache_control"] == {"type": "ephemeral"}
    assert beta.kwargs["messages"][1] == {"role": "assistant", "content": "a"}


def test_anthropic_older_models_get_no_effort(fake_sdk):  # noqa: F811
    plain = _FakeMessages(_anthropic_response())
    client = SimpleNamespace(messages=plain)
    config = build_config("anthropic", model="claude-haiku-4-5")
    AnthropicProvider(config, "k", client=client).complete("s", [ChatMessage("user", "q")])
    assert "output_config" not in plain.kwargs


def test_a_problems_fix_reaches_the_model():
    """A Problem's fix is {label, replace: [old, new]}: the model is told both."""
    from ducta.ai.builder import _describe

    text = _describe(
        {
            "file": "pipelines/etl.yaml",
            "line": 4,
            "message": "unknown key 'timout'",
            "fix": {"label": "Use 'timeout_seconds'", "replace": ["timout", "timeout_seconds"]},
        }
    )
    assert "pipelines/etl.yaml:4" in text
    assert "Use 'timeout_seconds'" in text and "replace 'timout' with 'timeout_seconds'" in text


# pipelines/<name>.yaml: two levels up leaves the project.
@pytest.mark.parametrize("name", ["../../outside", "a/../../../outside", "..\\..\\outside", ""])
def test_a_pipeline_name_cannot_reach_outside_the_project(tmp_path, name):
    from ducta.ai.builder import fix_scope
    from ducta.ai.errors import AINotFoundError

    project = tmp_path / "project"
    (project / "pipelines").mkdir(parents=True)
    (tmp_path / "outside.yaml").write_text("nodes: {secret: {}}\n", encoding="utf-8")

    with pytest.raises(AINotFoundError):
        fix_scope(project, name)
