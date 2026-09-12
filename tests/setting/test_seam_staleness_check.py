"""The seam between GlobalConfigSchema.chain.staleness_check and
CoreSettings.chain_staleness_check.

``schemas.py::ChainReuseConfig.staleness_check`` documents, in its own
docstring, that it "must stay in step with CoreSettings.chain_staleness_check"
— Context replaces global_config with this schema's model_dump, and
exclude_none does not drop a False, so a default that disagrees here would
silently override the one the engine resolves. The sibling field
``min_pass_rate`` already diverged this way once in production (see
``tests/check/test_gate_schema_seam.py``), with nothing crossing the seam to
catch it; this test is that seam for ``staleness_check``.
"""

from __future__ import annotations

from ducta.core.settings import CoreSettings
from ducta.setting.schemas import GlobalConfigSchema


def _global_config_through_schema() -> dict:
    """A minimal global config, round-tripped through the schema, with the
    ``chain`` section present (but not overriding staleness_check) so its
    default actually resolves rather than staying ``None``."""
    schema = GlobalConfigSchema(
        input_path="data",
        output_path="data",
        chain={"reuse_materialized": True},
    )
    return schema.model_dump(exclude_none=True)


def test_schema_and_core_settings_default_agree():
    dumped = _global_config_through_schema()
    schema_default = dumped["chain"]["staleness_check"]

    core_default = CoreSettings.from_context({}).chain_staleness_check

    assert schema_default == core_default
