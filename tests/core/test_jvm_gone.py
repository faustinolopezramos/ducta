"""When the Spark JVM dies, py4j's error names everything except the likely cause."""

from __future__ import annotations

import pytest

from ducta.console.ux.error_analyzer import classify_error
from ducta.core.errors import JVM_GONE_HINT, is_jvm_gone
from ducta.core.execution.coordinator import ParallelCoordinator
from ducta.core.execution.state import ThreadSafeExecutionState


@pytest.mark.parametrize(
    "text",
    [
        "org.apache.spark does not exist in the JVM",
        "Answer from Java side is empty",
        "Error while sending or receiving",
        "Java gateway process exited before sending its port number",
    ],
)
def test_py4j_reporting_a_dead_jvm_is_recognised(text):
    assert is_jvm_gone(RuntimeError(text))
    analysis = classify_error(f"Py4JError: {text}", None)
    assert analysis["error_type"] == "Spark JVM Stopped"
    assert any("spark.driver.memory" in s for s in analysis["suggestions"])


def test_any_other_error_is_left_alone():
    assert not is_jvm_gone(ValueError("column 'x' does not exist"))


def test_the_pipeline_error_says_what_to_do():
    state = ThreadSafeExecutionState.__new__(ThreadSafeExecutionState)
    state.get_first_failure = lambda: ("n", RuntimeError("x does not exist in the JVM"))
    state.get_execution_results_copy = lambda: {"n": {"status": "failed"}}
    error = ParallelCoordinator._build_failure_error(state)
    assert JVM_GONE_HINT in str(error)
