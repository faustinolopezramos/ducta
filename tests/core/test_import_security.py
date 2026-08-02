"""Unit tests for ducta.core.import_security.SecureModuleImporter."""

from __future__ import annotations

import pytest

from ducta.core.import_security import ModuleImportError, SecureModuleImporter


class TestValidateModulePath:
    def setup_method(self):
        self.imp = SecureModuleImporter()

    def test_valid_path(self):
        assert self.imp.validate_module_path("ducta.core.utils") is True

    def test_empty_raises(self):
        with pytest.raises(ModuleImportError):
            self.imp.validate_module_path("   ")

    def test_too_long_raises(self):
        with pytest.raises(ModuleImportError, match="maximum length"):
            self.imp.validate_module_path("a" * 300)

    def test_parent_traversal_forbidden(self):
        with pytest.raises(ModuleImportError, match="forbidden pattern"):
            self.imp.validate_module_path("..evil")

    def test_absolute_path_forbidden(self):
        with pytest.raises(ModuleImportError, match="forbidden pattern"):
            self.imp.validate_module_path("/etc/passwd")

    def test_invalid_characters(self):
        with pytest.raises(ModuleImportError, match="invalid characters"):
            self.imp.validate_module_path("bad-name!")

    def test_dunder_import_forbidden(self):
        with pytest.raises(ModuleImportError, match="forbidden pattern"):
            self.imp.validate_module_path("__import__")


class TestStrictMode:
    def test_default_is_strict(self):
        imp = SecureModuleImporter()
        with pytest.raises(ModuleImportError, match="whitelist"):
            imp.validate_module_path("random_third_party")

    def test_strict_rejects_non_whitelisted(self):
        imp = SecureModuleImporter(strict_mode=True)
        with pytest.raises(ModuleImportError, match="whitelist"):
            imp.validate_module_path("random_third_party")

    def test_strict_allows_whitelisted_prefix(self):
        imp = SecureModuleImporter(strict_mode=True)
        assert imp.validate_module_path("ducta.something") is True

    def test_non_strict_allows_any_valid_name(self):
        imp = SecureModuleImporter(strict_mode=False)
        assert imp.validate_module_path("some_module.sub") is True


class TestGetFunctionFromModule:
    def setup_method(self):
        # Exercises function-loading behavior (not whitelist enforcement, which
        # TestStrictMode covers), so use a non-strict importer against stdlib "json".
        self.imp = SecureModuleImporter(strict_mode=False)

    def test_loads_real_function(self):
        fn = self.imp.get_function_from_module("json", "dumps")
        assert callable(fn)
        assert fn({"a": 1}) == '{"a": 1}'

    def test_invalid_function_name(self):
        with pytest.raises(ModuleImportError, match="Invalid function name"):
            self.imp.get_function_from_module("json", "123bad")

    def test_missing_function(self):
        with pytest.raises(ModuleImportError, match="not found"):
            self.imp.get_function_from_module("json", "no_such_function")

    def test_cache_reuses_module(self):
        self.imp.import_module("json")
        info = self.imp.get_cache_info()
        assert info["cached_modules"] >= 1
