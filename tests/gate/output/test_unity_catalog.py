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


class _RecordingSpark:
    """A session that records every ``spark.sql`` and answers the existence probes."""

    def __init__(self, catalogs=(), schemas=(), fail_on=()):
        self.statements = []
        self.catalogs, self.schemas, self.fail_on = set(catalogs), set(schemas), fail_on
        self.conf = MagicMock()
        self.conf.get.return_value = "true"

    def sql(self, statement):
        self.statements.append(statement)
        if any(word in statement for word in self.fail_on):
            raise RuntimeError("PERMISSION_DENIED")
        found = False
        if "information_schema.catalogs" in statement:
            found = any(f"catalog_name = '{c}'" in statement for c in self.catalogs)
        elif "information_schema.schemata" in statement:
            found = any(
                f"catalog_name = '{c}' AND schema_name = '{s}'" in statement
                for c, s in self.schemas
            )
        result = MagicMock()
        result.take.return_value = [1] if found else []
        return result

    def ddl(self):
        return [s for s in self.statements if not s.startswith("SELECT 1")]


def _cfg(**kw):
    base = dict(catalog_name="main", schema="silver", table_name="orders")
    base.update(kw)
    return UnityCatalogConfig(**base)


class TestEnsureSchemaExists:
    def test_existing_catalog_and_schema_create_nothing(self):
        spark = _RecordingSpark(catalogs={"main"}, schemas={("main", "silver")})
        UnityCatalogManager({"spark": spark}).ensure_schema_exists("main", "silver")
        assert spark.ddl() == []

    def test_a_missing_schema_is_created_with_its_location(self):
        spark = _RecordingSpark(catalogs={"main"})
        UnityCatalogManager({"spark": spark}).ensure_schema_exists(
            "main", "silver", location="s3://b/it's", managed=True
        )
        assert spark.ddl() == [
            "CREATE SCHEMA IF NOT EXISTS `main`.`silver` MANAGED LOCATION 's3://b/it''s'"
        ]

    def test_a_missing_catalog_is_created_before_the_schema(self):
        spark = _RecordingSpark()
        UnityCatalogManager({"spark": spark}).ensure_schema_exists("main", "silver")
        assert spark.ddl() == [
            "CREATE CATALOG `main`",
            "CREATE SCHEMA IF NOT EXISTS `main`.`silver`",
        ]

    def test_existence_is_asked_once_per_manager(self):
        spark = _RecordingSpark(catalogs={"main"}, schemas={("main", "silver")})
        manager = UnityCatalogManager({"spark": spark})
        manager.ensure_schema_exists("main", "silver")
        manager.ensure_schema_exists("main", "silver")
        assert len(spark.statements) == 2  # one catalog probe, one schema probe

    def test_a_backtick_in_a_name_cannot_close_the_identifier(self):
        spark = _RecordingSpark(catalogs={"main"})
        UnityCatalogManager({"spark": spark}).ensure_schema_exists("main", "a`b")
        [create] = spark.ddl()
        assert create == "CREATE SCHEMA IF NOT EXISTS `main`.`a``b`"

    def test_without_spark_nothing_happens(self):
        UnityCatalogManager({"spark": None}).ensure_schema_exists("main", "silver")


class TestWrites:
    def test_a_managed_table_is_saved_by_name(self):
        df = MagicMock()
        writer = df.write.format.return_value
        writer.mode.return_value = writer
        writer.option.return_value = writer
        UnityCatalogManager({"spark": _RecordingSpark()}).write_managed_table(
            df, "main.silver.orders", _cfg(write_mode="append", overwrite_schema=False)
        )
        df.write.format.assert_called_once_with("delta")
        writer.mode.assert_called_once_with("append")
        writer.option.assert_any_call("overwriteSchema", "false")
        writer.saveAsTable.assert_called_once_with("`main`.`silver`.`orders`")

    def test_an_external_table_is_written_then_registered(self):
        spark = _RecordingSpark()
        factory = MagicMock()
        df = MagicMock()
        UnityCatalogManager({"spark": spark}).write_external_table(
            df, "main.silver.orders", "s3://b/orders", _cfg(), writer_factory=factory
        )
        factory.get_writer.assert_called_once_with("delta")
        written = factory.get_writer.return_value.write.call_args.args
        assert written[0] is df and written[1] == "s3://b/orders"
        assert written[2]["write_mode"] == "overwrite"
        assert spark.ddl() == [
            "CREATE TABLE IF NOT EXISTS `main`.`silver`.`orders` USING DELTA LOCATION 's3://b/orders'"
        ]


class TestPostWriteOperations:
    def test_comment_optimize_of_the_window_and_vacuum(self):
        spark = _RecordingSpark()
        cfg = _cfg(description="Daily orders", partition_col="day", vacuum=True)
        UnityCatalogManager({"spark": spark}).post_write_operations(
            "main.silver.orders", cfg, "2026-01-01", "2026-01-02"
        )
        assert spark.ddl() == [
            "COMMENT ON TABLE `main`.`silver`.`orders` IS 'Daily orders. Partition: day'",
            "OPTIMIZE `main`.`silver`.`orders` WHERE `day` >= '2026-01-01' AND `day` < '2026-01-03'",
            "VACUUM `main`.`silver`.`orders` RETAIN 168 HOURS",
        ]

    def test_vacuum_never_goes_below_the_delta_minimum(self):
        spark = _RecordingSpark()
        UnityCatalogManager({"spark": spark}).post_write_operations(
            "main.silver.orders", _cfg(optimize=False, vacuum_retention_hours=24)
        )
        assert spark.ddl() == ["VACUUM `main`.`silver`.`orders` RETAIN 168 HOURS"]

    def test_no_optimize_without_a_window_or_a_partition_column(self):
        spark = _RecordingSpark()
        manager = UnityCatalogManager({"spark": spark})
        manager.post_write_operations("main.silver.orders", _cfg(partition_col="day"))
        manager.post_write_operations("main.silver.orders", _cfg(), "2026-01-01", "2026-01-02")
        assert not [s for s in spark.ddl() if s.startswith("OPTIMIZE")]

    def test_a_failed_maintenance_step_does_not_fail_the_write(self):
        spark = _RecordingSpark(fail_on=("COMMENT", "OPTIMIZE"))
        cfg = _cfg(description="d", partition_col="day", vacuum=True)
        UnityCatalogManager({"spark": spark}).post_write_operations(
            "main.silver.orders", cfg, "2026-01-01", "2026-01-01"
        )
        assert spark.ddl()[-1] == "VACUUM `main`.`silver`.`orders` RETAIN 168 HOURS"
