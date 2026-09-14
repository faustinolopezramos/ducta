"""Regression test: `_validate_node_name`'s regex allows a bare "." or ".."
(both are single path components made only of allowed characters), which
could resolve to "this directory"/"parent directory" wherever the node name
is later joined onto a filesystem path.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ducta.api.routes.nodes import _validate_node_name


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

        from ducta.api.routes import nodes as nodes_route
        from ducta.api.services.node_service import NodeService

        accepted = set(inspect.signature(NodeService.save_node).parameters)
        source = inspect.getsource(nodes_route.update_node)

        # Whatever keyword the route uses for the OCC sha has to be one the
        # service actually accepts.
        assert "expected_sha=" in source
        assert "expected_sha" in accepted
        assert "expected_commit_sha=body.expected_commit_sha" not in source

    def test_delete_still_passes_its_own_argument(self):
        import inspect

        from ducta.api.routes import nodes as nodes_route
        from ducta.api.services.node_service import NodeService

        accepted = set(inspect.signature(NodeService.delete_node).parameters)
        assert "expected_sha=" in inspect.getsource(nodes_route.delete_node)
        assert "expected_sha" in accepted
