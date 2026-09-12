"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
"""

import importlib.util
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - yaml is optional, handled in load()
    yaml = None  # type: ignore

try:
    import tomllib  # type: ignore
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

from ducta.setting.exceptions import ConfigLoadError


class ConfigLoader:
    """Abstract base class for configuration loaders."""

    def can_load(self, source: Union[str, Path]) -> bool:
        raise NotImplementedError

    def load(self, source: Union[str, Path]) -> Dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _validate_safe_path(source: Union[str, Path]) -> Path:
        """Validate that the path is safe and accessible."""
        try:
            path = Path(source).resolve(strict=False)
        except (ValueError, OSError) as e:
            raise ConfigLoadError(f"Invalid path: {source} - {e}") from e

        if ".." in Path(source).parts:
            raise ConfigLoadError(
                f"Path traversal not allowed: {source}. "
                "Relative paths with '..' are forbidden for security."
            )

        if not path.exists():
            raise ConfigLoadError(f"Configuration file not found: {path}")

        if not path.is_file():
            raise ConfigLoadError(f"Path must be a file, not a directory: {path}")

        if not os.access(path, os.R_OK):
            raise ConfigLoadError(f"File not readable (permission denied): {path}")

        return path


class BaseFormatLoader(ConfigLoader):
    """Base class for format-specific loaders with common error handling."""

    FILE_SUFFIXES: tuple = ()
    FORMAT_NAME: str = "Format"

    def can_load(self, source: Union[str, Path]) -> bool:
        if isinstance(source, str):
            source = Path(source)
        return source.suffix.lower() in self.FILE_SUFFIXES

    def load(self, source: Union[str, Path]) -> Dict[str, Any]:
        """Template method for format loading with common error handling."""
        try:
            safe_path = self._validate_safe_path(source)
            return self._load_format(safe_path)
        except ConfigLoadError:
            raise
        except Exception as e:
            raise ConfigLoadError(
                f"Error loading {self.FORMAT_NAME} file {source}: {str(e)}"
            ) from e

    def _load_format(self, safe_path: Path) -> Dict[str, Any]:
        """Override in subclasses to implement format-specific loading."""
        raise NotImplementedError


class YamlConfigLoader(BaseFormatLoader):
    FILE_SUFFIXES = (".yaml", ".yml")
    FORMAT_NAME = "YAML"

    def _load_format(self, safe_path: Path) -> Dict[str, Any]:
        if yaml is None:
            raise ConfigLoadError("PyYAML not installed. Run: pip install PyYAML")
        try:
            with safe_path.open("r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except yaml.YAMLError as e:  # type: ignore
            raise ConfigLoadError(f"Invalid YAML in {safe_path}: {str(e)}") from e


class JsonConfigLoader(BaseFormatLoader):
    FILE_SUFFIXES = (".json",)
    FORMAT_NAME = "JSON"

    def _load_format(self, safe_path: Path) -> Dict[str, Any]:
        try:
            with safe_path.open("r", encoding="utf-8") as file:
                return json.load(file) or {}
        except json.JSONDecodeError as e:
            raise ConfigLoadError(f"Invalid JSON in {safe_path}: {str(e)}") from e


class TomlConfigLoader(BaseFormatLoader):
    """Loader for TOML configuration files with native type safety."""

    FILE_SUFFIXES = (".toml",)
    FORMAT_NAME = "TOML"

    def _load_format(self, safe_path: Path) -> Dict[str, Any]:
        """Load TOML file with proper error handling."""
        if tomllib is None:
            raise ConfigLoadError(
                "TOML support requires 'tomli' package for Python < 3.11. "
                "Install with: pip install tomli"
            )

        try:
            with safe_path.open("rb") as f:
                return tomllib.load(f) or {}
        except Exception as e:
            raise ConfigLoadError(f"Invalid TOML syntax in {safe_path}: {str(e)}") from e


class PythonConfigLoader(BaseFormatLoader):
    FILE_SUFFIXES = (".py",)
    FORMAT_NAME = "Python"

    def _load_format(self, safe_path: Path) -> Dict[str, Any]:
        warnings.warn(
            f"PythonConfigLoader: executing Python file '{safe_path}'. "
            "Python config files run arbitrary code — only load files from "
            "trusted, controlled sources.",
            UserWarning,
            stacklevel=4,
        )
        module = self._load_module(safe_path)
        return self._extract_config(module, safe_path)

    def _load_module(self, path: Path):
        """Load and execute a Python module."""
        module_name = f"ducta_config_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, path)

        if not spec or not spec.loader:
            raise ConfigLoadError(f"Could not load Python module: {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise ConfigLoadError(f"Error executing module {path}: {str(e)}") from e
        finally:
            sys.modules.pop(module_name, None)

        return module

    @staticmethod
    def _extract_config(module, path: Path) -> Dict[str, Any]:
        """Extract config variable from module."""
        if not hasattr(module, "config"):
            raise ConfigLoadError(f"Python module {path} must define 'config' variable")
        if not isinstance(module.config, dict):
            raise ConfigLoadError(f"'config' in {path} must be a dict")
        return module.config


class ConfigLoaderFactory:
    """Factory for creating appropriate configuration loaders."""

    def __init__(self, allow_python: bool = True):
        self._loaders: List[ConfigLoader] = [
            YamlConfigLoader(),
            JsonConfigLoader(),
            TomlConfigLoader(),
        ]

        if allow_python:
            self._loaders.append(PythonConfigLoader())

    def get_loader(self, source: Union[str, Path]) -> ConfigLoader:
        for loader in self._loaders:
            if loader.can_load(source):
                return loader
        raise ConfigLoadError(f"No supported loader for source: {source}")

    def load_config(self, source: Union[str, Dict, Path]) -> Dict[str, Any]:
        if isinstance(source, dict):
            return source

        if isinstance(source, Path):
            return self._load_from_path(source)

        if isinstance(source, str):
            text = source.strip()
            parsed = self._try_parse_inline_text(text)
            if parsed is not None:
                return parsed

            path = Path(source)
            if path.exists():
                return self._load_from_path(path)

        return self.get_loader(source).load(source)

    def _try_parse_inline_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to parse a string as JSON or YAML; return None on failure or if not applicable."""
        if not text:
            return None

        if not text.startswith(("{", "[")):
            return None

        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                return None
            return parsed
        except Exception:
            if yaml is not None:
                try:
                    parsed = yaml.safe_load(text)
                    if not isinstance(parsed, dict):
                        return None
                    return parsed or {}
                except Exception:
                    return None
        return None

    def _load_from_path(self, path: Path) -> Dict[str, Any]:
        """Load configuration from a Path, raising a clear error if missing."""
        if not path.exists():
            raise ConfigLoadError(f"File not found: {path}")
        return self.get_loader(path).load(path)
