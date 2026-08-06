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

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.console.core import (
    ConfigCache,
    ConfigFormat,
    ConfigurationError,
    SecurityError,
    SecurityValidator,
    get_base_environment,
    is_allowed_environment,
    is_sandbox_environment,
    normalize_environment,
)


def load_config_file(file_path: str) -> Dict[str, Any]:
    """Load configuration from file, auto-detecting format by extension.

    Supports .yaml, .yml (YAML), .json (JSON), .toml (TOML).
    """
    if not Path(file_path).exists():
        raise ConfigurationError(f"File not found: {file_path}")

    suffix = Path(file_path).suffix.lower()

    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise ConfigurationError("PyYAML not installed. Run: pip install PyYAML")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config or {}
        except Exception as e:
            raise ConfigurationError(f"Invalid YAML in {file_path}: {e}")

    elif suffix == ".json":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in {file_path}: {e}")

    elif suffix == ".toml":
        try:
            import tomllib  # type: ignore  # Python >= 3.11
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore  # Python < 3.11
            except ImportError:
                raise ConfigurationError(
                    "TOML support requires 'tomli' for Python < 3.11. "
                    "Install with: pip install tomli"
                )
        try:
            with open(file_path, "rb") as f:
                return tomllib.load(f) or {}
        except Exception as e:
            raise ConfigurationError(f"Invalid TOML in {file_path}: {e}")

    else:
        raise ConfigurationError(f"Unsupported format: {suffix}. Use .yaml, .yml, .json, or .toml")


class ConfigDiscovery:
    CONFIG_PATTERNS = [
        "environment.yml",
        "environment.yaml",
        "environment.toml",
        "environment.json",
        "settings.yaml",
        "settings.yml",
        "settings.toml",
        "settings.json",
        "settings_yaml.json",
        "settings_json.json",
        "settings_toml.json",
        "config.json",
    ]
    _SCORE_LAYER_MATCH = 30
    _SCORE_USE_CASE_MATCH = 40
    _SCORE_CONFIG_TYPE_MATCH = 20
    _SCORE_DEPTH_MAX_BONUS = 10

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.discovered_configs: List[Tuple[Path, str]] = []

    def discover(self, max_depth: int = 3) -> List[Tuple[Path, str]]:
        cache_key = f"{self.base_path}:{max_depth}"
        cached = ConfigCache.get(cache_key)
        if cached:
            self.discovered_configs = cached
            return cached
        self.discovered_configs = []
        try:
            self._search_recursive(self.base_path, 0, max_depth)
        except Exception as e:
            logger.warning("Error during config discovery: {}", e)
        ConfigCache.set(cache_key, self.discovered_configs)
        return self.discovered_configs

    def _search_recursive(self, path: Path, depth: int, max_depth: int) -> None:
        if depth > max_depth or not path.is_dir():
            return
        try:
            for pattern in self.CONFIG_PATTERNS:
                if (path / pattern).is_file():
                    self.discovered_configs.append((path, pattern))
                    break
            for item in path.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    self._search_recursive(item, depth + 1, max_depth)
        except OSError:
            pass

    def find_best_match(
        self,
        layer_name: Optional[str] = None,
        use_case: Optional[str] = None,
        config_type: Optional[str] = None,
    ) -> Optional[Tuple[Path, str]]:
        if not self.discovered_configs:
            self.discover()
        if not self.discovered_configs:
            return None
        scored = []
        for config_dir, config_file in self.discovered_configs:
            score = 0
            if layer_name and layer_name.lower() in config_dir.as_posix().lower():
                score += self._SCORE_LAYER_MATCH
            if use_case and use_case.lower() in config_dir.as_posix().lower():
                score += self._SCORE_USE_CASE_MATCH
            if config_type:
                config_type_lower = config_type.lower().lstrip(".")
                if config_file.endswith(f".{config_type_lower}"):
                    score += self._SCORE_CONFIG_TYPE_MATCH
                elif config_file == f"settings_{config_type_lower}.json":
                    score += self._SCORE_CONFIG_TYPE_MATCH
            score += max(0, self._SCORE_DEPTH_MAX_BONUS - len(config_dir.parts))
            scored.append((score, config_dir, config_file))
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0]
        return (best[1], best[2])

    def list_all(self) -> None:
        if not self.discovered_configs:
            self.discover()
        if not self.discovered_configs:
            logger.warning("No configurations found")
            return
        for i, (config_dir, config_file) in enumerate(self.discovered_configs, 1):
            logger.info("  {}. {}", i, config_dir / config_file)

    def select_interactive(self) -> Optional[Tuple[Path, str]]:
        if not self.discovered_configs:
            self.discover()
        if not self.discovered_configs:
            return None
        if len(self.discovered_configs) == 1:
            return self.discovered_configs[0]
        self.list_all()
        try:
            while True:
                choice = input(f"Select configuration (1-{len(self.discovered_configs)}): ").strip()
                if choice.isdigit():
                    index = int(choice) - 1
                    if 0 <= index < len(self.discovered_configs):
                        return self.discovered_configs[index]
                print("Invalid selection. Try again.")
        except (KeyboardInterrupt, EOFError):
            return None


