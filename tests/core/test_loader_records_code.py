"""`FunctionLoader` is the single choke point where node code is resolved, so
it is where the code fingerprint has to be recorded — on every load, cache hits
included."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ducta.core.code_fingerprint import clear_cache
from ducta.core.execution.loader import FunctionLoader
from ducta.core.ledger import ledger_for


def _loader(context) -> FunctionLoader:
    loader = FunctionLoader.__new__(FunctionLoader)
    loader.context = context
    loader.settings = MagicMock()
    loader.is_ml_layer = False
    loader._function_cache = {}
    loader.secure_importer = MagicMock()
    return loader


def sample_node(df, start_date, end_date):
    return df


class TestLoaderRecordsCode:
    def setup_method(self):
        clear_cache()

    def test_a_loaded_node_lands_in_the_ledger(self):
        context = SimpleNamespace()
        loader = _loader(context)
        loader.secure_importer.get_function_from_module.return_value = sample_node

        loader.load({"name": "clean_sales", "module": "nodes", "function": "clean_sales"})

        recorded = ledger_for(context).code_fingerprints
        assert recorded["clean_sales"]["source_hash"].startswith("sha256:")
        assert recorded["clean_sales"]["module"] == "nodes"
        assert recorded["clean_sales"]["function"] == "clean_sales"

    def test_a_cache_hit_still_records(self):
        """A chained run reuses the loader but resets the ledger between
        pipelines, so recording only on the cache miss would leave the second
        pipeline's certificate silently missing its code evidence."""
        context = SimpleNamespace()
        loader = _loader(context)
        loader.secure_importer.get_function_from_module.return_value = sample_node
        node = {"name": "clean_sales", "module": "nodes", "function": "clean_sales"}

        loader.load(node)
        ledger = ledger_for(context)
        ledger.reset()
        assert ledger.code_fingerprints == {}

        loader.load(node)  # served from the loader's cache this time

        assert "clean_sales" in ledger.code_fingerprints

    def test_a_node_without_a_name_falls_back_to_module_and_function(self):
        context = SimpleNamespace()
        loader = _loader(context)
        loader.secure_importer.get_function_from_module.return_value = sample_node

        loader.load({"module": "nodes", "function": "clean_sales"})

        assert "nodes.clean_sales" in ledger_for(context).code_fingerprints

    def test_a_fingerprinting_failure_is_a_recorded_gap_not_a_crash(self):
        context = SimpleNamespace()
        loader = _loader(context)
        loader.secure_importer.get_function_from_module.return_value = sample_node

        with patch(
            "ducta.core.code_fingerprint.fingerprint_callable",
            side_effect=RuntimeError("boom"),
        ):
            func = loader.load({"name": "n", "module": "m", "function": "f"})

        assert func is sample_node, "the node must still run"
        ledger = ledger_for(context)
        assert ledger.evidence_complete is False
        assert any("code fingerprint" in gap for gap in ledger.record_failures)
