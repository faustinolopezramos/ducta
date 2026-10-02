"""``get_pipeline_info`` must return what its callers are documented to get.

``Context.pipelines`` is the *expanded* view built by
``PipelineManager._generate_pipeline_config``: it replaces each node name with
that node's whole config dict. That shape is right for the executor, which needs
the configs, and wrong for ``get_pipeline_info``, whose callers treat ``nodes``
as a list of names — ``", ".join(...)`` it, print it, test membership against
``--node``.

The mismatch was not theoretical: ``ducta config pipeline-info`` crashed on every
project, and three separate callers had grown their own hand-written
``n if isinstance(n, str) else n.get("name")`` coercion to work around it.

``description`` had the same root cause from the other direction: the expansion
dropped the key entirely, so every caller reported an empty description.
"""

from __future__ import annotations

import pytest

from ducta.core.executors.facade import PipelineExecutor
from ducta.setting.contexts import Context

GLOBAL_CONFIG = {
    "input_path": "data",
    "output_path": "data",
    "mode": "local",
    "preflight_enabled": False,
    "evidence_level": "off",
}

NODES_CONFIG = {
    "extract": {"module": "nodes", "function": "extract", "output": ["bronze.etl.raw"]},
    "transform": {
        "module": "nodes",
        "function": "transform",
        "input": ["bronze.etl.raw"],
        "output": ["silver.etl.clean"],
    },
}

PIPELINES_CONFIG = {
    "etl": {
        "type": "batch",
        "description": "Complete ETL pipeline",
        "nodes": ["extract", "transform"],
        "requires_dates": False,
    }
}


@pytest.fixture
def executor() -> PipelineExecutor:
    context = Context(
        global_config=dict(GLOBAL_CONFIG),
        pipelines_config={k: dict(v) for k, v in PIPELINES_CONFIG.items()},
        nodes_config={k: dict(v) for k, v in NODES_CONFIG.items()},
        input_config={"bronze.etl.raw": {"format": "parquet", "filepath": "x"}},
        output_config={
            "bronze.etl.raw": {"format": "parquet"},
            "silver.etl.clean": {"format": "parquet"},
        },
    )
    return PipelineExecutor(context)


class TestPipelineInfoShape:
    def test_nodes_are_names_not_configs(self, executor):
        """What every caller assumes, and what none of them got."""
        info = executor.get_pipeline_info("etl")

        assert info["nodes"] == ["extract", "transform"]

    def test_nodes_can_be_joined(self, executor):
        """``ducta config pipeline-info`` does exactly this and used to crash with
        ``TypeError: sequence item 0: expected str instance, dict found``."""
        info = executor.get_pipeline_info("etl")

        assert ", ".join(info["nodes"]) == "extract, transform"

    def test_node_membership_works(self, executor):
        """``--node`` validation tests membership; against dicts it never matched,
        so the CLI warned "may not exist" for every node that did exist."""
        info = executor.get_pipeline_info("etl")

        assert "extract" in info["nodes"]
        assert "nonexistent" not in info["nodes"]

    def test_description_survives_expansion(self, executor):
        info = executor.get_pipeline_info("etl")

        assert info["description"] == "Complete ETL pipeline"

    def test_missing_pipeline_still_reports_absence(self, executor):
        info = executor.get_pipeline_info("nope")

        assert info["exists"] is False
        assert info["nodes"] == []
