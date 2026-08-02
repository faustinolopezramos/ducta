"""Regression tests for `ProjectRepository.project_dir` path validation.

`project_dir(project_id)` did `projects_root() / project_id` with no validation
beyond a special case for `project_id in (".", root.name)`. A `project_id` of
`".."` resolved to `projects_root().parent == workspace_root`, so any route
that reaches `project_dir()` (confirmed against a real uvicorn server) — e.g.
`DELETE /api/projects/..?force=true` — could delete the entire workspace.
"""

from __future__ import annotations

import pytest

from ducta.api.exceptions import ValidationError
from ducta.api.repositories.project_repository import ProjectRepository


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "projects").mkdir()
    return ProjectRepository(tmp_path)


class TestProjectDirRejectsTraversal:
    def test_dotdot_is_rejected(self, repo):
        with pytest.raises(ValidationError):
            repo.project_dir("..")

    def test_nested_traversal_is_rejected(self, repo):
        with pytest.raises(ValidationError):
            repo.project_dir("../../etc")

    def test_path_separator_is_rejected(self, repo):
        with pytest.raises(ValidationError):
            repo.project_dir("foo/../bar")

    def test_absolute_path_is_rejected(self, repo):
        with pytest.raises(ValidationError):
            repo.project_dir("/etc/passwd")


class TestProjectDirAllowsLegitimateIds:
    def test_ordinary_name_resolves_under_projects_root(self, repo, tmp_path):
        assert repo.project_dir("my_project") == tmp_path / "projects" / "my_project"

    def test_dot_is_the_workspace_root_special_case(self, repo, tmp_path):
        assert repo.project_dir(".") == tmp_path

    def test_root_name_is_the_workspace_root_special_case(self, repo, tmp_path):
        assert repo.project_dir(tmp_path.name) == tmp_path
