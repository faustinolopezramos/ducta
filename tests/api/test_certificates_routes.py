"""Run Certificate lookup under the Ducta storage convention.

`run_certificate_dir` defaults to the template
``${output_path}/${environment}/.ducta/runs``. The executor resolved it, but
the API glued the raw template onto the project directory and searched
``projects/<id>/${output_path}/${environment}/.ducta/runs`` — a directory that
never exists — so every certificate GET/verify/diff/reproduce answered 404
while the file sat in ``data/<env>/.ducta/runs/<run_id>/``. These tests build a
real project config (resolved through the same loader the runner uses) rather
than patching the resolver out.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="certificate route tests require the api extra")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ducta.api.dependencies import get_current_user, get_source_path  # noqa: E402
from ducta.api.models.auth import User  # noqa: E402
from ducta.api.routes import certificates as certificates_route  # noqa: E402
from ducta.api.services.run_certificates import env_runs_dir  # noqa: E402

RUN_ID = "6d5b1c20e9ab41268dec6f9bbf2faef7"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def _write_certificate(runs_dir: Path, run_id: str, env: str | None) -> Path:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "certificate.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pipeline": "golden.transformation",
                "status": "success",
                "started_at": "2026-09-15T05:18:47+00:00",
                "environment_name": env,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A workspace whose `batch` project keeps its outputs under `./data`."""
    project = tmp_path / "projects" / "batch"
    _write(
        project / "ducta.yaml",
        """
        version: 2
        project: batch
        paths: {input: ./data, output: ./data}
        settings: {mode: local}
        """,
    )
    _write(project / "catalog.yaml", "{}\n")
    (project / "pipelines").mkdir()
    return tmp_path


@pytest.fixture()
def project(workspace: Path) -> Path:
    return workspace / "projects" / "batch"


@pytest.fixture()
def client(workspace: Path) -> TestClient:
    app = FastAPI()
    app.include_router(certificates_route.router, prefix="/api")
    app.dependency_overrides[get_source_path] = lambda: workspace
    app.dependency_overrides[get_current_user] = lambda: User(
        id="test-user", username="test-user", email="test@ducta.local", roles=["admin"]
    )
    return TestClient(app)


class TestEnvRunsDir:
    def test_resolves_the_template_to_the_environment_output_dir(self, project: Path):
        (project / "data" / "dev").mkdir(parents=True)

        runs_dir = env_runs_dir(project, "dev")

        assert runs_dir == (project / "data" / "dev" / ".ducta" / "runs").resolve()

    def test_never_changes_the_server_process_cwd(self, project: Path):
        before = os.getcwd()
        env_runs_dir(project, "dev")
        assert os.getcwd() == before


class TestGetCertificate:
    def test_finds_a_certificate_under_the_env_scoped_output_dir(
        self, client: TestClient, project: Path
    ):
        _write_certificate(project / "data" / "dev" / ".ducta" / "runs", RUN_ID, "dev")

        resp = client.get(f"/api/projects/batch/certificates/{RUN_ID}")

        assert resp.status_code == 200
        assert resp.json()["run_id"] == RUN_ID

    def test_env_param_restricts_the_search_to_that_environment(
        self, client: TestClient, project: Path
    ):
        _write_certificate(project / "data" / "dev" / ".ducta" / "runs", RUN_ID, "dev")

        assert client.get(f"/api/projects/batch/certificates/{RUN_ID}?env=dev").status_code == 200
        assert (
            client.get(f"/api/projects/batch/certificates/{RUN_ID}?env=staging").status_code == 404
        )

    def test_a_pre_convention_legacy_runs_dir_stays_readable(
        self, client: TestClient, project: Path
    ):
        _write_certificate(project / ".ducta" / "runs", RUN_ID, None)

        resp = client.get(f"/api/projects/batch/certificates/{RUN_ID}")

        assert resp.status_code == 200

    def test_an_unknown_run_is_still_a_404(self, client: TestClient, project: Path):
        (project / "data" / "dev" / ".ducta" / "runs").mkdir(parents=True)

        resp = client.get("/api/projects/batch/certificates/does-not-exist")

        assert resp.status_code == 404


class TestListCertificates:
    def test_lists_runs_from_every_environment_with_its_name(
        self, client: TestClient, project: Path
    ):
        _write_certificate(project / "data" / "dev" / ".ducta" / "runs", "run-dev", "dev")
        _write_certificate(
            project / "data" / "staging" / ".ducta" / "runs", "run-staging", "staging"
        )

        resp = client.get("/api/projects/batch/certificates")

        assert resp.status_code == 200
        by_run = {row["run_id"]: row["environment_name"] for row in resp.json()}
        assert by_run == {"run-dev": "dev", "run-staging": "staging"}

    def test_env_param_filters_the_listing(self, client: TestClient, project: Path):
        _write_certificate(project / "data" / "dev" / ".ducta" / "runs", "run-dev", "dev")
        _write_certificate(
            project / "data" / "staging" / ".ducta" / "runs", "run-staging", "staging"
        )

        resp = client.get("/api/projects/batch/certificates?env=staging")

        assert [row["run_id"] for row in resp.json()] == ["run-staging"]
