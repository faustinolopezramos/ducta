"""The environment picker marks the canonical environments a project does not
declare: they run with the base configuration, which nothing used to say."""

from __future__ import annotations

from ducta_server.repositories.project_repository import ProjectRepository
from ducta_server.workspace.manager import WorkspaceManager


def test_declared_environments_are_base_plus_the_projects_own(tmp_path):
    (tmp_path / "projects").mkdir()
    ProjectRepository(tmp_path).create("batch", {})
    manifest = tmp_path / "projects" / "batch" / "ducta.yaml"
    manifest.write_text(manifest.read_text() + "\nenvironments:\n  dev: {}\n  qa: {}\n")
    manager = WorkspaceManager(tmp_path).for_project("batch")

    assert manager.declared_environments() == ["base", "dev", "qa"]
    listed = manager.list_environments()
    assert "staging" in listed and "qa" in listed
