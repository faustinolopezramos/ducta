"""Adding nodes to a pipeline and reviewing a whole pipeline, over HTTP."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai"))
from test_ai_routes import _client, _configure, _use, _wait, home  # noqa: E402,F401
from test_extend_and_pipeline_review import REVIEW, SALES, _good  # noqa: E402


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    shutil.copytree(SALES, root)
    return root


def test_an_extend_job_drafts_new_nodes_that_are_then_applied(home, proj, monkeypatch):
    _configure(home)
    _use(monkeypatch, _good(proj))
    client, src = _client(), {"source": str(proj)}
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "extend", "pipeline": "silver.sales", "request": "one row per customer"},
    )
    assert r.status_code == 202, r.text
    job = _wait(client, proj, r.json()["id"])
    assert job["status"] == "done" and job["ok"], job
    draft = client.get(f"/api/projects/proj/ai/drafts/{job['draft_id']}", params=src).json()
    assert draft["kind"] == "extend" and draft["pipeline"] == "silver.sales"
    r = client.post(f"/api/projects/proj/ai/drafts/{job['draft_id']}/apply", params=src, json={})
    assert r.status_code == 200, r.text
    assert "latest_customers" in (proj / "pipelines" / "silver.sales.yaml").read_text()


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "extend", "pipeline": "silver.sales"},
        {"kind": "extend", "request": "x"},
        {"kind": "review_pipeline"},
    ],
)
def test_extend_and_review_pipeline_say_what_they_need(home, proj, body):
    _configure(home)
    r = _client().post("/api/projects/proj/ai/jobs", params={"source": str(proj)}, json=body)
    assert r.status_code == 400


def test_a_pipeline_review_job_and_the_checks_without_a_model(home, proj, monkeypatch):
    _configure(home)
    _use(monkeypatch, REVIEW)
    client, src = _client(), {"source": str(proj)}
    assert client.get("/api/projects/proj/ai/reviews/silver.sales", params=src).status_code == 404

    checks = client.post("/api/projects/proj/ai/reviews/silver.sales/checks", params=src)
    assert checks.status_code == 200, checks.text
    assert checks.json()["model"] is None and checks.json()["kind"] == "pipeline"

    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "review_pipeline", "pipeline": "silver.sales"},
    )
    job = _wait(client, proj, r.json()["id"])
    assert job["status"] == "done", job
    review = job["review"]
    assert review["kind"] == "pipeline" and review["dropped"] == 2 and len(review["ideas"]) == 3
    assert any(f["node"] == "clean_orders" and f["source"] == "ai" for f in review["findings"])
    kept = client.get("/api/projects/proj/ai/reviews/silver.sales", params=src).json()
    assert kept == review
    # A node's own review is a different thing, kept apart.
    assert (
        client.get(
            "/api/projects/proj/ai/reviews/silver.sales/clean_orders", params=src
        ).status_code
        == 404
    )


def test_a_viewer_neither_extends_nor_reviews(home, proj):
    _configure(home)
    client, src = _client("viewer"), {"source": str(proj)}
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "review_pipeline", "pipeline": "silver.sales"},
    )
    assert r.status_code == 403
    assert (
        client.post("/api/projects/proj/ai/reviews/silver.sales/checks", params=src).status_code
        == 403
    )
