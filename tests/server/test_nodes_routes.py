"""Regression test: `_validate_node_name`'s regex allows a bare "." or ".."
(both are single path components made only of allowed characters), which
could resolve to "this directory"/"parent directory" wherever the node name
is later joined onto a filesystem path.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ducta_server.routes.nodes import _validate_node_name


class TestValidateNodeName:
    def test_ordinary_name_accepted(self):
        _validate_node_name("my_node-1.v2")

    def test_dotdot_rejected(self):
        with pytest.raises(HTTPException):
            _validate_node_name("..")

    def test_dot_rejected(self):
        with pytest.raises(HTTPException):
            _validate_node_name(".")

    def test_slash_rejected(self):
        with pytest.raises(HTTPException):
            _validate_node_name("foo/bar")


class TestUpdateNodeCallsTheServiceCorrectly:
    """`PUT /nodes/{name}` answered 500 for every request.

    The route called ``save_node(..., expected_commit_sha=...)`` while the
    service parameter is ``expected_sha`` (``delete_node`` already passed the
    right one), so the handler raised ``TypeError`` before touching disk — which
    is why adding a node from the canvas never worked. Nothing covered it.
    """

    def test_the_route_passes_the_argument_the_service_declares(self):
        import inspect

        from ducta_server.routes import nodes as nodes_route
        from ducta_server.services.node_service import NodeService

        accepted = set(inspect.signature(NodeService.save_node).parameters)
        source = inspect.getsource(nodes_route.update_node)

        # Whatever keyword the route uses for the OCC sha has to be one the
        # service actually accepts.
        assert "expected_sha=" in source
        assert "expected_sha" in accepted
        assert "expected_commit_sha=body.expected_commit_sha" not in source

    def test_delete_still_passes_its_own_argument(self):
        import inspect

        from ducta_server.routes import nodes as nodes_route
        from ducta_server.services.node_service import NodeService

        accepted = set(inspect.signature(NodeService.delete_node).parameters)
        assert "expected_sha=" in inspect.getsource(nodes_route.delete_node)
        assert "expected_sha" in accepted


# ── the routes, against a real project ───────────────────────────────────────


@pytest.fixture
def project(tmp_path, monkeypatch):
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


@pytest.fixture
def api(project):
    from fastapi.testclient import TestClient

    from ducta_server.main import create_app

    client = TestClient(create_app())
    client.params = {"source": str(project)}  # type: ignore[assignment]
    return client


class TestNodeRoutes:
    def test_list_and_get(self, api):
        listed = api.get("/api/nodes").json()
        assert set(listed["nodes"]) == {"extract", "transform", "load"}
        assert listed["count"] == 3

        node = api.get("/api/nodes/extract").json()
        assert (node["spec"]["module"], node["spec"]["function"]) == ("pipelines.etl", "extract")
        assert node["commit_sha"]

    def test_unknown_node_is_404_and_a_bad_name_400(self, api):
        assert api.get("/api/nodes/ghost").status_code == 404
        assert api.get("/api/nodes/bad name").status_code == 400
        assert api.delete("/api/nodes/ghost").status_code == 404

    def test_code_and_its_preview(self, api):
        full = api.get("/api/nodes/extract/code").json()
        assert full["module_path"] == "pipelines/etl.py"
        assert full["exists"] and "def extract" in full["code"]

        preview = api.get("/api/nodes/extract/code", params={"preview": 3}).json()
        assert preview["code"] == "\n".join(full["code"].split("\n")[:3])
        assert preview["size_bytes"] == full["size_bytes"]

    def test_code_by_module(self, api):
        body = api.get("/api/nodes/anything/code", params={"module": "pipelines.etl"}).json()
        assert body["module_path"] == "pipelines/etl.py"

    def test_ast_lists_top_level_functions_and_imports(self, api, project):
        (project / "pipelines" / "shapes.py").write_text(
            "import os\n"
            "from typing import Any\n\n"
            "@staticmethod\n"
            "def plain(a, b) -> int:\n"
            '    """Adds."""\n'
            "    def inner():\n"
            "        pass\n"
            "    return a + b\n\n"
            "async def later(x):\n"
            "    return x\n",
            encoding="utf-8",
        )
        body = api.post("/api/nodes/shapes/code/ast", params={"module": "pipelines.shapes"}).json()
        assert body["imports"] == ["os", "typing.Any"]
        plain, later = body["functions"]
        assert (plain["name"], plain["params"], plain["return_type"]) == (
            "plain",
            ["a", "b"],
            "int",
        )
        assert (plain["decorators"], plain["docstring"]) == (["staticmethod"], "Adds.")
        assert (later["name"], later["is_async"]) == ("later", True)

    def test_ast_reports_a_syntax_error_instead_of_failing(self, api, project):
        (project / "pipelines" / "broken.py").write_text("def oops(:\n", encoding="utf-8")
        body = api.post("/api/nodes/broken/code/ast", params={"module": "pipelines.broken"}).json()
        assert body["functions"] == []
        assert body["error"].startswith("Syntax error")

    def test_save_code_writes_valid_python_and_refuses_invalid(self, api, project):
        code = "def extract(source_data, start_date=None, end_date=None):\n    return source_data\n"
        saved = api.put("/api/nodes/extract/code", json={"code": code})
        assert saved.status_code == 200
        assert (project / "pipelines" / "etl.py").read_text(encoding="utf-8") == code

        refused = api.put("/api/nodes/extract/code", json={"code": "def broken(:\n"})
        assert refused.status_code == 400
        assert (project / "pipelines" / "etl.py").read_text(encoding="utf-8") == code

    def test_update_spec_and_a_stale_version_is_refused(self, api):
        current = api.get("/api/nodes/load").json()
        spec = {**current["spec"], "description": "Gold, described again"}
        updated = api.put(
            "/api/nodes/load", json={"spec": spec, "expected_commit_sha": current["commit_sha"]}
        )
        assert updated.status_code == 200
        assert api.get("/api/nodes/load").json()["spec"]["description"] == "Gold, described again"

        stale = api.put(
            "/api/nodes/load",
            json={"spec": current["spec"], "expected_commit_sha": current["commit_sha"]},
        )
        assert stale.status_code == 409

    def test_a_name_that_derives_no_module_is_refused(self, api):
        response = api.put("/api/nodes/my-node", json={"spec": {"function": "f"}})
        assert response.status_code == 400
        assert "Python identifier" in response.json()["message"]

    def test_node_executions_ask_the_manager_for_this_node(self, api, project):
        from ducta_server.dependencies import get_execution_manager

        seen = {}

        class _Manager:
            def list_executions_paginated(self, **kwargs):
                seen.update(kwargs)
                return [], 0

        api.app.dependency_overrides[get_execution_manager] = lambda: _Manager()
        body = api.get("/api/nodes/extract/executions", params={"limit": 5}).json()
        assert (body["count"], body["limit"]) == (0, 5)
        assert (seen["node_name"], seen["workspace"]) == ("extract", project.resolve())

    def test_saving_each_node_as_read_changes_nothing_the_engine_sees(self, api, project):
        """GET returns ``inputs``/``outputs`` lists; PUT used to refuse exactly that (400).

        Neither what the engine compiles nor the file changes: the quality blocks
        come back compiled (long form) and used to overwrite the short form the
        template wrote, comments and all.
        """
        from ducta.project_store.store import V2ProjectStore
        from ducta.setting.project import compile_project

        def compiled():
            return compile_project(V2ProjectStore(project).project(None))

        files = sorted((project / "pipelines").glob("*.yaml"))
        text_before = [f.read_text(encoding="utf-8") for f in files]
        before = compiled()
        for name in ("extract", "transform", "load"):
            current = api.get(f"/api/nodes/{name}").json()
            saved = api.put(
                f"/api/nodes/{name}",
                json={"spec": current["spec"], "expected_commit_sha": current["commit_sha"]},
            )
            assert saved.status_code == 200, (name, saved.json())
        assert compiled() == before
        assert [f.read_text(encoding="utf-8") for f in files] == text_before

    def test_a_changed_check_is_written(self, api, project):
        current = api.get("/api/nodes/transform").json()
        spec = current["spec"]
        spec["data_quality"]["checks"]["row_count"] = {"min": 7}
        saved = api.put(
            "/api/nodes/transform",
            json={"spec": spec, "expected_commit_sha": current["commit_sha"]},
        )
        assert saved.status_code == 200, saved.json()
        again = api.get("/api/nodes/transform").json()["spec"]
        assert again["data_quality"]["checks"]["row_count"] == {"min": 7}
