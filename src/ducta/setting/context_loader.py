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

from pathlib import Path
from typing import Any, Dict

from loguru import logger

from ducta.setting.contexts import Context
from ducta.setting.exceptions import ConfigLoadError, ConfigValidationError
from ducta.setting.loaders import ConfigLoaderFactory


class ContextLoader:
    """
    Core component for loading execution contexts from configuration files.
    """

    def __init__(self, allow_python_config: bool = True):
        self.allow_python_config = allow_python_config
        self.loader_factory = ConfigLoaderFactory(allow_python=allow_python_config)

    def load_from_paths(self, config_paths: Dict[str, str], env: str) -> Context:
        """
        Initialize context from a dictionary of configuration file paths.
        Delegates parallel loading and validation to the Context class.
        """
        required = (
            "global_settings_path",
            "pipelines_config_path",
            "nodes_config_path",
            "input_config_path",
            "output_config_path",
        )

        missing = [path for path in required if path not in config_paths]
        if missing:
            raise ValueError(f"Missing config paths: {missing}")

        logger.debug("Delegating parallel configuration loading for env '{}' to Context", env)

        # Environment override files are partial: deep-merge the env's global
        # settings over the base's so omitted keys keep their base value instead
        # of being dropped. Only kicks in when the resolved env supplied its own
        # global_settings file distinct from base (see AppConfig._merge_base_and_env).
        global_settings_source: Any = config_paths["global_settings_path"]
        base_gs_path = config_paths.get("base_global_settings_path")
        if base_gs_path and base_gs_path != global_settings_source:
            from ducta.setting.utils import deep_merge_dicts

            base_settings = self._load_file(base_gs_path)
            env_settings = self._load_file(global_settings_source)
            global_settings_source = deep_merge_dicts(base_settings, env_settings)
            logger.info(
                "Merged '{}' global settings over base ({} override key(s))",
                env,
                len(env_settings),
            )

        ctx = Context(
            global_settings=global_settings_source,
            pipelines_config=config_paths["pipelines_config_path"],
            nodes_config=config_paths["nodes_config_path"],
            input_config=config_paths["input_config_path"],
            output_config=config_paths["output_config_path"],
            env=env,
            allow_python_config=self.allow_python_config,
        )

        ctx.config_paths = config_paths

        # Quality extensions loading remains in loader for lifecycle reasons.
        # load_quality_extensions() imports arbitrary Python modules named in
        # config, same trust boundary as PythonConfigLoader — must not run
        # when allow_python_config=False (see ConfigLoaderFactory below).
        global_settings = ctx.global_settings
        extensions = (global_settings.get("quality") or {}).get("extensions") or []
        if extensions and not self.allow_python_config:
            logger.warning(
                "Skipping {} quality extension(s): allow_python_config is False, "
                "which forbids importing arbitrary Python modules from config.",
                len(extensions),
            )
        elif extensions:
            try:
                from ducta.check.core import load_quality_extensions

                load_quality_extensions(extensions)
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to load quality extensions: {}", exc)

        return ctx

    def _load_file(self, path_str: str) -> Dict[str, Any]:
        """Load a configuration file."""
        try:
            return self.loader_factory.load_config(Path(path_str))
        except (ConfigLoadError, ConfigValidationError):
            raise
        except Exception as e:
            raise ConfigLoadError(f"Failed to load config '{path_str}': {e}") from e