class ConfigManager:
    CONFIG_FILES = {
        ConfigFormat.YAML: "environment.yaml",
        ConfigFormat.JSON: "settings.json",
    }

    def __init__(
        self,
        base_path: Optional[str] = None,
        layer_name: Optional[str] = None,
        use_case: Optional[str] = None,
        config_type: Optional[str] = None,
        interactive: bool = False,
        require_config: bool = True,
    ):
        self.original_cwd = Path.cwd()
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.discovery = ConfigDiscovery(str(self.base_path))
        self.active_config_dir: Optional[Path] = None
        self.active_config_file: Optional[str] = None
        self.active_format: Optional[ConfigFormat] = None
        # When False, a missing canonical root is tolerated (active_* stay None)
        # so callers can fall back to flexible config-form resolution instead of
        # erroring. Defaults to True to preserve strict behavior for all other
        # call sites.
        self.require_config = require_config
        self._initialize_config(layer_name, use_case, config_type, interactive)

    def _initialize_config(self, layer_name, use_case, config_type, interactive) -> None:
        try:
            self._discover_config(layer_name, use_case, config_type, interactive)
        except ConfigurationError:
            try:
                self._fallback_config_detection()
            except ConfigurationError:
                if self.require_config:
                    raise
                logger.debug(
                    "No canonical config root found under {}; deferring to "
                    "flexible config-form resolution",
                    self.base_path,
                )

    def _discover_config(self, layer_name, use_case, config_type, interactive) -> None:
        config_location = (
            self.discovery.select_interactive()
            if interactive
            else self.discovery.find_best_match(layer_name, use_case, config_type)
        )
        if not config_location:
            discovered = self.discovery.discover()
            if discovered:
                config_location = discovered[0]
        if not config_location:
            raise ConfigurationError("No configuration files found")
        self.active_config_dir, self.active_config_file = config_location
        self.active_config_dir = self.active_config_dir.resolve()
        self._detect_format_from_filename(self.active_config_file)

    def _fallback_config_detection(self) -> None:
        available = [
            (fmt, fn) for fmt, fn in self.CONFIG_FILES.items() if (self.base_path / fn).exists()
        ]
        if not available:
            raise ConfigurationError(
                f"No config found. Expected one of: {list(self.CONFIG_FILES.values())}"
            )
        if len(available) > 1:
            raise ConfigurationError(f"Multiple configs found: {[f[1] for f in available]}")
        self.active_format, self.active_config_file = available[0]
        self.active_config_dir = self.base_path

    def _detect_format_from_filename(self, filename: str) -> None:
        _map = {
            "yml": ConfigFormat.YAML,
            "yaml": ConfigFormat.YAML,
            "json": ConfigFormat.JSON,
            "toml": ConfigFormat.TOML,
        }
        suffix = filename.lower().rsplit(".", 1)[-1]
        self.active_format = _map.get(suffix, ConfigFormat.YAML)

    def get_active_format(self) -> ConfigFormat:
        if not self.active_format:
            raise ConfigurationError("No active configuration format")
        return self.active_format

    def get_config_file_path(self) -> str:
        if not self.active_config_dir or not self.active_config_file:
            raise ConfigurationError("No active configuration file")
        return str((self.active_config_dir / self.active_config_file).resolve())

    def get_config_directory(self) -> Path:
        if not self.active_config_dir:
            if not self.require_config:
                # No canonical root: a flexible config form (bundle / directory
                # convention / quickstart) resolved the project instead. Fall
                # back to base_path — the same directory FlexibleConfigResolver
                # searched — so callers (module resolution, PipelineExecutor)
                # get a sensible project directory instead of an error.
                return self.base_path
            raise ConfigurationError("No active configuration directory")
        return self.active_config_dir

    def load_config(self) -> Dict[str, Any]:
        return load_config_file(self.get_config_file_path())

    def change_to_config_directory(self) -> None:
        if self.active_config_dir and self.active_config_dir != self.original_cwd:
            try:
                # Confine against self.base_path (the explicit --base-path,
                # or cwd if unset) — not original_cwd, the directory the CLI
                # happened to be launched from. `ducta start --base-path
                # /some/project` from an unrelated launch directory is a
                # normal, legitimate usage; checking against original_cwd
                # instead of the intended project root either rejects that
                # valid case or fails to actually confine to it.
                os.chdir(SecurityValidator.validate_path(self.base_path, self.active_config_dir))
            except SecurityError as e:
                raise ConfigurationError(f"Failed to change directory: {e}")

    def restore_original_directory(self) -> None:
        try:
            os.chdir(self.original_cwd)
        except OSError:
            pass

    @classmethod
    def from_layer_config(cls, layer_context: Dict[str, str]) -> "ConfigManager":
        """Create ConfigManager from layered project configuration.
        """
        instance = cls.__new__(cls)
        instance.original_cwd = Path.cwd()
        instance.base_path = Path(layer_context.get("layer_path", "."))

        config_dir = Path(layer_context.get("global_settings", ".")).parent
        instance.active_config_dir = config_dir.resolve()
        instance.active_config_file = Path(layer_context.get("global_settings", "global.yaml")).name

        instance.active_format = None
        instance._detect_format_from_filename(instance.active_config_file)

        instance.discovery = ConfigDiscovery(str(instance.base_path))

        logger.debug(f"Initialized ConfigManager from layer config: {config_dir}")
        return instance


