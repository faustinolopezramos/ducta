"""The `/api/quality` routes end to end, on a real project and its sample data.

An ad-hoc run (`POST /quality/run`) stores a report; the read routes find it,
the delete route removes it, and each wrong input gets its own status.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

CHECKS = {"null_rate": {"columns": ["amount"], "threshold": 0.0}, "row_count": {"min": 1}}


@pytest.fixture
def project(tmp_path, monkeypatch):
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


@pytest.fixture
def api(project) -> TestClient:
    from ducta.api.main import create_app

    client = TestClient(create_app())
    client.params = {"source": str(project)}  # type: ignore[assignment]
    return client


def _run(api, **body):
    payload = {"input_path": "data/input.csv", "format": "csv", "checks": CHECKS, **body}
    return api.post("/api/quality/run", json=payload)


class TestRun:
    def test_inline_checks_score_the_sample_data(self, api):
        response = _run(api)
        assert response.status_code == 200
        report = response.json()
        assert report["dataset_name"] == "input"
        results = {r["check_name"]: r["passed"] for r in report["results"]}
        # The sample ships with missing amounts on purpose.
        assert results == {"null_rate": False, "row_count": True}
        assert report["score"] == 0.5

    def test_checks_from_a_config_file(self, api, project):
        (project / "checks.yaml").write_text("checks:\n  row_count: {min: 1}\n", encoding="utf-8")
        report = _run(api, checks=None, config_path="checks.yaml").json()
        assert [r["check_name"] for r in report["results"]] == ["row_count"]
        assert report["passed"] is True

    def test_neither_checks_nor_config_is_422(self, api):
        assert _run(api, checks=None).status_code == 422

    def test_missing_input_or_config_is_404(self, api):
        assert _run(api, input_path="data/none.csv").status_code == 404
        assert _run(api, checks=None, config_path="none.yaml").status_code == 404

    def test_a_path_outside_the_workspace_is_400(self, api):
        assert _run(api, input_path="../../etc/passwd").status_code == 400


class TestStoredReports:
    @pytest.fixture
    def run_id(self, api):
        return _run(api).json()["run_id"]

    def test_datasets_and_summary_list_the_run(self, api, run_id):
        assert api.get("/api/quality/datasets").json() == [
            {"pipeline_name": "_adhoc", "dataset": "input"}
        ]
        (summary,) = api.get("/api/quality/summary").json()
        assert (summary["dataset"], summary["latest_run_id"], summary["trend"]) == (
            "input",
            run_id,
            [0.5],
        )

    def test_report_latest_by_id_and_all(self, api, run_id):
        params = {"pipeline_name": "_adhoc"}
        latest = api.get("/api/quality/reports/input", params=params).json()
        assert latest["run_id"] == run_id
        by_id = api.get("/api/quality/reports/input", params={**params, "run_id": run_id})
        assert by_id.json()["run_id"] == run_id
        listed = api.get("/api/quality/reports/input", params={**params, "all": True}).json()
        assert run_id in str(listed)

    def test_a_dataset_without_reports_says_so_and_an_unknown_run_is_404(self, api, run_id):
        params = {"pipeline_name": "_adhoc"}
        empty = api.get("/api/quality/reports/ghost", params=params)
        assert (empty.status_code, empty.json()["status"]) == (200, "no_reports")
        missing = api.get("/api/quality/reports/input", params={**params, "run_id": "nope"})
        assert missing.status_code == 404

    def test_trend(self, api, run_id):
        _run(api)
        trend = api.get(
            "/api/quality/trend/input", params={"pipeline_name": "_adhoc", "last_n": 5}
        ).json()
        assert trend == {"dataset": "input", "scores": [0.5, 0.5]}

    def test_delete_then_404(self, api, run_id):
        params = {"pipeline_name": "_adhoc"}
        assert api.delete(f"/api/quality/reports/input/{run_id}", params=params).status_code == 204
        again = api.delete(f"/api/quality/reports/input/{run_id}", params=params)
        assert again.status_code == 404

    def test_score_of_an_unknown_run_is_404(self, api):
        assert api.get("/api/quality/score/nope").status_code == 404


class TestValidateConfig:
    def test_a_known_node_validates(self, api):
        body = api.post("/api/quality/validate-config", json={"node_name": "transform"}).json()
        assert body["valid"] is True, body

    def test_an_unknown_node_is_404(self, api):
        response = api.post("/api/quality/validate-config", json={"node_name": "ghost"})
        assert response.status_code == 404


def test_a_viewer_cannot_run_checks(api):
    from ducta.api.dependencies import get_current_user
    from ducta.api.models.auth import User

    api.app.dependency_overrides[get_current_user] = lambda: User(
        id="v", username="v", email="v@example.com", roles=["viewer"]
    )
    assert _run(api).status_code == 403
    assert api.get("/api/quality/checks").status_code == 200
