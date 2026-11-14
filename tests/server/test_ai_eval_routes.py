"""``/ai/evals``: the server's model measured from the UI, and the kept reports."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai"))
from test_ai_routes import _client, home  # noqa: E402,F401
from test_evals_2026_10_24 import GOOD_EXPLANATION, Canned, _report  # noqa: E402


@pytest.fixture
def local(home):  # noqa: F811
    (home / "ai.toml").write_text('provider = "ollama"\nmodel = "fake"\n')
    return home


def _use(monkeypatch, *answers):
    provider = Canned(*answers)
    monkeypatch.setattr("ducta.ai.providers.make_provider", lambda config: provider)
    return provider


def _wait(client, job_id):
    for _ in range(500):
        r = client.get(f"/api/ai/evals/jobs/{job_id}")
        assert r.status_code == 200, r.text
        if r.json()["status"] != "running":
            return r.json()
        time.sleep(0.02)
    raise AssertionError("eval did not finish")


def test_only_an_admin_measures_the_model_or_reads_reports(local):
    dev = _client("developer")
    for method, url in (
        ("post", "/api/ai/evals"),
        ("get", "/api/ai/evals"),
        ("get", "/api/ai/evals/cases"),
        ("get", "/api/ai/evals/jobs/0123456789ab"),
        ("get", "/api/ai/evals/compare?b=x"),
        ("get", "/api/ai/evals/20261024T100000Z-m"),
    ):
        kwargs = {"json": {}} if method == "post" else {}
        assert getattr(dev, method)(url, **kwargs).status_code == 403, url


def test_a_remote_model_needs_confirm_remote(home):  # noqa: F811
    (home / "ai.toml").write_text(
        'provider = "openai"\nmodel = "gpt"\nbase_url = "https://api.openai.com/v1"\n'
    )
    r = _client("admin").post("/api/ai/evals", json={"cases": ["explain-keyerror"]})
    assert r.status_code == 409
    assert "confirm_remote" in r.text and "template" in r.text


def test_an_eval_job_reports_each_case_and_keeps_the_report(local, monkeypatch):
    _use(monkeypatch, GOOD_EXPLANATION)
    admin = _client("admin")
    r = admin.post("/api/ai/evals", json={"cases": ["explain-keyerror"]})
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "eval" and r.json()["evaluation"]["cases"] == ["explain-keyerror"]
    job = _wait(admin, r.json()["id"])
    assert job["status"] == "done" and job["ok"] is True
    evaluation = job["evaluation"]
    assert evaluation["results"][0]["case"] == "explain-keyerror"
    assert evaluation["summary"]["passed"] == 1
    listed = admin.get("/api/ai/evals").json()
    assert [r["id"] for r in listed] == [evaluation["report_id"]]
    report = admin.get(f"/api/ai/evals/{evaluation['report_id']}").json()
    assert report["results"][0]["passed"] is True


def test_an_unknown_case_is_a_400(local):
    r = _client("admin").post("/api/ai/evals", json={"cases": ["nope"]})
    assert r.status_code == 400 and "Unknown eval case" in r.text


def test_stopping_an_eval_keeps_no_report(local, monkeypatch):
    from ducta.ai import evals

    real = evals.run_eval

    def slow(*args, should_stop=None, **kwargs):
        for _ in range(500):
            if should_stop and should_stop():
                break
            time.sleep(0.01)
        return real(*args, should_stop=should_stop, **kwargs)

    monkeypatch.setattr(evals, "run_eval", slow)
    _use(monkeypatch, GOOD_EXPLANATION)
    admin = _client("admin")
    job_id = admin.post("/api/ai/evals", json={"cases": ["explain-keyerror"]}).json()["id"]
    r = admin.delete(f"/api/ai/evals/jobs/{job_id}")
    assert r.status_code == 202 and r.json()["status"] == "cancelled"
    time.sleep(0.3)
    assert _wait(admin, job_id)["status"] == "cancelled"
    assert admin.get("/api/ai/evals").json() == []


def test_compare_and_report_ids_are_never_paths(local):
    from ducta.ai import evals

    old = _report("m", "2026-10-24T10:00:00+00:00", [False])
    new = _report("m", "2026-10-24T11:00:00+00:00", [True])
    evals.save_report(old)
    evals.save_report(new)
    admin = _client("admin")
    out = admin.get("/api/ai/evals/compare", params={"b": new.id}).json()
    assert out["a"]["id"] == old.id and out["cases"][0]["change"] == "gained"
    both = admin.get("/api/ai/evals/compare", params={"a": new.id, "b": old.id}).json()
    assert both["cases"][0]["change"] == "lost"
    assert admin.get("/api/ai/evals/compare", params={"b": old.id}).status_code == 404
    assert admin.get("/api/ai/evals/compare", params={"b": "/etc/passwd"}).status_code == 404
    assert admin.get("/api/ai/evals/..%2F..%2Fai.toml").status_code == 404


def test_cases_say_what_they_are_about_and_server_reports_say_so(local, monkeypatch):
    admin = _client("admin")
    cases = admin.get("/api/ai/evals/cases").json()
    assert all(c["about"] for c in cases) and len(cases) == 10
    _use(monkeypatch, GOOD_EXPLANATION)
    job_id = admin.post("/api/ai/evals", json={"cases": ["explain-keyerror"]}).json()["id"]
    _wait(admin, job_id)
    assert admin.get("/api/ai/evals").json()[0]["source"] == "server"
