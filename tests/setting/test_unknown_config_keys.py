"""A mistyped config key used to validate clean and be silently ignored.

Every schema sets ``extra="allow"``, which is load-bearing — it is how
forward-compatible and user-owned keys survive a round-trip through validation.
The cost was that a misspelling was indistinguishable from an intentional extra:
``max_paralel_nodes: 16`` validated, and the pipeline ran on the default of 4
with nothing said. Warning (rather than rejecting) keeps the escape hatch open
while making the typo visible.
"""

from __future__ import annotations

import pytest
from loguru import logger

from ducta.setting.schemas import GlobalConfigSchema

_REQUIRED = {"input_path": "/in", "output_path": "/out"}


@pytest.fixture
def warnings_emitted():
    captured: list[str] = []
    sink = logger.add(lambda m: captured.append(m), level="WARNING")
    logger.enable("ducta")
    try:
        yield captured
    finally:
        logger.remove(sink)


def test_a_near_miss_suggests_the_intended_key(warnings_emitted):
    GlobalConfigSchema(**_REQUIRED, max_paralel_nodes=16)
    joined = "".join(warnings_emitted)
    assert "max_paralel_nodes" in joined
    assert "max_parallel_nodes" in joined, "the correction should be suggested"


def test_an_unrelated_key_warns_without_a_bogus_suggestion(warnings_emitted):
    GlobalConfigSchema(**_REQUIRED, my_own_bookkeeping_key=1)
    joined = "".join(warnings_emitted)
    assert "my_own_bookkeeping_key" in joined
    assert "did you mean" not in joined.lower()


def test_extras_are_still_preserved_not_dropped(warnings_emitted):
    """Warning must not turn into rejecting: the escape hatch still works."""
    schema = GlobalConfigSchema(**_REQUIRED, my_own_bookkeeping_key=7)
    assert schema.my_own_bookkeeping_key == 7


@pytest.mark.parametrize("field", ["in_memory_handoff", "max_input_workers", "fill_none_on_error"])
def test_keys_the_engine_actually_reads_are_declared(field, warnings_emitted):
    """These three are read via `get_nested` but were undeclared, so they would
    have been reported as typos the moment the warning was added."""
    assert field in GlobalConfigSchema.model_fields
    GlobalConfigSchema(**_REQUIRED, **{field: 1 if field == "max_input_workers" else True})
    assert not warnings_emitted


def test_runtime_injected_keys_never_warn(warnings_emitted):
    """`Context` writes these into global_config after validation."""
    GlobalConfigSchema(**_REQUIRED, environment="dev", pipeline_name="etl")
    assert not warnings_emitted


def test_a_clean_config_is_silent(warnings_emitted):
    GlobalConfigSchema(**_REQUIRED, max_parallel_nodes=8, mode="local")
    assert not warnings_emitted


@pytest.mark.parametrize("template_type", ["medallion_basic", "streaming_basic"])
@pytest.mark.parametrize("evidence_level", ["record", "signed"])
def test_a_freshly_generated_project_has_no_unknown_keys(
    template_type, evidence_level, warnings_emitted
):
    """The first run of a brand-new project used to print nine "Unknown key"
    warnings for keys the template itself wrote — noise that teaches users to
    ignore the one warning that catches real typos."""
    from ducta.console.template import TemplateFactory, TemplateType

    template = TemplateFactory.create_template(TemplateType(template_type), "p")
    template.evidence_level = evidence_level
    GlobalConfigSchema(**template.generate_global_config())

    assert "Unknown key" not in "".join(warnings_emitted)
