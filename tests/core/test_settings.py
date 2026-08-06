"""CoreSettings: one resolution point for everything ducta.core reads.

These cover the defects the scattered-`getattr` shape kept producing: a key read
with different defaults in different places, a boolean-looking string silently
evaluating true, a timeout clamped in one path but not another, and an
environment name derived by three subtly different precedence orders.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.core.settings import (
    DEFAULT_EXECUTION_TIMEOUT_SECONDS,
    DEFAULT_MAX_PARALLEL_NODES,
    DEFAULT_NODE_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    CoreSettings,
    clamp_timeout,
    coerce_bool,
    coerce_int,
)


def _ctx(global_settings=None, **attrs):
    return SimpleNamespace(global_settings=global_settings or {}, **attrs)


class TestCoerceBool:
    @pytest.mark.parametrize("raw", ["true", "TRUE", " yes ", "on", "1", True, 1])
    def test_truthy_spellings(self, raw):
        assert coerce_bool("k", raw, default=False) is True

    @pytest.mark.parametrize("raw", ["false", "FALSE", " no ", "off", "0", "", False, 0])
    def test_falsy_spellings(self, raw):
        assert coerce_bool("k", raw, default=True) is False

    def test_the_string_false_is_not_true(self):
        # bool("false") is True in Python — the exact way a disabled feature
        # stayed enabled with no warning.
        assert coerce_bool("k", "false", default=True) is False

    def test_unrecognized_value_falls_back_to_default(self):
        assert coerce_bool("k", "maybe", default=True) is True
        assert coerce_bool("k", "maybe", default=False) is False

    def test_none_uses_the_default(self):
        assert coerce_bool("k", None, default=True) is True


class TestCoerceInt:
    def test_numeric_strings_are_accepted(self):
        assert coerce_int("k", "8", default=4) == 8

    def test_garbage_falls_back_to_default(self):
        assert coerce_int("k", "eight", default=4) == 4

    def test_none_uses_the_default(self):
        assert coerce_int("k", None, default=4) == 4

    def test_below_minimum_is_raised_to_the_minimum(self):
        assert coerce_int("k", 0, default=4, minimum=1) == 1
        assert coerce_int("k", -5, default=4, minimum=1) == 1


class TestClampTimeout:
    def test_values_within_the_ceiling_pass_through(self):
        assert clamp_timeout("k", 3600) == 3600

    def test_values_above_the_ceiling_are_clamped(self):
        assert clamp_timeout("k", 999_999_999) == MAX_TIMEOUT_SECONDS


class TestDefaults:
    def test_empty_config_yields_documented_defaults(self):
        s = CoreSettings.from_context(_ctx())

        assert s.max_parallel_nodes == DEFAULT_MAX_PARALLEL_NODES
        assert s.execution_timeout_seconds == DEFAULT_EXECUTION_TIMEOUT_SECONDS
        assert s.node_timeout_seconds == DEFAULT_NODE_TIMEOUT_SECONDS
        assert s.preflight_enabled is True
        assert s.strict_module_import is True
        assert s.mlops_enabled is True
        assert s.mlops_required is False
        assert s.enable_run_certificate is True

    def test_missing_context_attributes_do_not_raise(self):
        assert CoreSettings.from_context(object()).max_parallel_nodes == DEFAULT_MAX_PARALLEL_NODES

    def test_a_bare_settings_dict_is_accepted(self):
        s = CoreSettings.from_context({"max_parallel_nodes": 9})
        assert s.max_parallel_nodes == 9


class TestTimeoutClamping:
    def test_both_timeouts_share_one_ceiling(self):
        # These used to be clamped by two independent literals, one of them
        # copied into NodeExecutor "to avoid a circular import".
        s = CoreSettings.from_context(
            _ctx({"execution_timeout_seconds": 10**9, "node_timeout_seconds": 10**9})
        )

        assert s.execution_timeout_seconds == MAX_TIMEOUT_SECONDS
        assert s.node_timeout_seconds == MAX_TIMEOUT_SECONDS


class TestEnvResolution:
    def test_context_env_wins(self):
        s = CoreSettings.from_context(_ctx({"env": "from_gs"}, env="from_ctx"))
        assert s.env == "from_ctx"

    def test_falls_back_to_global_settings_env(self):
        assert CoreSettings.from_context(_ctx({"env": "dev"})).env == "dev"

    def test_falls_back_to_environment_key(self):
        assert CoreSettings.from_context(_ctx({"environment": "prod"})).env == "prod"

    def test_env_key_beats_environment_key(self):
        s = CoreSettings.from_context(_ctx({"env": "dev", "environment": "prod"}))
        assert s.env == "dev"

    def test_absent_everywhere_is_none(self):
        assert CoreSettings.from_context(_ctx()).env is None

    def test_blank_values_are_treated_as_absent(self):
        s = CoreSettings.from_context(_ctx({"env": "   ", "environment": "prod"}))
        assert s.env == "prod"


class TestNestedSections:
    def test_mlflow_enabled_reads_the_nested_section(self):
        assert CoreSettings.from_context(_ctx({"mlflow": {"enabled": True}})).mlflow_enabled is True

    def test_nested_mlops_enabled_overrides_the_flat_flag(self):
        s = CoreSettings.from_context(_ctx({"mlops_enabled": True, "mlops": {"enabled": False}}))
        assert s.mlops_enabled is False

    def test_flat_flag_applies_when_the_nested_one_is_absent(self):
        s = CoreSettings.from_context(_ctx({"mlops_enabled": False, "mlops": {}}))
        assert s.mlops_enabled is False

    def test_chain_section_is_read(self):
        s = CoreSettings.from_context(
            _ctx({"chain": {"reuse_materialized": True, "staleness_check": "yes"}})
        )
        assert s.chain_reuse_materialized is True
        assert s.chain_staleness_check is True

    def test_malformed_section_degrades_to_empty(self):
        s = CoreSettings.from_context(_ctx({"quality": "not-a-mapping"}))
        assert s.quality == {}


class TestStrictModuleImport:
    def test_context_attribute_overrides_the_setting(self):
        s = CoreSettings.from_context(
            _ctx({"strict_module_import": True}, strict_module_import=False)
        )
        assert s.strict_module_import is False

    def test_setting_applies_when_no_attribute_is_present(self):
        assert (
            CoreSettings.from_context(_ctx({"strict_module_import": False})).strict_module_import
            is False
        )


class TestImmutability:
    def test_settings_cannot_be_mutated_mid_run(self):
        s = CoreSettings.from_context(_ctx())
        with pytest.raises(Exception):
            s.max_parallel_nodes = 99

    def test_to_dict_round_trips_every_field(self):
        s = CoreSettings.from_context(_ctx({"max_parallel_nodes": 7}))
        assert s.to_dict()["max_parallel_nodes"] == 7
