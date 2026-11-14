"""The connection-test endpoints say what happened: verified, failed, or not tested.

The messages used to be swapped — a refused connection read "inconclusive
(Spark unavailable)", and one nobody had contacted read "verified" with ok=True.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from ducta_server.routes.ingestion import _test_response  # noqa: E402


def test_verified():
    r = _test_response(True)
    assert r.ok is True and "verified" in r.message.lower()


def test_failed_says_failed():
    r = _test_response(False)
    assert r.ok is False and "failed" in r.message.lower()


def test_untested_is_not_ok():
    r = _test_response(None)
    assert r.ok is False and r.message.startswith("Not verified")


def test_connections_are_read_from_the_named_project(tmp_path):
    """Connections live in each project's sources.yaml. Without ``project`` the
    routes read the workspace root, so a multi-project workspace listed none."""
    from ducta_server.repositories.project_repository import ProjectRepository
    from ducta_server.routes.ingestion import _project_manager, _service
    from ducta_server.workspace.manager import WorkspaceManager

    (tmp_path / "projects").mkdir()
    ProjectRepository(tmp_path).create("batch", {})
    (tmp_path / "projects" / "batch" / "config").mkdir()
    (tmp_path / "projects" / "batch" / "config" / "sources.yaml").write_text(
        "sources:\n  warehouse:\n    type: postgres\n    host: db\n    port: 5432\n    database: dw\n"
    )
    workspace = WorkspaceManager(tmp_path)

    names = [c["name"] for c in _service(_project_manager(workspace, "batch")).list_connections()]
    assert names == ["warehouse"]
    assert _service(_project_manager(workspace, None)).list_connections() == []
