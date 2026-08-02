"""Regression: `NodeRepository.delete()`/`PipelineRepository.delete()` never
checked `expected_sha` (unlike `save()`, which calls `validate_occ` first) —
a delete could silently discard a change someone else committed concurrently,
since nothing verified the file was still at the version the caller last saw.
"""

from __future__ import annotations

import pytest

from ducta.api.exceptions import ConcurrencyError
from ducta.api.repositories.node_repository import NodeRepository
from ducta.api.repositories.pipeline_repository import PipelineRepository


@pytest.fixture
def workspace(tmp_path):
    from git import Repo

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "nodes.yaml").write_text("node_a:\n  module: nodes.a\n")
    (tmp_path / "config" / "pipelines.yaml").write_text("pipe_a:\n  nodes: [node_a]\n")

    # validate_occ is a no-op when file_commit_sha can't resolve a real sha
    # (no git history) — a genuine commit is needed to exercise the check.
    repo = Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test").set_value("user", "email", "test@example.com")
    repo.index.add(["config/nodes.yaml", "config/pipelines.yaml"])
    repo.index.commit("initial")
    return tmp_path


class TestNodeRepositoryDeleteOCC:
    def test_delete_without_expected_sha_still_works(self, workspace):
        repo = NodeRepository(workspace)
        repo.delete("node_a")
        assert "node_a" not in repo.list_all()

    def test_delete_with_stale_expected_sha_raises_concurrency_error(self, workspace):
        repo = NodeRepository(workspace)
        with pytest.raises(ConcurrencyError):
            repo.delete("node_a", expected_sha="not-the-real-sha")


class TestPipelineRepositoryDeleteOCC:
    def test_delete_without_expected_sha_still_works(self, workspace):
        repo = PipelineRepository(workspace)
        repo.delete("pipe_a")
        assert "pipe_a" not in repo.list_all()

    def test_delete_with_stale_expected_sha_raises_concurrency_error(self, workspace):
        repo = PipelineRepository(workspace)
        with pytest.raises(ConcurrencyError):
            repo.delete("pipe_a", expected_sha="not-the-real-sha")
