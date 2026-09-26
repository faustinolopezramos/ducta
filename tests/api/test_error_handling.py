"""Regression tests for the consolidated error handling (middleware/errors.py).

- A custom field validator's 422 came back as a 500: Pydantic puts the
  validator's exception object in the error ``ctx``, which JSONResponse could
  not serialize.
- The 422 body had no ``request_id`` while every other error body did.
- MLOps and Git errors were translated per route (or not at all); they now
  have one global mapping.
- ``http_error_on`` replaces the hand-written ``except ValueError`` stanzas.
- Deleting a pipeline that does not exist answered 204.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from ducta.api.core.git_sync import GitSyncError
from ducta.api.exceptions import PipelineNotFoundError, http_error_on
from ducta.api.middleware import register_middleware
from ducta.api.repositories.project_repository import ProjectRepository
from ducta.api.utils.validators import validate_environment_name, validate_project_name
from ducta.mlrun.exceptions import ModelNotFoundError, StorageBackendError


class _Body(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _check(cls, v: str) -> str:
        raise ValueError("never valid")


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_middleware(app)

    @app.post("/validated")
    async def validated(body: _Body) -> dict:
        return {}

    @app.get("/model")
    async def model() -> dict:
        raise ModelNotFoundError("m1")

    @app.get("/storage")
    async def storage() -> dict:
        raise StorageBackendError("disk exploded at /secret/path")

    @app.get("/git")
    async def git() -> dict:
        raise GitSyncError("nothing to push")

    @app.get("/value/{code}")
    async def value(code: int) -> dict:
        with http_error_on(code):
            raise ValueError("bad input")

    return TestClient(app, raise_server_exceptions=False)


def test_custom_validator_error_is_422_with_request_id(client):
    resp = client.post("/validated", json={"name": "x"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "VALIDATION_ERROR"
    assert body["request_id"]
    assert "never valid" in str(body["detail"])


def test_mlops_not_found_maps_to_404(client):
    resp = client.get("/model")
    assert resp.status_code == 404
    assert resp.json()["request_id"]


def test_unmapped_mlops_error_is_500_without_leaking_its_message(client):
    resp = client.get("/storage")
    assert resp.status_code == 500
    assert "/secret/path" not in resp.text


def test_git_sync_error_is_400_with_the_code_the_ui_maps(client):
    resp = client.get("/git")
    assert resp.status_code == 400
    assert resp.json()["error"] == "GIT_ERROR"


@pytest.mark.parametrize("code", [400, 404, 422])
def test_http_error_on_translates_value_error(client, code):
    resp = client.get(f"/value/{code}")
    assert resp.status_code == code
    assert resp.json()["message"] == "bad input"


def test_http_error_on_leaves_other_exceptions_alone():
    with pytest.raises(KeyError):
        with http_error_on(400):
            raise KeyError("x")
    with pytest.raises(HTTPException):
        with http_error_on(400, KeyError):
            raise KeyError("x")


class TestNameValidators:
    @pytest.mark.parametrize("name", ["sales", "Sales_2", "a-b"])
    def test_project_name_accepts(self, name):
        assert validate_project_name(name) == name

    @pytest.mark.parametrize("name", ["1abc", "_x", "a.b", "a b", "", "x" * 65])
    def test_project_name_rejects(self, name):
        with pytest.raises(ValueError):
            validate_project_name(name)

    @pytest.mark.parametrize("env", ["dev", "PROD", "stage-2", "base"])
    def test_env_name_accepts(self, env):
        assert validate_environment_name(env) == env

    @pytest.mark.parametrize("env", ["", "a/b", "x;y", "e" * 65])
    def test_env_name_rejects(self, env):
        with pytest.raises(ValueError):
            validate_environment_name(env)


def test_deleting_a_missing_pipeline_is_not_found(tmp_path):
    repo = ProjectRepository(tmp_path)
    (tmp_path / "projects" / "p1" / "config").mkdir(parents=True)
    (tmp_path / "projects" / "p1" / "config" / "pipelines.yaml").write_text("a: {nodes: []}\n")
    with pytest.raises(PipelineNotFoundError):
        repo.delete_pipeline("p1", "missing")
