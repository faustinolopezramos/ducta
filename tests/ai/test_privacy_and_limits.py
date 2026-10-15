"""What the 2026-10-15 review fixed: credentials written in YAML or settings
never reach a remote model, a draft on disk is held to its kind's rules, a
request fits a local model's window, and the providers' and skill's details."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.ai import secrets
from ducta.ai.builder import (
    Draft,
    _sha,
    apply_draft,
    fix,
    generate,
    load_draft,
    message_budget,
    revise,
    save_draft,
)
from ducta.ai.config import AIConfig, build_config, load_config
from ducta.ai.context import (
    build_context,
    find_secrets,
    is_secret_name,
    redact_code,
    redact_config,
)
from ducta.ai.errors import AIConfigError, AIConflictError, AIEnvironmentError, AIError
from ducta.ai.explain import explanation_message
from ducta.ai.providers import AnthropicProvider, ChatMessage
from ducta.ai.review import ReviewFacts, _code_findings, _render

sys.path.insert(0, str(Path(__file__).parent))
from test_builder import FakeProvider, _project  # noqa: E402
from test_config_and_providers import (  # noqa: E402,F401
    _anthropic_response,
    _FakeMessages,
    fake_sdk,
)

SKILL = Path(__file__).parents[2] / "src" / "ducta" / "skills" / "ducta"
INLINE = "      options: {user: etl, password: Hunter2Hunter2}\n"


class RemoteFake(FakeProvider):
    def __init__(self, *answers: str):
        super().__init__(*answers)
        self.config = AIConfig(provider="anthropic", model="m")


@pytest.fixture
def sales(tmp_path):
    """The skill's example project, with a password written in an ingest's options."""
    root = tmp_path / "sales"
    shutil.copytree(SKILL / "assets" / "examples" / "sales", root)
    path = root / "pipelines" / "bronze.sales.yaml"
    path.write_text(
        path.read_text().replace("      source: shop_db\n", "      source: shop_db\n" + INLINE)
    )
    return root


# ── what counts as a credential ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "password",
        "db_pwd",
        "sasToken",
        "apiKey",
        "fs.s3a.secret.key",
        "spark.hadoop.fs.azure.account.key.acc.dfs.core.windows.net",
    ],
)
def test_credential_names(name):
    assert is_secret_name(name)


@pytest.mark.parametrize(
    "name", ["api_key_env", "token_url", "password_file", "max_tokens", "tokenizer", "source"]
)
def test_names_about_a_credential_are_not_one(name):
    assert not is_secret_name(name)


def test_unquoted_yaml_credentials_are_found_and_masked():
    text = "options:\n  password: Hunter2Hunter2\nconn: {user: a, token: abcdef123}\n"
    assert find_secrets(text, yaml=True)
    masked = redact_code(text, yaml=True)
    assert "Hunter2Hunter2" not in masked and "abcdef123" not in masked
    assert "user: a" in masked


def test_yaml_placeholders_and_flags_are_not_credentials():
    text = (
        "password: ${DB_PASSWORD}\nuse_token: true\napi_key_env: OPENAI_API_KEY\n"
        "token_url: https://login/x\n"
    )
    assert find_secrets(text, yaml=True) == []
    # In Python, `name: Type` is an annotation, not a value.
    assert find_secrets("    token: SecretStr\n") == []


def test_redact_config_masks_by_name_and_inside_text():
    out = redact_config(
        {
            "options": {"password": "Hunter2", "user": "etl", "pass": "${P}"},
            "url": "jdbc:postgresql://etl:S3cret@db/x",
            "spark_config": {"spark.hadoop.fs.azure.account.key.a.dfs.core.windows.net": "K=="},
        }
    )
    assert out["options"] == {"password": "***", "user": "etl", "pass": "${P}"}
    assert "S3cret" not in out["url"]
    assert set(out["spark_config"].values()) == {"***"}


# ── nothing written in the project reaches a remote model ──────────────────


def test_the_context_masks_an_ingest_nodes_inline_credentials(sales):
    text = build_context(sales).render()
    assert "Hunter2Hunter2" not in text and "shop_db" in text


def test_a_fix_of_a_yaml_file_with_an_unquoted_credential_is_refused_remotely(sales):
    with pytest.raises(AIConfigError, match="credential"):
        fix(sales, "bronze.sales", RemoteFake(), note="add a where")


def test_a_revision_on_a_remote_model_rechecks_the_files_it_resends(sales):
    rel = "pipelines/bronze.sales.yaml"
    draft = Draft(
        id="20261015-000000-abcdef",
        request="r",
        provider="ollama",
        model="m",
        created_at="",
        ok=True,
        files={},
        base={},
        problems=[],
        kind="fix",
        pipeline="bronze.sales",
        prompt="the files, whole",
        raw_answer="an answer",
        seen={rel: _sha((sales / rel).read_text())},
    )
    remote = RemoteFake("never asked")
    with pytest.raises(AIConfigError, match="credential"):
        revise(sales, draft, "also filter", remote)
    assert remote.calls == []


def test_an_explanation_masks_the_diagnosis_too():
    error = "Connection failed: postgresql://etl:S3cretPass@db:5432/x"
    diagnosis = {"kind": "infra", "message": error, "hint": "check password=S3cretPass"}
    assert "S3cretPass" not in explanation_message(Path("/tmp"), diagnosis, error)


def test_a_review_masks_the_nodes_settings():
    facts = ReviewFacts(
        pipeline="p",
        pipeline_rel="pipelines/p.yaml",
        node="n",
        env="dev",
        spec={"kind": "ingest", "ingest": {"options": {"password": "Hunter2Hunter2"}}},
        pipeline_settings={},
        settings={"spark_config": {"spark.hadoop.fs.s3a.secret.key": "S3KEYS3KEY"}},
        effective={"retry": (2, "node"), "spark_config": ({"fs.s3a.access.key": "AKEY"}, "")},
    )
    text = _render(facts, [], remote=True, note="")
    assert not any(s in text for s in ("Hunter2Hunter2", "S3KEYS3KEY", "AKEY"))
    assert '"retry": "2 (node)"' in text


def test_why_a_dataset_was_not_measured_is_masked(tmp_path, monkeypatch):
    from ducta.ai.proposals import quality_facts
    from ducta.api.services import dataset_preview

    root = tmp_path / "sales"
    shutil.copytree(SKILL / "assets" / "examples" / "sales", root)

    def unreadable(*_a, **_k):
        raise OSError("cannot open https://acc.blob.core.windows.net/x?sig=SIGSIGSIG123")

    monkeypatch.setattr(dataset_preview, "read_frame", unreadable)
    facts = quality_facts(root, "silver.sales", "clean_orders")
    assert facts.unmeasured and "SIGSIGSIG123" not in facts.unmeasured


# ── a draft on disk is held to its kind's rules ─────────────────────────────


def _draft(**kw):
    data = dict(
        id="20261015-000000-aaaaaa",
        request="r",
        provider="ollama",
        model="m",
        created_at="",
        ok=True,
        files={},
        base={},
        problems=[],
    )
    data.update(kw)
    return Draft(**data)


def test_apply_refuses_a_file_python_runs_on_its_own(tmp_path):
    root = _project(tmp_path)
    draft = _draft(files={"conftest.py": "import os\n"}, base={"conftest.py": None})
    with pytest.raises(AIConflictError, match="conftest.py"):
        apply_draft(root, draft, force=True)
    assert not (root / "conftest.py").exists()


def test_apply_refuses_a_file_the_draft_has_no_base_for(tmp_path):
    root = _project(tmp_path)
    draft = _draft(files={"src/extra.py": "x = 1\n"}, base={})
    with pytest.raises(AIConflictError, match="does not record"):
        apply_draft(root, draft, force=True)


def test_a_proposal_may_only_edit_its_own_yaml(sales):
    rel = "ducta.yaml"
    draft = _draft(
        kind="quality",
        pipeline="silver.sales",
        target="clean_orders",
        files={rel: "version: 2\nproject: hijacked\n"},
        base={rel: _sha((sales / rel).read_text())},
    )
    with pytest.raises(AIConflictError, match="only edits"):
        apply_draft(sales, draft, force=True)
    assert "hijacked" not in (sales / rel).read_text()


def test_a_draft_from_another_version_still_loads(tmp_path):
    root = _project(tmp_path)
    draft = _draft()
    save_draft(root, draft)
    path = root / ".ducta" / "ai" / "drafts" / f"{draft.id}.json"
    path.write_text(
        path.read_text().replace(
            '"attempts": []',
            '"attempts": [{"number": 1, "files": [], "errors": 0, "warnings": 0, '
            '"rejected": [], "usage": {}, "future": true}]',
        )
    )
    assert load_draft(root, draft.id).attempts[0].number == 1
    path.write_text('{"id": 1}')
    with pytest.raises(AIConflictError, match="not a readable draft"):
        load_draft(root, draft.id)


# ── a request fits a local model's window ───────────────────────────────────


def test_only_ollamas_window_limits_a_request():
    assert message_budget(AIConfig(provider="anthropic"), "s") is None
    small = AIConfig(provider="ollama", base_url="http://localhost:1/v1", context_tokens=32768)
    assert message_budget(small, "") > message_budget(
        AIConfig(provider="ollama", base_url="http://localhost:1/v1"), ""
    )


def test_a_window_too_small_is_said_before_asking(tmp_path):
    root = _project(tmp_path)
    provider = FakeProvider("never asked")
    provider.config.context_tokens = 7000
    with pytest.raises(AIConfigError, match="context_tokens"):
        generate(root, "a pipeline", provider)
    assert provider.calls == []


def test_a_retry_sends_only_the_last_answer(tmp_path):
    root = _project(tmp_path)
    provider = FakeProvider("no blocks", "still none", "nothing")
    generate(root, "a pipeline", provider, max_attempts=3)
    assert [len(c) for c in provider.calls] == [1, 3, 3]
    assert provider.calls[2][1].content == "still none"


# ── providers ───────────────────────────────────────────────────────────────


def test_anthropic_streams_with_room_for_thinking(fake_sdk):  # noqa: F811
    beta = _FakeMessages(_anthropic_response())
    client = SimpleNamespace(beta=SimpleNamespace(messages=beta))
    AnthropicProvider(build_config("anthropic"), "k", client=client).complete(
        "s", [ChatMessage("user", "q")]
    )
    assert getattr(beta, "streamed", False) and beta.kwargs["max_tokens"] == 64000


def test_an_anthropic_timeout_is_not_called_unreachable(fake_sdk):  # noqa: F811
    import anthropic

    class Slow:
        @contextmanager
        def stream(self, **_):
            raise anthropic.APITimeoutError()
            yield  # pragma: no cover

    client = SimpleNamespace(messages=Slow())
    config = build_config("anthropic", model="claude-haiku-4-5")
    with pytest.raises(AIError, match="did not answer"):
        AnthropicProvider(config, "k", client=client).complete("s", [ChatMessage("user", "q")])


def test_a_providers_own_key_variable_is_not_sent_to_another_endpoint(monkeypatch):
    monkeypatch.setattr(secrets, "_keyring", lambda: None)
    env = {"OPENAI_API_KEY": "sk-own-endpoint-only"}
    other = build_config("openai", base_url="https://gateway.example/v1", model="m")
    assert secrets.resolve_key(other, env).value is None
    with pytest.raises(AIConfigError, match="not sent to"):
        secrets.require_key(other, env)
    own = build_config("openai", model="m")
    assert secrets.require_key(own, env) == "sk-own-endpoint-only"
    named = build_config("openai", base_url="https://gw/v1", model="m", api_key_env="DUCTA_AI_GW")
    assert secrets.require_key(named, {"DUCTA_AI_GW": "k2"}) == "k2"


def test_a_keychain_that_fails_to_store_is_an_environment_error(monkeypatch):
    def refuse(*_):
        raise RuntimeError("locked")

    monkeypatch.setattr(secrets, "_keyring", lambda: SimpleNamespace(set_password=refuse))
    monkeypatch.setattr(secrets, "keychain_available", lambda: True)
    with pytest.raises(AIEnvironmentError, match="did not store"):
        secrets.store_key("anthropic", "sk-ant-x")


def test_switching_provider_by_variable_keeps_timeouts(tmp_path):
    path = tmp_path / "ai.toml"
    path.write_text('provider = "ollama"\nmodel = "q"\ntimeout_seconds = 900.0\n')
    config = load_config(path, env={"DUCTA_AI_PROVIDER": "anthropic"})
    assert (config.provider, config.model) == ("anthropic", "claude-opus-5-5")
    assert config.timeout_seconds == 900.0


# ── review ──────────────────────────────────────────────────────────────────


def test_writing_a_file_handle_is_not_writing_a_dataframe():
    lines = [
        "def f(df):",
        "    f.write('x')",
        "    sys.stdout.write('y')",
        "    df.write.parquet('p')",
        "    return df",
    ]
    facts = ReviewFacts("p", "pipelines/p.yaml", "n", "dev", {}, {}, {})
    facts.function, facts.code_lines = {"file": "m.py", "line": 1, "function": "f"}, lines
    io = [f.line for f in _code_findings(facts) if f.area == "code"]
    assert io == [4]


# ── the skill's environment check ───────────────────────────────────────────


def _check_env():
    spec = importlib.util.spec_from_file_location("check_env", SKILL / "scripts" / "check_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "head, expected",
    [
        ("#!/opt/venv/bin/python3.12\n", "/opt/venv/bin/python3.12"),
        (
            "#!/bin/sh\n'''exec' \"/Users/a b/venv/bin/python3\" \"$0\" \"$@\"\n' '''\n",
            "/Users/a b/venv/bin/python3",
        ),
        ("#!/bin/sh\necho not python\n", None),
        ("#!/usr/bin/ruby\n", None),
    ],
)
def test_check_env_only_hands_its_probe_to_a_python(tmp_path, head, expected):
    script = tmp_path / "ducta"
    script.write_text(head)
    assert _check_env()._ducta_python(str(script)) == expected
