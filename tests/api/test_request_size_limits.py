"""Regression tests: request-body fields with no size limit could buffer an
arbitrarily large payload in memory (and, for file-writing endpoints, on
disk) per request.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ducta.api.models.execution import BulkCancelRequest
from ducta.api.models.workspace import WriteFileRequest
from ducta.api.routes.nodes import NodeCodeUpdateRequest


class TestWriteFileRequestContentLimit:
    def test_ordinary_content_accepted(self):
        WriteFileRequest(path="a.txt", content="hello")

    def test_oversized_content_rejected(self):
        with pytest.raises(ValidationError):
            WriteFileRequest(path="a.txt", content="x" * (10 * 1024 * 1024 + 1))


class TestNodeCodeUpdateRequestLimit:
    def test_ordinary_code_accepted(self):
        NodeCodeUpdateRequest(code="def run():\n    pass\n")

    def test_oversized_code_rejected(self):
        with pytest.raises(ValidationError):
            NodeCodeUpdateRequest(code="x" * (10 * 1024 * 1024 + 1))


class TestBulkCancelRequestLimit:
    def test_ordinary_batch_accepted(self):
        BulkCancelRequest(execution_ids=["a", "b", "c"])

    def test_oversized_batch_rejected(self):
        with pytest.raises(ValidationError):
            BulkCancelRequest(execution_ids=["x"] * 1001)

    def test_max_size_batch_accepted(self):
        BulkCancelRequest(execution_ids=["x"] * 1000)
