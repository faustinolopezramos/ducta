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


class TestAllowedPrefixesValidation:
    """Regression: `"".startswith("")` is always True, so an empty prefix in
    allowed_prefixes made validate_module_path() accept *any* module path
    even in strict_mode — silently defeating the whitelist."""

    def test_empty_string_prefix_is_filtered_out(self):
        imp = SecureModuleImporter(allowed_prefixes=["", "ducta."], strict_mode=True)
        assert imp.validate_module_path("ducta.something") is True
        with pytest.raises(ModuleImportError, match="whitelist"):
            imp.validate_module_path("random_third_party")

    def test_whitespace_only_prefix_is_filtered_out(self):
        imp = SecureModuleImporter(allowed_prefixes=["   ", "ducta."], strict_mode=True)
        with pytest.raises(ModuleImportError, match="whitelist"):
            imp.validate_module_path("random_third_party")

    def test_all_invalid_prefixes_falls_back_to_defaults(self):
        imp = SecureModuleImporter(allowed_prefixes=["", None, "  "], strict_mode=True)
        assert imp.allowed_prefixes == SecureModuleImporter.DEFAULT_ALLOWED_PREFIXES
        assert imp.validate_module_path("ducta.something") is True

    def test_valid_prefixes_are_unaffected(self):
        imp = SecureModuleImporter(allowed_prefixes=["nodes.", "custom."], strict_mode=True)
        assert imp.allowed_prefixes == ["nodes.", "custom."]


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


class TestPrefixesAndTrailingNewline:
    def test_a_prefix_without_a_dot_names_a_package_not_a_string_start(self):
        imp = SecureModuleImporter(allowed_prefixes=["nodes"], strict_mode=True)
        assert imp.validate_module_path("nodes") is True
        assert imp.validate_module_path("nodes.clean") is True
        with pytest.raises(ModuleImportError, match="whitelist"):
            imp.validate_module_path("nodes_evil.x")

    @pytest.mark.parametrize("path", ["nodes.clean\n", "nodes.clean\n\n"])
    def test_a_trailing_newline_is_not_a_valid_module_path(self, path):
        with pytest.raises(ModuleImportError, match="invalid characters"):
            SecureModuleImporter().validate_module_path(path)

    def test_a_trailing_newline_is_not_a_valid_function_name(self):
        with pytest.raises(ModuleImportError, match="Invalid function name"):
            SecureModuleImporter().get_function_from_module("json", "dumps\n")


class TestMissingFunctionMessage:
    """A typo in `run:` listed `Any, Optional` (imports) as available functions
    and gave no suggestion."""

    def test_suggests_the_close_name_and_lists_only_own_functions(self):
        imp = SecureModuleImporter(strict_mode=False)
        with pytest.raises(ModuleImportError) as exc:
            imp.get_function_from_module("json", "detect_encodng")
        message = str(exc.value)
        assert "Did you mean 'detect_encoding'?" in message
        assert "JSONDecoder" not in message  # imported into json, not defined as a function
