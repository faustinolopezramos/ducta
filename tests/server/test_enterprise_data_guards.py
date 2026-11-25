"""Enterprise-data guards from the second security review of 2026-11-20 (live probes).

- A developer's pipeline rewrote the SQLite ``users`` table and became admin: a server
  others reach now refuses SQLite with accounts (``check_shared_database``).
- The file API and git served a protected environment's data files whole to a viewer
  (prod CSV with emails and IBANs) while the preview answered 403, and let a developer
  overwrite a prod dataset and its quality history.
- The PII guard split ``teléfono`` into ``tel`` and ``fono`` (ASCII words), so a rule
  on it went through and its count of failing rows told the values.
- ``LIKE`` became a backtracking regex: 8 ``%`` on a 60-character value took 21 s.
- Promoting to Production (or forcing past the project's own policy) took only the
  developer's ``model.promote``.
- The language server got the server's whole environment (``JWT_SECRET_KEY``…).
"""

from __future__ import annotations

import pickle
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta_server.config import Settings
from ducta_server.dependencies import get_current_user
from ducta_server.main import check_shared_database, create_app
from ducta_server.models.auth import User
from ducta_server.services.data_access import names_in, refuse_hidden
from ducta_server.services.sql_rules import like_matcher, rule_mask


def _as(role: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=role, username=role, email=f"{role}@example.com", roles=[role]
    )
    return TestClient(app)


# ── PII guard: names in any script ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule",
    [
        "`teléfono` NOT LIKE '5512%'",
        "TELÉFONO > 1",
        "`fecha nacimiento` IS NULL",
        '"fecha nacimiento" IS NULL',
    ],
)
def test_a_rule_naming_a_pii_column_is_refused_whatever_its_script(rule):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        refuse_hidden(names_in({"rules": [rule]}), {"teléfono", "fecha nacimiento"})
    assert e.value.status_code == 403


def test_a_check_parameter_holding_the_whole_name_is_refused():
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        refuse_hidden(names_in({"columns": ["fecha nacimiento"]}), {"fecha nacimiento"})


# ── LIKE without backtracking ──────────────────────────────────────────────────


def _regex_like(pattern: str, text: str, ignore_case: bool) -> bool:
    regex = "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern)
    flags = re.DOTALL | (re.IGNORECASE if ignore_case else 0)
    return re.fullmatch(regex, text, flags) is not None


def test_like_agrees_with_the_regex_it_replaced():
    import random

    rnd = random.Random(7)
    for _ in range(20000):
        pattern = "".join(rnd.choice("abA%_") for _ in range(rnd.randint(0, 6)))
        text = "".join(rnd.choice("abAB\n") for _ in range(rnd.randint(0, 7)))
        for ignore_case in (False, True):
            assert like_matcher(pattern, ignore_case)(text) == _regex_like(
                pattern, text, ignore_case
            ), (pattern, text, ignore_case)


def test_like_is_linear_on_the_pattern_that_took_21_seconds():
    import pandas as pd

    df = pd.DataFrame({"name": ["a" * 4000] * 200})
    started = time.monotonic()
    rule_mask(df, "name LIKE '" + "%a" * 1500 + "%'")
    rule_mask(df, "name LIKE '" + "%a" * 1500 + "%b'")
    assert time.monotonic() - started < 10


# ── Protected data files: file API and git ─────────────────────────────────────


