"""A node that returns several frames gets a clear error (review 2026-11-11).

It used to fail further down as "Unsupported DataFrame type: <class 'tuple'>".
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ducta.core.execution.runner import NodeExecutor
from tests.core.fakes import FakeContext, FakeFrame


@pytest.mark.parametrize("result", [(FakeFrame(), FakeFrame()), [FakeFrame(), FakeFrame()]])
def test_tuple_or_list_result_is_refused_before_the_write(result):
    context = FakeContext(nodes_config={"n": {"output": ["a.b.c", "a.b.d"]}})
    executor = NodeExecutor(context, MagicMock(), MagicMock(), max_workers=1)
    executor._function_loader = MagicMock()
    executor.input_loader.load_inputs.return_value = []
    executor.input_loader.get_input_param_names.return_value = []
    executor._quality_executor = MagicMock()
    command = MagicMock()
    command.execute.return_value = result
    executor._ml_builder = MagicMock()
    executor._ml_builder.prepare_node_ml_info.side_effect = lambda name, info: info
    executor._ml_builder.create_command.return_value = command
    executor._output_writer = MagicMock()

    with pytest.raises(TypeError, match=r"returned a (tuple|list) of 2; a node returns one"):
        executor.execute_single_node("n", None, None, {})
    executor._output_writer.save.assert_not_called()
