import os
from unittest.mock import patch

import pytest

from ducta.setting.exceptions import ConfigLoadError
from ducta.setting.interpolator import VariableInterpolator


class TestInterpolate:
    def test_no_variables(self):
        assert VariableInterpolator.interpolate("hello", {}) == "hello"

    def test_simple_variable(self):
        assert VariableInterpolator.interpolate("${name}", {"name": "world"}) == "world"

    def test_variable_in_string(self):
        assert VariableInterpolator.interpolate("hello ${name}", {"name": "world"}) == "hello world"

    def test_multiple_variables(self):
        result = VariableInterpolator.interpolate("${a} ${b}", {"a": "x", "b": "y"})
        assert result == "x y"

    def test_env_var_takes_precedence(self):
        with patch.dict(os.environ, {"MY_VAR": "env_value"}, clear=True):
            result = VariableInterpolator.interpolate("${MY_VAR}", {"MY_VAR": "config_value"})
            assert result == "env_value"

    def test_non_string_returns_unchanged(self):
        assert VariableInterpolator.interpolate(123, {}) == 123
        assert VariableInterpolator.interpolate(None, {}) is None

    def test_empty_string(self):
        assert VariableInterpolator.interpolate("", {}) == ""

    def test_variable_not_found_keeps_placeholder(self):
        result = VariableInterpolator.interpolate("${missing}", {})
        assert result == "${missing}"

    def test_recursive_interpolation(self):
        result = VariableInterpolator.interpolate("${a}", {"a": "${b}", "b": "final_value"})
        assert result == "final_value"

    def test_max_depth_exceeded(self):
        with pytest.raises(ConfigLoadError, match="Maximum interpolation depth exceeded"):
            VariableInterpolator.interpolate("${a}", {"a": "${a}"}, _depth=10)

    def test_sensitive_var_name_rejected_even_if_set(self):
        """Regression: `${VAR}` interpolated ANY set environment variable with
        no restriction — a config value of `${AWS_SECRET_ACCESS_KEY}` would
        embed the real secret into a config file, which can end up logged or
        persisted (e.g. alongside a run certificate) far more widely than the
        environment itself."""
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "s3cr3t"}, clear=True):
            with pytest.raises(ConfigLoadError, match="Refusing to interpolate"):
                VariableInterpolator.interpolate("${AWS_SECRET_ACCESS_KEY}", {})

    def test_sensitive_var_name_rejected_even_if_unset(self):
        # The name alone is enough to reject — must not depend on it resolving.
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigLoadError, match="Refusing to interpolate"):
                VariableInterpolator.interpolate("${API_TOKEN}", {})

    @pytest.mark.parametrize(
        "var_name",
        ["DB_PASSWORD", "MY_SECRET", "GITHUB_TOKEN", "AWS_ACCESS_KEY_ID", "SERVICE_CREDENTIAL"],
    )
    def test_various_sensitive_patterns_rejected(self, var_name):
        with patch.dict(os.environ, {var_name: "x"}, clear=True):
            with pytest.raises(ConfigLoadError, match="Refusing to interpolate"):
                VariableInterpolator.interpolate("${" + var_name + "}", {})

    def test_ordinary_var_names_still_interpolate(self):
        # Must not false-positive on ordinary path/config variable names.
        with patch.dict(os.environ, {"DATA_ROOT": "/data"}, clear=True):
            assert VariableInterpolator.interpolate("${DATA_ROOT}/bronze", {}) == "/data/bronze"

    def test_max_iterations_env(self):
        deep_string = "${A}" * 200
        with patch.dict(os.environ, {"A": "x"}, clear=True):
            with pytest.raises(ConfigLoadError, match="Maximum interpolation iterations exceeded"):
                VariableInterpolator.interpolate(deep_string, {})


