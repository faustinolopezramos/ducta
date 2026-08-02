import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.setting.exceptions import ConfigLoadError
from ducta.setting.loaders import (
    BaseFormatLoader,
    ConfigLoader,
    ConfigLoaderFactory,
    JsonConfigLoader,
    PythonConfigLoader,
    TomlConfigLoader,
    YamlConfigLoader,
)


class TestBaseClass:
    def test_abstract_can_load_raises(self):
        with pytest.raises(NotImplementedError):
            ConfigLoader().can_load("x")

    def test_abstract_load_raises(self):
        with pytest.raises(NotImplementedError):
            ConfigLoader().load("x")

    def test_validate_safe_path_resolves(self, temp_dir):
        f = temp_dir / "test.yaml"
        f.touch()
        assert ConfigLoader._validate_safe_path(str(f)) == f.resolve()

    def test_validate_safe_path_not_found(self):
        with pytest.raises(ConfigLoadError, match="not found"):
            ConfigLoader._validate_safe_path("/nonexistent/file.yaml")

    def test_validate_safe_path_traversal(self):
        with pytest.raises(ConfigLoadError, match="Path traversal"):
            ConfigLoader._validate_safe_path("/safe/../etc/passwd")

    def test_validate_safe_path_directory(self, temp_dir):
        with pytest.raises(ConfigLoadError, match="must be a file"):
            ConfigLoader._validate_safe_path(str(temp_dir))

    def test_validate_safe_path_unreadable(self, temp_dir):
        f = temp_dir / "test.txt"
        f.write_text("hello")
        with patch("os.access", return_value=False):
            with pytest.raises(ConfigLoadError, match="permission denied"):
                ConfigLoader._validate_safe_path(str(f))


class TestBaseFormatLoader:
    def test_can_load_by_suffix(self, temp_dir):
        loader = YamlConfigLoader()
        path = temp_dir / "cfg.yaml"
        assert loader.can_load(path) is True
        assert loader.can_load(temp_dir / "cfg.yml") is True
        assert loader.can_load(temp_dir / "cfg.json") is False

    def test_load_delegates_to_format(self, temp_dir):
        loader = YamlConfigLoader()
        f = temp_dir / "cfg.yaml"
        f.write_text("key: value\n")
        result = loader.load(str(f))
        assert result == {"key": "value"}

    def test_load_raises_on_missing_file(self):
        loader = YamlConfigLoader()
        with pytest.raises(ConfigLoadError, match="not found"):
            loader.load("/no/such/file.yaml")


class TestYamlConfigLoader:
    def test_load_valid_yaml(self, temp_dir):
        f = temp_dir / "cfg.yaml"
        f.write_text("a: 1\nb: two\n")
        result = YamlConfigLoader().load(str(f))
        assert result == {"a": 1, "b": "two"}

    def test_load_empty_file_returns_empty_dict(self, temp_dir):
        f = temp_dir / "empty.yaml"
        f.write_text("")
        result = YamlConfigLoader().load(str(f))
        assert result == {}

    def test_load_invalid_yaml(self, temp_dir):
        f = temp_dir / "bad.yaml"
        f.write_text("{{invalid}}")
        with pytest.raises(ConfigLoadError, match="Invalid YAML"):
            YamlConfigLoader().load(str(f))


class TestJsonConfigLoader:
    def test_load_valid_json(self, temp_dir):
        f = temp_dir / "cfg.json"
        f.write_text('{"a": 1, "b": "two"}')
        result = JsonConfigLoader().load(str(f))
        assert result == {"a": 1, "b": "two"}

    def test_load_empty_json(self, temp_dir):
        f = temp_dir / "empty.json"
        f.write_text("{}")
        result = JsonConfigLoader().load(str(f))
        assert result == {}

    def test_load_invalid_json(self, temp_dir):
        f = temp_dir / "bad.json"
        f.write_text("{invalid}")
        with pytest.raises(ConfigLoadError, match="Invalid JSON"):
            JsonConfigLoader().load(str(f))


class TestTomlConfigLoader:
    def test_load_valid_toml(self, temp_dir):
        f = temp_dir / "cfg.toml"
        f.write_text('key = "value"\nnum = 42\n')
        result = TomlConfigLoader().load(str(f))
        assert result == {"key": "value", "num": 42}

    def test_load_invalid_toml(self, temp_dir):
        f = temp_dir / "bad.toml"
        f.write_text("key = \n")
        with pytest.raises(ConfigLoadError, match="Invalid TOML"):
            TomlConfigLoader().load(str(f))


