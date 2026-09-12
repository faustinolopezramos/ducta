"""Regression tests for `ProjectService.import_project`.

`import_project` used to resolve `projects_root`/`settings_path`/`pipelines_path`
via private module-level helpers in `services/project.py` that duplicated
`ProjectRepository`'s equivalents but without the `validate_identifier()` guard
`ProjectRepository.project_dir` uses to block path traversal (see
`tests/api/test_project_repository.py`). Those private helpers were removed and
`import_project` now calls `self._repo` directly, so any future caller of these
paths gets the same traversal guard for free.

These tests are regression coverage for that refactor: normal imports must still
land in the same place, the existing `_SAFE_NAME_RE`/expected-location checks
must still reject bad input, and `import_project` must actually route through
`ProjectRepository` (not a private duplicate) when resolving paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ducta.api.exceptions import ValidationError
from ducta.api.models.project import ImportProjectRequest
from ducta.api.repositories.project_repository import ProjectRepository
from ducta.api.services.project import ProjectService


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "projects").mkdir()
    return tmp_path


@pytest.fixture
def service(workspace: Path) -> ProjectService:
    return ProjectService(workspace)


class TestImportProjectPathResolution:
    def test_normal_import_lands_in_config_subdir(self, service: ProjectService, workspace: Path):
        source = workspace / "projects" / "myproj"
        source.mkdir()

        response = service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

        assert response.id == "myproj"
        settings_file = workspace / "projects" / "myproj" / "config" / "project_settings.yaml"
        pipelines_file = workspace / "projects" / "myproj" / "config" / "pipelines.yaml"
        assert settings_file.exists()
        assert pipelines_file.exists()

    def test_import_uses_project_repository_not_a_private_duplicate(
        self, service: ProjectService, workspace: Path
    ):
        source = workspace / "projects" / "spied"
        source.mkdir()

        with patch.object(ProjectRepository, "project_dir", wraps=service._repo.project_dir) as spy:
            service.import_project(ImportProjectRequest(path=str(source)), auto_commit=False)

        # settings_path()/pipelines_path() both call project_dir() internally, so a
        # successful import must exercise ProjectRepository's guarded implementation.
        assert spy.call_count > 0
        assert all(call.args[0] == "spied" for call in spy.call_args_list)

    def test_reimport_of_existing_project_is_idempotent(
        self, service: ProjectService, workspace: Path
    ):
        source = workspace / "projects" / "again"
        source.mkdir()
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
