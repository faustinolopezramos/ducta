"""The AI pipeline builder over HTTP: settings, keys, jobs and drafts."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.ai import secrets
from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai"))
from test_builder import FIXED_MODULE, GOOD, FakeProvider, _project  # noqa: E402


def _client(role: str = "developer") -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=role, username=role, email=f"{role}@example.com", roles=[role]
    )
    return TestClient(app)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DUCTA_HOME", str(home))
    for var in ("DUCTA_AI_PROVIDER", "DUCTA_AI_MODEL", "DUCTA_AI_BASE_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    store = {}

    class FakeKeyring:
        @staticmethod
        def get_password(service, user):
            return store.get((service, user))

        @staticmethod
        def set_password(service, user, key):
            store[(service, user)] = key

        @staticmethod
        def delete_password(service, user):
            store.pop((service, user))

    monkeypatch.setattr(secrets, "_keyring", lambda: FakeKeyring)
    monkeypatch.setattr(secrets, "keychain_available", lambda: True)
    return home


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    root.mkdir()
    return _project(root)


def _use(monkeypatch, *answers):
    provider = FakeProvider(*answers)
    monkeypatch.setattr("ducta.ai.providers.make_provider", lambda config: provider)
    return provider


def _wait(client, project_root, job_id):
    for _ in range(200):
        r = client.get(f"/api/projects/proj/ai/jobs/{job_id}", params={"source": str(project_root)})
        assert r.status_code == 200, r.text
        if r.json()["status"] != "running":
            return r.json()
        time.sleep(0.02)
    raise AssertionError("job did not finish")


# ── settings and keys ────────────────────────────────────────────────────────


def test_unconfigured_settings_say_so_and_list_the_providers(home):
    body = _client().get("/api/ai/settings").json()
    assert body["configured"] is False
    assert "ducta ai setup" in body["error"]
    names = {p["name"]: p for p in body["providers"]}
    assert names["ollama"]["local"] and not names["ollama"]["needs_key"]
    assert names["anthropic"]["needs_key"] and names["anthropic"]["default_model"]


def test_an_admin_chooses_the_model_and_keeps_a_key(home):
    admin = _client("admin")
    r = admin.put("/api/ai/settings", json={"provider": "anthropic"})
    assert r.status_code == 200, r.text
    assert r.json()["key"] == {"present": False, "source": "none", "masked": "—"}

    r = admin.put("/api/ai/key", json={"api_key": "sk-ant-secret-0123456789"})
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    assert key["present"] and key["source"] == "keychain"
    assert "secret" not in r.text  # never echoed
    assert "sk-ant" not in (home / "ai.toml").read_text()

    r = admin.delete("/api/ai/key")
    assert r.json()["key"]["present"] is False


def test_a_developer_cannot_change_the_servers_model(home):
    r = _client("developer").put("/api/ai/settings", json={"provider": "ollama", "model": "m"})
    assert r.status_code == 403
    assert _client("viewer").get("/api/ai/settings").status_code == 403


def test_a_bad_provider_is_a_400(home):
    r = _client("admin").put("/api/ai/settings", json={"provider": "nope"})
    assert r.status_code == 400
    assert "Unknown AI provider" in r.text


# ── jobs and drafts ──────────────────────────────────────────────────────────


def _configure(home):
    (home / "ai.toml").write_text('provider = "ollama"\nmodel = "fake"\n')


def test_a_job_drafts_a_pipeline_that_is_then_applied(home, project, monkeypatch):
    _configure(home)
    _use(monkeypatch, GOOD)
    client = _client()
    src = {"source": str(project)}
    r = client.post("/api/projects/proj/ai/jobs", params=src, json={"request": "totals per order"})
    assert r.status_code == 202, r.text
    job = _wait(client, project, r.json()["id"])
    assert job["status"] == "done" and job["ok"], job
    assert [a["errors"] for a in job["attempts"]] == [0]

    drafts = client.get("/api/projects/proj/ai/drafts", params=src).json()
    assert [d["id"] for d in drafts] == [job["draft_id"]]

    draft = client.get(f"/api/projects/proj/ai/drafts/{job['draft_id']}", params=src).json()
    changes = {f["path"]: f["change"] for f in draft["file_contents"]}
    assert changes == {
        "pipelines/silver.totals.yaml": "added",
        "src/totals.py": "added",
        "catalog.yaml": "modified",
    }
    assert "+++ b/src/totals.py" in draft["diff"]
    assert not (project / "src" / "totals.py").exists()

    r = client.post(f"/api/projects/proj/ai/drafts/{job['draft_id']}/apply", params=src, json={})
    assert r.status_code == 200, r.text
    assert (project / "src" / "totals.py").exists()
    r = client.post(f"/api/projects/proj/ai/drafts/{job['draft_id']}/apply", params=src, json={})
    assert r.status_code == 409


def test_a_fix_job_takes_the_pipeline_and_a_note(home, project, monkeypatch):
    _configure(home)
    (project / "src" / "m.py").write_text("def clean(df):\n    return df\n")
    provider = _use(monkeypatch, FIXED_MODULE)
    client = _client()
    src = {"source": str(project)}
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "fix", "pipeline": "etl", "note": "el parámetro se llama orders"},
    )
    job = _wait(client, project, r.json()["id"])
    assert job["ok"], job
    draft = client.get(f"/api/projects/proj/ai/drafts/{job['draft_id']}", params=src).json()
    assert draft["kind"] == "fix" and draft["pipeline"] == "etl"
    assert [f["change"] for f in draft["file_contents"]] == ["modified"]
    assert "el parámetro se llama orders" in provider.calls[0][0].content


def test_an_invalid_draft_is_not_applied_without_force(home, project, monkeypatch):
    _configure(home)
    bad = GOOD.replace("def totals(orders, **kwargs):", "def totals(df):")
    _use(monkeypatch, bad, bad, bad)
    client = _client()
    src = {"source": str(project)}
    job = _wait(
        client,
        project,
        client.post("/api/projects/proj/ai/jobs", params=src, json={"request": "x"}).json()["id"],
    )
    assert job["status"] == "done" and job["ok"] is False
    assert len(job["attempts"]) == 3
    url = f"/api/projects/proj/ai/drafts/{job['draft_id']}"
    assert client.post(url + "/apply", params=src, json={}).status_code == 400
    assert client.post(url + "/apply", params=src, json={"force": True}).status_code == 200


def test_a_viewer_cannot_draft(home, project):
    _configure(home)
    src = {"source": str(project)}
    r = _client("viewer").post("/api/projects/proj/ai/jobs", params=src, json={"request": "x"})
    assert r.status_code == 403


def test_a_job_failure_is_reported_not_raised(home, project, monkeypatch):
    _configure(home)
    _use(monkeypatch)  # no answers: the provider raises
    client = _client()
    src = {"source": str(project)}
    r = client.post("/api/projects/proj/ai/jobs", params=src, json={"request": "x"})
    job = _wait(client, project, r.json()["id"])
    assert job["status"] == "failed" and job["error"]


def test_no_provider_is_a_400_before_any_job(home, project):
    src = {"source": str(project)}
    r = _client().post("/api/projects/proj/ai/jobs", params=src, json={"request": "x"})
    assert r.status_code == 400
    assert "ducta ai setup" in r.text


def test_an_unknown_draft_is_a_404_and_a_bad_id_a_400(home, project):
    src = {"source": str(project)}
    client = _client()
    assert client.get("/api/projects/proj/ai/drafts/20990101-x", params=src).status_code == 404
    assert client.get("/api/projects/proj/ai/drafts/..%2Fetc", params=src).status_code in (400, 404)


def test_a_draft_is_discarded(home, project, monkeypatch):
    _configure(home)
    _use(monkeypatch, GOOD)
    client = _client()
    src = {"source": str(project)}
    job = _wait(
        client,
        project,
        client.post("/api/projects/proj/ai/jobs", params=src, json={"request": "x"}).json()["id"],
    )
    url = f"/api/projects/proj/ai/drafts/{job['draft_id']}"
    assert client.delete(url, params=src).status_code == 204
    assert client.get(url, params=src).status_code == 404


def test_a_failed_runs_errors_become_text_for_the_model():
    from types import SimpleNamespace

    from ducta.api.routes.ai import _format_run_errors

    summary = {
        "errors": [
            {
                "node_id": "etl.clean",
                "error_type": "KeyError",
                "message": "'amount'",
                "traceback": "Traceback…",
            }
        ]
    }
    text = _format_run_errors(SimpleNamespace(error="failed"), summary)
    assert text.startswith("etl.clean KeyError 'amount'\nTraceback")
    assert _format_run_errors(SimpleNamespace(error="boom"), None) == "boom"


def test_a_revise_job_asks_for_changes_to_a_draft(home, project, monkeypatch):
    _configure(home)
    provider = _use(monkeypatch, GOOD, GOOD.replace("Order totals", "Daily order totals"))
    client = _client()
    src = {"source": str(project)}
    first = _wait(
        client,
        project,
        client.post("/api/projects/proj/ai/jobs", params=src, json={"request": "totals"}).json()[
            "id"
        ],
    )
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "revise", "draft_id": first["draft_id"], "note": "per day"},
    )
    assert r.status_code == 202, r.text
    second = _wait(client, project, r.json()["id"])
    assert second["ok"], second
    draft = client.get(f"/api/projects/proj/ai/drafts/{second['draft_id']}", params=src).json()
    assert draft["revision_of"] == first["draft_id"]
    assert "per day" in provider.calls[1][-1].content
    bad = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "revise", "draft_id": first["draft_id"]},
    )
    assert bad.status_code == 400


# ── hardening (review 2026-10-11) ────────────────────────────────────────────


def test_saving_from_the_ui_keeps_settings_it_does_not_show(home):
    (home / "ai.toml").write_text(
        'provider = "ollama"\nmodel = "a"\ncontext_tokens = 32768\ntimeout_seconds = 900.0\n'
    )
    r = _client("admin").put(
        "/api/ai/settings", json={"provider": "ollama", "model": "b", "base_url": None}
    )
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "b" and r.json()["timeout_seconds"] == 900.0
    assert "context_tokens = 32768" in (home / "ai.toml").read_text()


@pytest.mark.parametrize("name", ["DATABASE_PASSWORD", "AWS_SECRET_ACCESS_KEY", "HOME"])
def test_the_key_variable_cannot_be_any_server_variable(home, name):
    r = _client("admin").put(
        "/api/ai/settings", json={"provider": "openai", "model": "m", "api_key_env": name}
    )
    assert r.status_code == 400 and "DUCTA_AI_" in r.text
    ok = _client("admin").put(
        "/api/ai/settings",
        json={"provider": "openai", "model": "m", "api_key_env": "DUCTA_AI_OPENAI"},
    )
    assert ok.status_code == 200, ok.text


def test_a_providers_own_key_is_not_sent_to_another_endpoint(home):
    r = _client("admin").put(
        "/api/ai/settings",
        json={"provider": "openai", "model": "m", "base_url": "https://evil.example/v1"},
    )
    assert r.status_code == 400 and "needs its own key" in r.text
    r = _client("admin").put(
        "/api/ai/settings",
        json={
            "provider": "openai",
            "model": "m",
            "base_url": "https://gateway.example/v1",
            "api_key_env": "DUCTA_AI_GATEWAY",
        },
    )
    assert r.status_code == 200, r.text


def test_a_job_can_be_stopped_and_saves_no_draft(home, project, monkeypatch):
    import threading

    _configure(home)
    release = threading.Event()
    provider = FakeProvider("no blocks here", GOOD)
    real = provider.complete

    def slow(system, messages):
        release.wait(5)
        return real(system, messages)

    provider.complete = slow
    monkeypatch.setattr("ducta.ai.providers.make_provider", lambda config: provider)
    client = _client()
    src = {"source": str(project)}
    job = client.post("/api/projects/proj/ai/jobs", params=src, json={"request": "x"}).json()
    r = client.delete(f"/api/projects/proj/ai/jobs/{job['id']}", params=src)
    assert r.status_code == 202 and r.json()["status"] == "cancelled"
    release.set()
    from ducta.api.routes import ai as ai_routes

    for _ in range(250):  # until the worker has seen the stop and ended
        if not ai_routes._jobs.running():
            break
        time.sleep(0.02)
    assert (
        client.get(f"/api/projects/proj/ai/jobs/{job['id']}", params=src).json()["status"]
        == "cancelled"
    )
    assert len(provider.calls) <= 1  # no attempt after the stop
    assert client.get("/api/projects/proj/ai/drafts", params=src).json() == []


def test_a_job_is_on_disk_and_only_its_owner_sees_it(home, project, monkeypatch):
    _configure(home)
    _use(monkeypatch, GOOD)
    src = {"source": str(project)}
    job = (
        _client("developer")
        .post("/api/projects/proj/ai/jobs", params=src, json={"request": "x"})
        .json()
    )
    _wait(_client("developer"), project, job["id"])
    assert (project / ".ducta" / "ai" / "jobs" / f"{job['id']}.json").is_file()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="someone-else", username="o", email="o@example.com", roles=["developer"]
    )
    other = TestClient(app)
    assert other.get(f"/api/projects/proj/ai/jobs/{job['id']}", params=src).status_code == 404
    assert (
        _client("admin").get(f"/api/projects/proj/ai/jobs/{job['id']}", params=src).status_code
        == 200
    )


def test_settings_are_tested_before_they_are_saved(home, monkeypatch):
    seen = []

    class Lister:
        def __init__(self, config):
            seen.append(config)

        def list_models(self):
            return ["qwen2.5-coder:14b"]

    monkeypatch.setattr("ducta.ai.providers.make_provider", Lister)
    body = {
        "provider": "ollama",
        "model": "qwen2.5-coder:14b",
        "base_url": "http://gpu-box:11434/v1",
    }
    r = _client("admin").post("/api/ai/models/test", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"models": ["qwen2.5-coder:14b"]}
    assert seen[0].base_url == "http://gpu-box:11434/v1"
    # Nothing was saved, and only an admin may point the server at an endpoint.
    assert _client("admin").get("/api/ai/settings").json()["configured"] is False
    assert _client("developer").post("/api/ai/models/test", json=body).status_code == 403


def test_a_quality_job_proposes_a_nodes_checks(home, project, monkeypatch):
    import pandas as pd

    from ducta.ai import proposals

    _configure(home)
    frame = pd.DataFrame({"order_id": [1, 2]})
    facts = proposals.QualityFacts(
        "etl",
        "pipelines/etl.yaml",
        "etl.clean",
        "clean",
        "dev",
        None,
        rows=2,
        measured_rows=2,
        columns=[{"name": "order_id"}],
        frame=frame,
    )
    monkeypatch.setattr(proposals, "quality_facts", lambda *a, **k: facts)
    _use(monkeypatch, "```yaml quality\nnull_rate: {columns: [order_id], threshold: 0.0}\n```\n")
    client, src = _client(), {"source": str(project)}
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "quality", "pipeline": "etl", "node": "etl.clean"},
    )
    assert r.status_code == 202, r.text
    job = _wait(client, project, r.json()["id"])
    assert job["status"] == "done" and job["ok"], job
    draft = client.get(f"/api/projects/proj/ai/drafts/{job['draft_id']}", params=src).json()
    assert (draft["kind"], draft["target"], draft["env"]) == ("quality", "etl.clean", "dev")
    assert [f["path"] for f in draft["file_contents"]] == ["pipelines/etl.yaml"]


def test_a_quality_job_needs_its_node(home, project):
    _configure(home)
    r = _client().post(
        "/api/projects/proj/ai/jobs",
        params={"source": str(project)},
        json={"kind": "quality", "pipeline": "etl"},
    )
    assert r.status_code == 400


def test_an_explain_job_explains_a_failed_run_and_keeps_it(home, project, monkeypatch):
    from types import SimpleNamespace

    _configure(home)
    provider = _use(monkeypatch, "**What happened** the region column is missing")

    class Executions:
        async def load_execution(self, execution_id, user_id=None):
            return SimpleNamespace(id=execution_id, error="KeyError: 'region'")

        def get_execution_errors(self, execution_id, user_id=None):
            return {
                "errors": [
                    {"node_id": "etl.clean", "error_type": "KeyError", "message": "'region'"}
                ]
            }

    monkeypatch.setattr("ducta.api.routes.ai.get_execution_manager", lambda request: Executions())
    monkeypatch.setattr(
        "ducta.api.routes.execution.build_diagnosis",
        lambda record, manager, root: {"kind": "data", "node": "etl.clean", "title": "Data"},
    )
    client, src = _client(), {"source": str(project)}
    assert client.get("/api/projects/proj/ai/explanations/run-7", params=src).status_code == 404
    r = client.post(
        "/api/projects/proj/ai/jobs", params=src, json={"kind": "explain", "execution_id": "run-7"}
    )
    assert r.status_code == 202, r.text
    job = _wait(client, project, r.json()["id"])
    assert job["status"] == "done", job
    assert job["explanation"].startswith("**What happened**")
    assert job["draft_id"] is None
    assert "KeyError" in provider.calls[0][0].content
    kept = client.get("/api/projects/proj/ai/explanations/run-7", params=src).json()
    assert kept["text"] == job["explanation"] and kept["model"] == "fake"


def test_docs_gaps_count_what_has_no_description(home, project):
    r = _client().get("/api/projects/proj/ai/docs-gaps", params={"source": str(project)})
    assert r.status_code == 200, r.text
    # The test project: two datasets, one pipeline and its node, none described.
    assert r.json() == {"datasets": 2, "pipelines": 1, "nodes": 1}


def test_a_nodes_checks_need_no_model_and_are_kept(home, project):
    (project / "src" / "m.py").write_text(
        "def clean(orders):\n    rows = orders.collect()\n    return orders\n"
    )
    client, src = _client(), {"source": str(project)}
    assert client.get("/api/projects/proj/ai/reviews/etl/etl.clean", params=src).status_code == 404
    r = client.post("/api/projects/proj/ai/reviews/etl/etl.clean/checks", params=src)
    assert r.status_code == 200, r.text
    assert r.json()["model"] is None
    assert [(f["line"], f["source"]) for f in r.json()["findings"]] == [(2, "ducta")]
    kept = client.get("/api/projects/proj/ai/reviews/etl/etl.clean", params=src).json()
    assert kept == r.json()


def test_a_review_job_adds_the_models_checked_findings(home, project, monkeypatch):
    _configure(home)
    _use(
        monkeypatch,
        "```yaml review\nfindings:\n  - {severity: low, area: code, title: Returns input, line: 2, code: return orders}\n"
        "  - {severity: low, area: code, title: Made up, line: 50}\n```\n",
    )
    client, src = _client(), {"source": str(project)}
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "review", "pipeline": "etl", "node": "etl.clean"},
    )
    assert r.status_code == 202, r.text
    job = _wait(client, project, r.json()["id"])
    assert job["status"] == "done", job
    assert [f["title"] for f in job["review"]["findings"]] == ["Returns input"]
    assert job["review"]["dropped"] == 1 and job["draft_id"] is None
    assert (
        client.get("/api/projects/proj/ai/reviews/etl/etl.clean", params=src).json()
        == job["review"]
    )


def test_a_review_needs_its_node(home, project):
    _configure(home)
    r = _client().post(
        "/api/projects/proj/ai/jobs",
        params={"source": str(project)},
        json={"kind": "review", "pipeline": "etl"},
    )
    assert r.status_code == 400
