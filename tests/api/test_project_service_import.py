"""`ProjectService.import_project`: registering a project already under projects/.

Import resolves every path through `ProjectRepository` (whose `project_dir`
carries the `validate_identifier()` traversal guard) and only accepts a
format-2 project; a format-1 one is refused with the command that converts it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ducta.api.exceptions import ProjectNotFoundError, ValidationError
from ducta.api.models.project import ImportProjectRequest
from ducta.api.repositories.project_repository import ProjectRepository
from ducta.api.services.project import ProjectService


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "projects").mkdir()
    return tmp_path


def _project(directory: Path, description: str = "") -> Path:
    (directory / "pipelines").mkdir(parents=True)
    (directory / "ducta.yaml").write_text(
        f"version: 2\nproject: {directory.name}\ndescription: '{description}'\n"
        "paths: {input: data, output: data}\n"
    )
    return directory


@pytest.fixture
def service(workspace: Path) -> ProjectService:
    return ProjectService(workspace)


class TestImportProjectPathResolution:
    def test_import_reads_the_project_in_place(self, service: ProjectService, workspace: Path):
        source = _project(workspace / "projects" / "myproj", "daily sales")

        response = service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

        assert response.id == "myproj"
        assert response.description == "daily sales"
        assert response.pipeline_count == 0

    def test_a_format_1_project_is_refused_with_the_migrate_command(
        self, service: ProjectService, workspace: Path
    ):
        source = workspace / "projects" / "old"
        source.mkdir()
        (source / "environment.yaml").write_text("env_config: {}\n")

        with pytest.raises(ValidationError, match="ducta config migrate"):
            service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

    def test_a_directory_without_a_project_is_not_found(
        self, service: ProjectService, workspace: Path
    ):
        source = workspace / "projects" / "empty"
        source.mkdir()

        with pytest.raises(ProjectNotFoundError):
            service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

    def test_import_uses_project_repository_not_a_private_duplicate(
        self, service: ProjectService, workspace: Path
    ):
        source = _project(workspace / "projects" / "spied")

        with patch.object(ProjectRepository, "project_dir", wraps=service._repo.project_dir) as spy:
            service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

        # store()/get_settings() resolve through project_dir(), so a successful
        # import must exercise ProjectRepository's guarded implementation.
        assert spy.call_count > 0
        assert all(call.args[0] == "spied" for call in spy.call_args_list)

    def test_reimport_of_existing_project_is_idempotent(
        self, service: ProjectService, workspace: Path
    ):
        source = _project(workspace / "projects" / "again")
        first = service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)
        second = service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

        assert first.id == second.id == "again"


class TestImportProjectRejectsBadInput:
    def test_rejects_directory_name_that_fails_safe_name_check(
        self, service: ProjectService, workspace: Path
    ):
        # A directory name starting with a digit is a legal filesystem name but
        # fails import_project's own _SAFE_NAME_RE check (letters/digits/_/- only,
        # must start with a letter) — this must keep working after the refactor.
        source = workspace / "projects" / "1bad"
        source.mkdir()

        with pytest.raises(ValidationError):
            service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

    def test_rejects_path_outside_projects_root(self, service: ProjectService, workspace: Path):
        source = workspace / "not_under_projects"
        source.mkdir()

        with pytest.raises(ValidationError):
            service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

    def test_rejects_nonexistent_path(self, service: ProjectService, workspace: Path):
        missing = workspace / "projects" / "ghost"

        with pytest.raises(ValidationError):
            service.import_project(ImportProjectRequest(path=str(missing)), auto_commit=False)
