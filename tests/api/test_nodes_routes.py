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
