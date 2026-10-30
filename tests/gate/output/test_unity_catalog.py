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

    def test_quote_table_name(self):
        ucm = UnityCatalogManager({"spark": MagicMock()})
        result = ucm.quote_table_name("cat.sch.tbl")
        assert result == "`cat`.`sch`.`tbl`"


class TestUnityCatalogConfigFromOutputConfig:
    PARSED = {"schema": "silver", "sub_folder": "sales", "table_name": "orders"}

    def test_names_fall_back_to_the_output_key_and_defaults_apply(self):
        cfg = UnityCatalogConfig.from_output_config({"catalog_name": "main"}, self.PARSED, "dev")
        assert (cfg.catalog_name, cfg.schema, cfg.table_name) == ("main", "silver", "orders")
        assert cfg.uc_table_mode == "external"
        assert cfg.write_mode == "overwrite"
        assert cfg.optimize is True and cfg.vacuum is False

    def test_environment_placeholder_is_filled_in_every_name(self):
        config = {
            "catalog_name": "{environment}_cat",
            "schema": "s_{environment}",
            "table_name": "t_{environment}",
        }
        cfg = UnityCatalogConfig.from_output_config(config, self.PARSED, "prod")
        assert (cfg.catalog_name, cfg.schema, cfg.table_name) == ("prod_cat", "s_prod", "t_prod")

    def test_explicit_values_win(self):
        config = {
            "catalog_name": "c",
            "uc_table_mode": "managed",
            "write_mode": "append",
            "partition_col": "d",
            "vacuum": True,
            "vacuum_retention_hours": 200,
            "options": {"k": "v"},
        }
        cfg = UnityCatalogConfig.from_output_config(config, self.PARSED, "dev")
        assert (cfg.uc_table_mode, cfg.write_mode, cfg.partition_col) == ("managed", "append", "d")
        assert (cfg.vacuum, cfg.vacuum_retention_hours, cfg.options) == (True, 200, {"k": "v"})

    def test_a_missing_catalog_name_is_a_key_error(self):
        with pytest.raises(KeyError, match="catalog_name"):
            UnityCatalogConfig.from_output_config({}, self.PARSED, "dev")

    def test_an_unknown_table_mode_is_refused(self):
        with pytest.raises(ConfigurationError, match="uc_table_mode"):
            UnityCatalogConfig.from_output_config(
                {"catalog_name": "c", "uc_table_mode": "weird"}, self.PARSED, "dev"
            )


class TestEnvironmentPlaceholder:
    PARSED = {"schema": "silver", "table_name": "orders"}

    def test_only_the_environment_placeholder_is_replaced(self):
        cfg = UnityCatalogConfig.from_output_config(
            {"catalog_name": "{environment}_main", "schema": "s_{environment}"},
            self.PARSED,
            "dev",
        )
        assert (cfg.catalog_name, cfg.schema) == ("dev_main", "s_dev")

    def test_other_braces_are_left_alone_not_evaluated(self):
        cfg = UnityCatalogConfig.from_output_config(
            {"catalog_name": "{environment.__class__}_{x}"}, self.PARSED, "dev"
        )
        assert cfg.catalog_name == "{environment.__class__}_{x}"