class TestInterpolateStructure:
    def test_string_value(self):
        result = VariableInterpolator.interpolate_structure("prefix_${var}", {"var": "suffix"})
        assert result == "prefix_suffix"

    def test_dict_inplace(self):
        d = {"path": "${base}/data", "other": "static"}
        VariableInterpolator.interpolate_structure(d, {"base": "/root"})
        assert d["path"] == "/root/data"

    def test_dict_copy(self):
        d = {"path": "${base}/data"}
        result = VariableInterpolator.interpolate_structure(d, {"base": "/root"}, copy=True)
        assert result["path"] == "/root/data"
        assert result is not d

    def test_list_inplace(self):
        lst = ["${a}", "${b}"]
        VariableInterpolator.interpolate_structure(lst, {"a": "x", "b": "y"})
        assert lst == ["x", "y"]

    def test_list_copy(self):
        lst = ["${a}"]
        result = VariableInterpolator.interpolate_structure(lst, {"a": "x"}, copy=True)
        assert result == ["x"]
        assert result is not lst

    def test_nested_dict(self):
        d = {"level1": {"level2": "${var}"}}
        VariableInterpolator.interpolate_structure(d, {"var": "val"})
        assert d["level1"]["level2"] == "val"

    def test_non_string_non_container(self):
        assert VariableInterpolator.interpolate_structure(42, {}) == 42

    def test_max_depth_exceeded(self):
        nested = []
        current = nested
        for _ in range(15):
            current.append([])
            current = current[0]
        current.append("${x}")
        with pytest.raises(ConfigLoadError, match="Maximum structure depth exceeded"):
            VariableInterpolator.interpolate_structure(nested, {"x": "y"})


class TestInterpolateConfigPaths:
    def test_default_keys_filepath(self):
        config = {"filepath": "${base}/data", "other": "static"}
        VariableInterpolator.interpolate_config_paths(config, {"base": "/root"})
        assert config["filepath"] == "/root/data"

    def test_default_keys_skips_other_keys(self):
        config = {"not_filepath": "${base}/data"}
        VariableInterpolator.interpolate_config_paths(config, {"base": "/root"})
        assert config["not_filepath"] == "${base}/data"

    def test_custom_keys(self):
        config = {"path": "${base}/path", "checkpoint_location": "${base}/cp"}
        VariableInterpolator.interpolate_config_paths(
            config, {"base": "/root"}, keys=frozenset({"path", "checkpoint_location"})
        )
        assert config["path"] == "/root/path"
        assert config["checkpoint_location"] == "/root/cp"

    def test_nested_dicts(self):
        config = {"nested": {"filepath": "${base}/data"}}
        VariableInterpolator.interpolate_config_paths(config, {"base": "/root"})
        assert config["nested"]["filepath"] == "/root/data"

    def test_list_of_dicts(self):
        config = {"inputs": [{"filepath": "${base}/a"}, {"filepath": "${base}/b"}]}
        VariableInterpolator.interpolate_config_paths(config, {"base": "/root"})
        assert config["inputs"][0]["filepath"] == "/root/a"
        assert config["inputs"][1]["filepath"] == "/root/b"

    def test_non_string_values_unaffected(self):
        config = {"filepath": 123}
        VariableInterpolator.interpolate_config_paths(config, {})
        assert config["filepath"] == 123


class TestSensitiveNameMatchingIsPerComponent:
    """The credential guard must not reject names that merely contain a token.

    It was a substring search (`re.search(r"(KEY|SECRET|...)")`), so it also
    refused `${MONKEY_DIR}`, `${TOKENIZER_PATH}` and `${KEYSTONE_ROOT}` — none of
    which is a credential by any reading. Matching per `_`/`-`/`.` component
    keeps every real case rejected.
    """

    @pytest.mark.parametrize(
        "var_name",
        ["MONKEY_DIR", "TOKENIZER_PATH", "KEYSTONE_ROOT", "PASSWORDLESS_MODE", "TURNKEY_BUILD"],
    )
    def test_a_name_that_merely_contains_a_token_still_interpolates(self, var_name, monkeypatch):
        monkeypatch.setenv(var_name, "/data")
        assert VariableInterpolator.interpolate(f"${{{var_name}}}/out", {}) == "/data/out"

    @pytest.mark.parametrize(
        "var_name",
        [
            "AWS_SECRET_ACCESS_KEY",
            "DB_PASSWORD",
            "GITHUB_TOKEN",
            "SERVICE_CREDENTIAL",
            "api-key",
            "app.secret",
            "TOKEN",
        ],
    )
    def test_a_real_credential_name_is_still_refused(self, var_name, monkeypatch):
        monkeypatch.setenv(var_name, "hunter2")
        with pytest.raises(ConfigLoadError):
            VariableInterpolator.interpolate(f"${{{var_name}}}", {})