@pytest.fixture
def project(tmp_path, monkeypatch):
    from ducta.console.templates import TemplateGenerator, TemplateType
    from ducta.project_store.governance import FLOOR_ENV

    monkeypatch.delenv(FLOOR_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    gold = root / "data" / "prod" / "gold"
    gold.mkdir(parents=True)
    (gold / "customers.csv").write_text("id,email\n1,ana@corp.com\n")
    (root / "data" / "dev").mkdir(parents=True, exist_ok=True)
    (root / "data" / "dev" / "scratch.csv").write_text("id\n1\n")
    catalog = root / "catalog.yaml"
    catalog.write_text(
        catalog.read_text()
        + "\ngold.crm.customers:\n  format: csv\n  path: data/prod/gold/customers.csv\n"
    )
    return root


def _read(role, root, path):
    return _as(role).get("/api/workspace/files/content", params={"source": str(root), "path": path})


def _write(role, root, path, content="x\n"):
    return _as(role).put(
        "/api/workspace/files/content",
        params={"source": str(root)},
        json={"path": path, "content": content},
    )


@pytest.mark.parametrize("role, status", [("viewer", 403), ("developer", 403),
                                          ("operator", 200), ("admin", 200)])  # fmt: skip
def test_reading_a_protected_environments_data_file_takes_its_permission(project, role, status):
    resp = _read(role, project, "data/prod/gold/customers.csv")
    assert resp.status_code == status, resp.text
    if status == 403:
        assert "data.read.protected" in resp.json()["message"]
        assert "ana@corp.com" not in resp.text


def test_code_and_other_environments_stay_readable(project):
    assert _read("viewer", project, "ducta.yaml").status_code == 200
    assert _read("viewer", project, "data/dev/scratch.csv").status_code == 200


@pytest.mark.parametrize("path", ["data/prod/gold/customers.csv", "data/prod/quality/history.json"])
def test_a_developer_cannot_change_a_protected_environments_data(project, path):
    before = (project / path).read_text() if (project / path).exists() else None
    resp = _write("developer", project, path, "tampered\n")
    assert resp.status_code == 403, resp.text
    assert "data.write.protected" in resp.json()["message"]
    after = (project / path).read_text() if (project / path).exists() else None
    assert after == before
    deleted = _as("developer").delete(
        "/api/workspace/files", params={"source": str(project), "path": path}
    )
    assert deleted.status_code in (403, 404)


def test_a_developer_still_edits_code(project):
    assert _write("developer", project, "pipelines/notes.md", "hi\n").status_code == 204


def test_git_does_not_serve_what_the_file_api_refuses(project):
    git = pytest.importorskip("git")
    repo = git.Repo.init(project)
    repo.config_writer().set_value("user", "name", "t").release()
    repo.config_writer().set_value("user", "email", "t@example.com").release()
    repo.git.add(A=True)
    repo.git.add("-f", "data/prod/gold/customers.csv")  # data/ is in the template's .gitignore
    repo.index.commit("all")
    sha = repo.head.commit.hexsha
    viewer = _as("viewer")
    whole = viewer.get(f"/api/git/diff/{sha}", params={"source": str(project)})
    assert whole.status_code == 200, whole.text
    assert "ana@corp.com" not in whole.text
    assert "ducta.yaml" in whole.json()["diff"]  # the rest of the commit is still there
    for url, params in (
        ("/api/git/working-diff", {"path": "data/prod/gold/customers.csv"}),
        ("/api/git/file-at", {"path": "data/prod/gold/customers.csv", "rev": sha}),
        ("/api/git/blame/data/prod/gold/customers.csv", {}),
    ):
        resp = viewer.get(url, params={"source": str(project), **params})
        assert resp.status_code == 403, (url, resp.text)
    admin = _as("admin").get(f"/api/git/diff/{sha}", params={"source": str(project)})
    assert "ana@corp.com" in admin.text


# ── Promotion to Production ────────────────────────────────────────────────────


@pytest.fixture
def ml_project(tmp_path, monkeypatch) -> Path:
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "ml"
    TemplateGenerator(root).generate_project(TemplateType.ML_SCORING, "ml")
    return root


def _registry(root):
    from ducta_server.routes.mlops import _registry_at, _resolve_mlops_storage

    return _registry_at(_resolve_mlops_storage(root, None, "dev", "score"))


def _register(registry, tmp_path, auc):
    artifact = tmp_path / f"m{auc}.pkl"
    artifact.write_bytes(pickle.dumps({"auc": auc}))
    return registry.register_model(
        name="churn-model",
        artifact_path=str(artifact),
        artifact_type="pickle",
        framework="sklearn",
        metrics={"val_auc": auc},
    )


def _promote(role, root, body):
    return _as(role).post(
        "/api/mlops/models/churn-model/promote",
        params={"source": str(root), "env": "dev", "pipeline": "score"},
        json=body,
    )


def test_a_developer_cannot_promote_to_production_or_force(ml_project, tmp_path):
    from ducta.mlrun.model_registry import ModelStage

    registry = _registry(ml_project)
    _register(registry, tmp_path, 0.9)
    _register(registry, tmp_path, 0.8)
    for body in (
        {"version": 1, "stage": "production"},
        {"version": 1, "stage": "staging", "force": True, "reason": "because"},
    ):
        resp = _promote("developer", ml_project, body)
        assert resp.status_code == 403, resp.text
        assert "model.promote.production" in resp.json()["message"]
    assert _promote("developer", ml_project, {"version": 2, "stage": "staging"}).status_code == 200
    assert _promote("admin", ml_project, {"version": 1, "stage": "production"}).status_code == 200
    # Taking the Production version out of Production is the admin's too.
    resp = _promote("developer", ml_project, {"version": 1, "stage": "archived"})
    assert resp.status_code == 403, resp.text
    stages = {
        v["version"]: str(v["stage"]) for v in registry.list_model_versions_lite("churn-model")
    }
    assert stages[1] == ModelStage.PRODUCTION.value


# ── SQLite with accounts ───────────────────────────────────────────────────────


class TestSharedDatabase:
    SQLITE = "sqlite+aiosqlite:////srv/ducta.db"

    @staticmethod
    def _settings(**kw):
        base = dict(
            environment="development",
            auth_enabled=True,
            host="0.0.0.0",
            jwt_secret_key="a-strong-secret",
        )
        base.update(kw)
        return Settings(**base)

    def test_an_exposed_server_refuses_sqlite_with_accounts(self):
        with pytest.raises(RuntimeError, match="SQLite"):
            check_shared_database(self._settings(database_url=self.SQLITE))

    def test_the_opt_out_only_warns(self):
        settings = self._settings(database_url=self.SQLITE, allow_sqlite_with_accounts=True)
        assert check_shared_database(settings) is True

    def test_loopback_only_warns(self):
        settings = self._settings(database_url=self.SQLITE, host="127.0.0.1")
        assert check_shared_database(settings) is True

    def test_a_database_server_or_no_accounts_is_silent(self):
        pg = "postgresql+asyncpg://ducta:pw@db:5432/ducta"
        assert check_shared_database(self._settings(database_url=pg)) is False
        no_accounts = self._settings(database_url=self.SQLITE, auth_enabled=False)
        assert check_shared_database(no_accounts) is False


# ── Language server environment ────────────────────────────────────────────────


def test_the_language_server_does_not_get_the_servers_secrets(tmp_path, monkeypatch):
    import asyncio
    import sys

    from ducta_server.services.language_server import LocalLanguageServerPool

    monkeypatch.setenv("JWT_SECRET_KEY", "server-key-under-test")
    monkeypatch.setenv("DUCTA_CERTIFICATE_KEY", "cert-key-under-test")
    out = tmp_path / "env.txt"
    script = (
        "import os,sys;"
        f"open({str(out)!r},'w').write(repr((os.environ.get('JWT_SECRET_KEY'),"
        "os.environ.get('DUCTA_CERTIFICATE_KEY'))));sys.stdin.read()"
    )
    pool = LocalLanguageServerPool("", 1)
    monkeypatch.setattr(pool, "available", lambda: [sys.executable, "-c", script])

    async def receive():
        for _ in range(100):
            if out.exists():
                break
            await asyncio.sleep(0.05)
        return None

    async def send(_text):
        return None

    asyncio.run(pool.bridge(tmp_path, receive, send))
    assert out.read_text() == "(None, None)"