class TestPythonConfigLoader:
    def test_load_valid_python(self, temp_dir):
        f = temp_dir / "cfg.py"
        f.write_text("config = {'a': 1, 'b': 'two'}\n")
        result = PythonConfigLoader().load(str(f))
        assert result == {"a": 1, "b": "two"}

    def test_no_config_var(self, temp_dir):
        f = temp_dir / "cfg.py"
        f.write_text("x = 1\n")
        with pytest.raises(ConfigLoadError, match="must define 'config'"):
            PythonConfigLoader().load(str(f))

    def test_config_not_dict(self, temp_dir):
        f = temp_dir / "cfg.py"
        f.write_text("config = 'not a dict'\n")
        with pytest.raises(ConfigLoadError, match="must be a dict"):
            PythonConfigLoader().load(str(f))

    def test_load_module_error(self, temp_dir):
        f = temp_dir / "cfg.py"
        f.write_text("raise ValueError('bad')\n")
        with pytest.raises(ConfigLoadError, match="Error executing module"):
            PythonConfigLoader().load(str(f))


class TestConfigLoaderFactory:
    def test_get_loader_yaml(self, temp_dir):
        factory = ConfigLoaderFactory()
        path = temp_dir / "cfg.yaml"
        loader = factory.get_loader(str(path))
        assert isinstance(loader, YamlConfigLoader)

    def test_get_loader_json(self, temp_dir):
        factory = ConfigLoaderFactory()
        path = temp_dir / "cfg.json"
        loader = factory.get_loader(str(path))
        assert isinstance(loader, JsonConfigLoader)

    def test_get_loader_toml(self, temp_dir):
        factory = ConfigLoaderFactory()
        path = temp_dir / "cfg.toml"
        loader = factory.get_loader(str(path))
        assert isinstance(loader, TomlConfigLoader)

    def test_get_loader_python(self, temp_dir):
        factory = ConfigLoaderFactory()
        path = temp_dir / "cfg.py"
        loader = factory.get_loader(str(path))
        assert isinstance(loader, PythonConfigLoader)

    def test_get_loader_unsupported(self):
        factory = ConfigLoaderFactory()
        with pytest.raises(ConfigLoadError, match="No supported loader"):
            factory.get_loader("file.xyz")

    def test_load_config_from_dict(self):
        factory = ConfigLoaderFactory()
        result = factory.load_config({"a": 1})
        assert result == {"a": 1}

    def test_load_config_from_path(self, temp_dir):
        factory = ConfigLoaderFactory()
        f = temp_dir / "cfg.yaml"
        f.write_text("key: val\n")
        result = factory.load_config(str(f))
        assert result == {"key": "val"}

    def test_load_config_inline_json(self):
        factory = ConfigLoaderFactory()
        result = factory.load_config('{"a": 1}')
        assert result == {"a": 1}

    def test_load_config_inline_yaml_fallback(self):
        factory = ConfigLoaderFactory()
        result = factory.load_config("{a: 1, b: two}")
        assert result == {"a": 1, "b": "two"}

    def test_load_config_file_not_found(self, temp_dir):
        factory = ConfigLoaderFactory()
        with pytest.raises(ConfigLoadError, match="Configuration file not found"):
            factory.load_config(str(temp_dir / "nonexistent.yaml"))

    def test_load_config_from_path_object(self, temp_dir):
        factory = ConfigLoaderFactory()
        f = temp_dir / "cfg.yaml"
        f.write_text("key: val\n")
        result = factory.load_config(Path(str(f)))
        assert result == {"key": "val"}

    def test_try_parse_inline_json_array_returns_none(self):
        factory = ConfigLoaderFactory()
        assert factory._try_parse_inline_text("[1, 2, 3]") is None

    def test_try_parse_empty_text(self):
        factory = ConfigLoaderFactory()
        assert factory._try_parse_inline_text("") is None

    def test_try_parse_non_json_object_returns_none(self):
        factory = ConfigLoaderFactory()
        assert factory._try_parse_inline_text("hello") is None


class TestConfigLoaderFactoryAllowPython:
    """Regression: `allow_python=False` must keep `PythonConfigLoader` out of
    the resolver entirely, so a `.py` config hits the generic "No supported
    loader" error instead of being executed. Needed on any path reachable from
    workspace/repo content the caller didn't write (see api/workspace/manager.py
    and api/workspace/loaders.py, which now construct the factory this way)."""

    def test_default_still_allows_python(self, temp_dir):
        factory = ConfigLoaderFactory()
        loader = factory.get_loader(str(temp_dir / "cfg.py"))
        assert isinstance(loader, PythonConfigLoader)

    def test_disallowed_python_file_has_no_loader(self, temp_dir):
        factory = ConfigLoaderFactory(allow_python=False)
        with pytest.raises(ConfigLoadError, match="No supported loader"):
            factory.get_loader(str(temp_dir / "cfg.py"))

    def test_disallowed_python_other_formats_still_work(self, temp_dir):
        factory = ConfigLoaderFactory(allow_python=False)
        f = temp_dir / "cfg.yaml"
        f.write_text("key: val\n")
        assert factory.load_config(str(f)) == {"key": "val"}

    def test_disallowed_python_load_config_raises_instead_of_executing(self, temp_dir):
        f = temp_dir / "evil.py"
        f.write_text("import sys\nconfig = {'pwned': True}\n")
        factory = ConfigLoaderFactory(allow_python=False)
        with pytest.raises(ConfigLoadError, match="No supported loader"):
            factory.load_config(str(f))