class AppConfigManager:
    """Manages application-level configuration settings."""

    def __init__(self, config_file_path: str):
        self.config_file_path = config_file_path
        self.settings = self._load_settings()
        settings_base_path = self.settings.get("base_path")
        if settings_base_path:
            self.base_path = Path(settings_base_path)
        else:
            self.base_path = Path(config_file_path).parent.resolve()

    def _load_settings(self) -> Dict[str, Any]:
        config_path = Path(self.config_file_path)
        if not config_path.exists():
            raise ConfigurationError(f"Settings file not found: {self.config_file_path}")
        settings = load_config_file(self.config_file_path)
        if not isinstance(settings.get("env_config"), dict):
            raise ConfigurationError("Missing or invalid 'env_config' section")
        return settings

    def get_env_config(self, env: str) -> Dict[str, str]:
        norm_env = self._normalize_env(env)
        env_configs = self.settings["env_config"]
        resolved_env = self._resolve_env_fallback(norm_env, env_configs)
        merged = self._merge_base_and_env(env_configs, resolved_env)
        result = self._validate_and_build_paths(merged)
        logger.info("Loaded config for environment '{}'", env)
        return result

    def _normalize_env(self, env: str) -> str:
        norm_env = normalize_environment(env)
        if not norm_env:
            available = list(self.settings.get("env_config", {}).keys())
            raise ConfigurationError(
                f"Environment '{env}' is invalid or empty. Available: {available}"
            )
        if not is_allowed_environment(norm_env):
            available = list(self.settings.get("env_config", {}).keys())
            raise ConfigurationError(
                f"Environment '{env}' not found or not allowed. Available: {available}"
            )
        return norm_env

    def _resolve_env_fallback(self, env: str, env_configs: Dict[str, Any]) -> str:
        if env in env_configs:
            return env
        if is_sandbox_environment(env):
            base_env = get_base_environment(env)
            if base_env in env_configs:
                return base_env
        if "base" in env_configs:
            return "base"
        raise ConfigurationError(
            f"Environment '{env}' not found. Available: {list(env_configs.keys())}"
        )

    def _merge_base_and_env(self, env_configs: Dict[str, Any], env: str) -> Dict[str, str]:
        base = env_configs.get("base", {})
        env_specific = env_configs.get(env, {})
        merged = {**base, **env_specific}
        base_gs = base.get("global_settings_path")
        env_gs = env_specific.get("global_settings_path")
        if env != "base" and base_gs and env_gs and base_gs != env_gs:
            merged["base_global_settings_path"] = base_gs
        return merged

    def _validate_and_build_paths(self, merged: Dict[str, str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for key, path in merged.items():
            if not path:
                continue
            full_path = self.base_path / path
            try:
                validated = SecurityValidator.validate_path(self.base_path, full_path)
                result[key] = str(validated)
                if not validated.exists():
                    logger.warning("Config path missing: {}", validated)
            except SecurityError as e:
                logger.error("Skipping invalid config path '{}': {}", key, e)
        return result
