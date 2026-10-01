"""API projects are format-2 projects: create, read, update and delete.

A project's API metadata (description, variables, timestamps) lives in its
``ducta.yaml`` — ``description`` and ``metadata`` — so what the UI edits is the
same file the CLI runs, and every write leaves a project the loader accepts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ducta.api.exceptions import ProjectAlreadyExistsError, ProjectNotFoundError, ValidationError
from ducta.api.models.project import ProjectCreateRequest, ProjectUpdateRequest
from ducta.api.services.project import ProjectService
from ducta.setting.project_loader import compile_project, validate_project


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "projects").mkdir()
    return tmp_path


@pytest.fixture
def service(workspace: Path) -> ProjectService:
    return ProjectService(workspace)


def _create(service: ProjectService, name: str = "sales", **kw):
    return service.create_project(ProjectCreateRequest(name=name, **kw), auto_commit=False)


class TestCreate:
    def test_writes_a_loadable_format_2_project(self, service, workspace):
        _create(service, description="Daily sales", variables={"region": "eu"})
        root = workspace / "projects" / "sales"

        manifest = yaml.safe_load((root / "ducta.yaml").read_text())
        assert manifest["version"] == 2
        assert manifest["description"] == "Daily sales"
        assert manifest["metadata"]["variables"] == {"region": "eu"}
        assert (root / "catalog.yaml").is_file()
        assert (root / "pipelines").is_dir()
        for env in ("dev", "prod"):
            compile_project(validate_project(root, env))

    def test_reads_back_what_was_written(self, service):
        created = _create(service, description="Daily sales", variables={"region": "eu"})
        fetched = service.get_project("sales")
        assert fetched.description == created.description == "Daily sales"
        assert fetched.variables == {"region": "eu"}
        assert fetched.created_at and fetched.updated_at
        assert fetched.pipeline_count == 0

    def test_a_second_create_is_refused(self, service):
        _create(service)
        with pytest.raises(ProjectAlreadyExistsError):
            _create(service)


class TestList:
    def test_lists_only_format_2_projects(self, service, workspace):
        _create(service, "alpha")
        _create(service, "beta")
        (workspace / "projects" / "stray").mkdir()
        listing = service.list_projects_paginated()
        assert [p.id for p in listing.projects] == ["alpha", "beta"]


class TestUpdate:
    def test_keeps_comments_and_the_rest_of_the_manifest(self, service, workspace):
        _create(service)
        manifest = workspace / "projects" / "sales" / "ducta.yaml"
        manifest.write_text("# owned by the data team\n" + manifest.read_text())

        service.update_project(
            "sales", ProjectUpdateRequest(description="Sales, hourly"), auto_commit=False
        )

        text = manifest.read_text()
        assert text.startswith("# owned by the data team")
        data = yaml.safe_load(text)
        assert data["description"] == "Sales, hourly"
        assert data["paths"] == {"input": "data", "output": "data"}
        assert service.get_project("sales").description == "Sales, hourly"

    def test_unknown_project_is_not_found(self, service):
        with pytest.raises(ProjectNotFoundError):
            service.update_project("ghost", ProjectUpdateRequest(description="x"))


class TestDelete:
    def test_removes_the_directory(self, service, workspace):
        _create(service)
        service.delete_project("sales", auto_commit=False)
        assert not (workspace / "projects" / "sales").exists()

    def test_a_project_with_pipelines_needs_force(self, service, workspace):
        _create(service)
        (workspace / "projects" / "sales" / "pipelines" / "etl.yaml").write_text(
            "nodes:\n  a: {run: 'm:f'}\n"
        )
        with pytest.raises(ValidationError, match="1 pipeline"):
            service.delete_project("sales", auto_commit=False)
        service.delete_project("sales", auto_commit=False, force=True)
        assert not (workspace / "projects" / "sales").exists()
