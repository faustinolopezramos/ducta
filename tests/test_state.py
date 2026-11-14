"""`ducta.state` decides where Ducta keeps its own state (the `.ducta` folders).

The values are pinned: projects already have files in these folders, so moving one
is a decision, not a refactor. The second test keeps them in one place — the
certificates' default was written three times, and the CLI and the web app once
looked for certificates in different folders.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ducta import state

SRC = Path(__file__).resolve().parents[1] / "src" / "ducta"


def test_the_folders_are_where_they_have_always_been(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("DUCTA_HOME", raising=False)

    assert state.RUNS_DIR == "${output_path}/${environment}/.ducta/runs"
    assert state.CHAIN_STATE_DIR == "${output_path}/${environment}/.ducta/chain_state"
    assert state.LOCKS_DIR == "${output_path}/${environment}/.ducta/locks"
    assert state.STREAMS_DIR == "${output_path}/${environment}/.ducta/streams"
    assert state.SCHEMA_DIR == ".ducta/schema"
    assert state.COMMENTS_DIR == ".ducta/comments"
    assert state.CONFIG_LOCK == ".ducta/config.lock"
    assert state.AUDIT_LOG == ".ducta/audit.log"
    assert state.ai_dir("p", "drafts") == Path("p/.ducta/ai/drafts")
    assert state.scratch_dir("data", "dev") == Path("data/dev/.ducta/scratch")
    assert state.under("x", "runs") == Path("x/.ducta/runs")
    assert state.user_dir("executions.db") == tmp_path / ".ducta" / "executions.db"


def test_ducta_home_moves_every_per_user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCTA_HOME", str(tmp_path / "home"))

    from ducta.ai.config import config_path
    from ducta_server.config import Settings

    assert state.user_dir("ai", "evals") == tmp_path / "home" / "ai" / "evals"
    assert config_path() == tmp_path / "home" / "ai.toml"
    assert Settings().runs_dir == str(tmp_path / "home" / "runs")


def test_the_engine_and_the_settings_use_them():
    from ducta.core.settings import CoreSettings
    from ducta.setting.schemas import ChainReuseConfig, GlobalConfigSchema
    from ducta.stream.journal import JOURNAL_DIR_TEMPLATE

    assert CoreSettings().run_certificate_dir == state.RUNS_DIR
    assert CoreSettings().chain_state_dir == state.CHAIN_STATE_DIR
    assert CoreSettings().run_lock_dir == state.LOCKS_DIR
    assert GlobalConfigSchema.model_fields["run_certificate_dir"].default == state.RUNS_DIR
    assert ChainReuseConfig.model_fields["state_dir"].default == state.CHAIN_STATE_DIR
    assert JOURNAL_DIR_TEMPLATE == state.STREAMS_DIR


def _code_strings(tree: ast.AST):
    """String constants that are code, not documentation (docstrings, help texts)."""
    skip = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            skip.add(id(body[0].value))
        if isinstance(node, ast.keyword) and node.arg in ("help", "description"):
            skip.update(id(n) for n in ast.walk(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node


def test_no_module_spells_a_ducta_path_by_hand():
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        # Skills ship as files, not code that writes state.
        if rel.name == "state.py" or rel.parts[0] == "skills":
            continue
        for node in _code_strings(ast.parse(path.read_text(encoding="utf-8"))):
            value = node.value
            if "yaml-language-server" in value:
                continue  # text a template writes into a project's YAML
            if value == ".ducta" or value.startswith(".ducta/") or "/.ducta/" in value:
                offenders.append(f"{rel}:{node.lineno}: {value[:60]!r}")
    assert offenders == [], "take it from ducta.state:\n" + "\n".join(offenders)
