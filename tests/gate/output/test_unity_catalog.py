from unittest.mock import MagicMock

import pytest

from ducta.gate.exceptions import ConfigurationError
from ducta.gate.output import UnityCatalogConfig, UnityCatalogManager


class TestUnityCatalogConfig:
    def test_valid(self):
        cfg = UnityCatalogConfig(catalog_name="cat", schema="sch", table_name="tbl")
        assert cfg.uc_table_mode == "external"

    def test_invalid_mode(self):
        with pytest.raises(ConfigurationError, match="uc_table_mode"):
            UnityCatalogConfig(
                catalog_name="cat",
                schema="sch",
                table_name="tbl",
                uc_table_mode="invalid",
            )


class TestUnityCatalogManager:
    def test_init_not_enabled(self, dict_context):
        ucm = UnityCatalogManager(dict_context)
        assert ucm.is_enabled() is False

    def test_init_enabled(self, spark_session):
        spark_session.conf.get.return_value = "true"
        ucm = UnityCatalogManager({"spark": spark_session})
        assert ucm.is_enabled() is True

    def test_clear_metadata_cache(self, dict_context_with_spark):
        ucm = UnityCatalogManager(dict_context_with_spark)
        ucm._catalog_cache["test"] = True
        ucm.clear_metadata_cache()
        assert ucm._catalog_cache == {}

    def test_quote_table_name(self):
        ucm = UnityCatalogManager({"spark": MagicMock()})
        result = ucm.quote_table_name("cat.sch.tbl")
        assert result == "`cat`.`sch`.`tbl`"
