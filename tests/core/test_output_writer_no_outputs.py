"""A node that declares no outputs runs for its effect.

The schema and `ducta config validate` accept a node without `outputs` (a notifier,
an audit, a train-and-register step), and the docs show such nodes. Its return value
was still validated as a DataFrame, so it failed every run: "Result DataFrame is None"
for `return None`, "Unsupported DataFrame type: dict" for a metrics dict.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ducta.core.errors import SchemaValidationError
from ducta.core.execution.output import OutputWriter
from tests.core.fakes import FakeContext


@pytest.mark.parametrize("returned", [None, {"val_f1": 0.9}, "done"])
def test_a_node_without_outputs_is_not_validated_or_saved(returned):
    manager = MagicMock()
    writer = OutputWriter(manager, FakeContext())

    writer.save(returned, {"run": "pipelines.x:notify"}, "notify", "2026-01-01", "2026-01-01", {})

    manager.save_output.assert_not_called()


def test_a_node_with_outputs_still_needs_a_dataframe():
    writer = OutputWriter(MagicMock(), FakeContext())

    with pytest.raises(SchemaValidationError):
        writer.save(None, {"output": ["silver.x"]}, "clean", "2026-01-01", "2026-01-01", {})
