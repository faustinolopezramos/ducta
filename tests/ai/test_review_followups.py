"""The 2026-10-19 review: credentials in free text, the code review's reach, limits,
and the files the AI features write."""

from __future__ import annotations

import json
import os

import pytest

from ducta.ai import fsutil
from ducta.ai.builder import Draft, list_drafts, load_draft
from ducta.ai.config import AIConfig, save_config
from ducta.ai.context import _imports, redact
from ducta.ai.errors import AIConfigError
from ducta.ai.review import ReviewFacts, _code_findings
from ducta.ai.secrets import keychain_user

# ── redact: a credential's name may carry a prefix ──────────────────────────


@pytest.mark.parametrize(
    "text, leaked",
    [
        ("db_password=hunter2", "hunter2"),
        ("DB_PASSWORD=hunter2", "hunter2"),
        ("PGPASSWORD=hunter2", "hunter2"),
        ("AWS_SECRET_ACCESS_KEY=abcd1234efgh", "abcd1234efgh"),
        ("{'jdbc_password': 's3cret'}", "s3cret"),
        ("spark.hadoop.fs.s3a.secret.key=abcd1234", "abcd1234"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("https://x.blob/c?sig=Zm9vYmFy&se=1", "Zm9vYmFy"),
        ("password=hunter2", "hunter2"),
    ],
)
def test_redact_masks_credentials_whatever_their_prefix(text, leaked):
    out = redact(text)
    assert leaked not in out and "***" in out


@pytest.mark.parametrize(
    "text", ["value assigned: None", "design=2", "max_tokens=100 left", "retry in 5s"]
)
def test_redact_leaves_ordinary_words_alone(text):
    assert redact(text) == text


# ── the example function keeps its imports whole ────────────────────────────


def test_a_parenthesised_import_is_kept_whole():
    source = "from __future__ import annotations\nfrom pyspark.sql import (\n    DataFrame,\n    functions as F,\n)\nimport os\n\n\ndef f(x): ...\n"
    found = _imports(source)
    assert found == [
        "from pyspark.sql import (\n    DataFrame,\n    functions as F,\n)",
        "import os",
    ]
    compile("\n".join(found), "<imports>", "exec")


# ── the code review's reach ─────────────────────────────────────────────────


def _titles(code: str):
    facts = ReviewFacts("", "", "", "dev", {}, {}, {})
    facts.function = {"file": "m.py", "line": 1, "function": ""}
    facts.code_lines = code.splitlines()
    return [f.title for f in _code_findings(facts)]


@pytest.mark.parametrize(
    "code",
    [
        "import subprocess\nsubprocess.run(['ls'])",
        "from subprocess import run",
        "import os\nos.system('id')",
        "import requests\nrequests.get('http://x')",
        "import urllib.request\nurllib.request.urlopen('http://x')",
        "from pathlib import Path\nPath('x').write_text('y')",
        "exec('print(1)')",
        "__import__('os')",
        "spark.sql('DROP TABLE t')",
        "spark.sql('  delete from t where 1=1')",
    ],
)
def test_commands_network_deletion_and_eval_are_flagged(code):
    assert _titles(code), code


def test_spark_sql_that_only_reads_is_not_flagged():
    assert _titles("df = spark.sql('select a from t')") == []


def test_a_writer_with_no_path_serialises_in_memory_and_is_not_flagged():
    assert _titles("s = df.to_json()") == []
    assert _titles("s = df.to_csv(index=False)") == []
    assert _titles("df.to_csv('out.csv')")
    assert _titles("df.to_parquet(path='out')")


# ── limits and what a URL may carry ─────────────────────────────────────────


@pytest.mark.parametrize(
    "kw", [{"timeout_seconds": 0.0}, {"timeout_seconds": -5.0}, {"context_tokens": 0}]
)
def test_a_timeout_and_a_window_must_be_positive(kw):
    with pytest.raises(AIConfigError):
        AIConfig(provider="ollama", base_url="http://localhost:11434/v1", **kw).validate()


def test_a_base_url_with_a_password_is_refused_without_echoing_it():
    with pytest.raises(AIConfigError) as e:
        AIConfig(provider="openai_compatible", base_url="https://etl:hunter2@host/v1").validate()
    assert "hunter2" not in str(e.value)


@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254/latest", "http://metadata.google.internal/v1", "http://[fe80::1]/v1"],
)
def test_metadata_addresses_are_not_model_endpoints(url):
    with pytest.raises(AIConfigError):
        AIConfig(provider="openai_compatible", base_url=url).validate()


def test_a_local_or_private_address_is_still_allowed():
    for url in ("http://localhost:11434/v1", "http://10.0.0.5:8000/v1"):
        AIConfig(provider="openai_compatible", base_url=url).validate()


def test_the_keychain_entry_names_host_and_port_only():
    assert (
        keychain_user("openai_compatible", "https://host:8443/v1") == "openai_compatible@host:8443"
    )
    assert "@" not in keychain_user("openai_compatible", "https://host/v1").split("@", 1)[1]


# ── a draft file does not get to pick a path with its id ────────────────────


def _draft_dict(draft_id):
    return {
        "id": draft_id,
        "request": "r",
        "provider": "p",
        "model": "m",
        "created_at": "t",
        "ok": True,
        "files": {},
        "base": {},
        "problems": [],
    }


def test_a_draft_with_a_path_for_an_id_is_not_read(tmp_path):
    with pytest.raises(ValueError):
        Draft.from_dict(_draft_dict("../../x"))
    folder = tmp_path / ".ducta" / "ai" / "drafts"
    folder.mkdir(parents=True)
    (folder / "20261019-000000-abcdef.json").write_text(json.dumps(_draft_dict("../../x")))
    assert list_drafts(tmp_path) == []
    with pytest.raises(Exception):
        load_draft(tmp_path, "20261019-000000-abcdef")


# ── writes are all or nothing ───────────────────────────────────────────────


def test_atomic_write_replaces_and_leaves_nothing_behind(tmp_path):
    target = tmp_path / "a" / "x.json"
    fsutil.atomic_write_text(target, "one")
    fsutil.atomic_write_text(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in target.parent.iterdir()] == ["x.json"]


def test_a_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "ai.toml"
    fsutil.atomic_write_text(target, "old")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        fsutil.atomic_write_text(target, "new")
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["ai.toml"]


def test_save_config_is_atomic(tmp_path):
    path = tmp_path / "ai.toml"
    save_config(AIConfig(provider="ollama", base_url="http://localhost:11434/v1", model="m"), path)
    assert "ollama" in path.read_text()
    assert [p.name for p in tmp_path.iterdir()] == ["ai.toml"]
