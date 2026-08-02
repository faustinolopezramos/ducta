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

import os
import re
from typing import Any, Dict, FrozenSet, Optional

from ducta.setting.exceptions import ConfigLoadError

_DEFAULT_PATH_KEYS: FrozenSet[str] = frozenset({"filepath"})

# ${VAR} is meant for interpolating paths/config, not for smuggling secrets
# into a config value — a config file (which may get logged, persisted
# alongside a run certificate, or committed) is a much wider blast radius
# than the environment variable itself. Reject any variable name that looks
# like it holds a credential, whether or not it's actually set.
_SENSITIVE_VAR_NAME_RE = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)


class VariableInterpolator:
    """Handles variable interpolation in configuration strings."""

    MAX_INTERPOLATION_DEPTH = 10
    MAX_ITERATIONS = 100

    @staticmethod
    def _check_max_depth(depth: int, context: str = "interpolation") -> None:
        """Validate that we haven't exceeded maximum depth."""
        if depth > VariableInterpolator.MAX_INTERPOLATION_DEPTH:
            raise ConfigLoadError(
                f"Maximum {context} depth exceeded ({VariableInterpolator.MAX_INTERPOLATION_DEPTH}). "
                "Possible circular reference in variable interpolation."
            )

    @staticmethod
    def _replace_env_placeholders(string: str) -> str:
        """Replace any ${VAR} occurrences that match environment variables only."""
        result = string
        iterations = 0

        start = result.find("${")
        while start != -1:
            iterations += 1
            if iterations > VariableInterpolator.MAX_ITERATIONS:
                raise ConfigLoadError(
                    f"Maximum interpolation iterations exceeded ({VariableInterpolator.MAX_ITERATIONS}). "
                    "Check for overly complex variable chains in the configuration."
                )

            end = result.find("}", start + 2)
            if end == -1:
                break

            var_name = result[start + 2 : end]
            if _SENSITIVE_VAR_NAME_RE.search(var_name):
                raise ConfigLoadError(
                    f"Refusing to interpolate '${{{var_name}}}': variable names matching "
                    "KEY/SECRET/TOKEN/PASSWORD/CREDENTIAL are not allowed via ${VAR} "
                    "interpolation. ${VAR} is meant for paths/config, not secrets — a "
                    "config value can end up logged or persisted (e.g. alongside a run "
                    "certificate) far more widely than the environment itself."
                )
            env_value = os.getenv(var_name)
            if env_value is not None:
                result = result[:start] + env_value + result[end + 1 :]
                start = result.find("${", start + len(env_value))
            else:
                start = result.find("${", end + 1)

        return result

    @staticmethod
    def _replace_variables(result: str, variables: Dict[str, Any], _depth: int) -> str:
        """Replace placeholders from the provided variables mapping (recursing when needed)."""
        if not variables:
            return result

        for key, value in variables.items():
            placeholder = f"${{{key}}}"
            if placeholder not in result:
                continue
            if isinstance(value, str) and "${" in value:
                # Recursively interpolate the variable's value before replacing
                value = VariableInterpolator.interpolate(value, variables, _depth + 1)
            result = result.replace(placeholder, str(value))
        return result

    @staticmethod
    def interpolate(string: str, variables: Dict[str, Any], _depth: int = 0) -> str:
        """Replace variables in a string with their corresponding values.

        OS environment variables take precedence over config-provided variables
        (deliberate, 12-factor-style override; see TestInterpolationPrecedence).
        """
        if not string or not isinstance(string, str):
            return string

        VariableInterpolator._check_max_depth(_depth)

        result = VariableInterpolator._replace_env_placeholders(string)

        result = VariableInterpolator._replace_variables(result, variables, _depth)

        return result

    @staticmethod
    def interpolate_config_paths(
        config: Dict[str, Any],
        variables: Dict[str, Any],
        *,
        keys: Optional[FrozenSet[str]] = None,
    ) -> None:
        """Recursively interpolate variables in configuration file paths in-place.

        This method **mutates** *config* directly (no copy is made). Only dict
        entries whose key is exactly one of ``keys`` are interpolated — by
        default just ``"filepath"`` (the input/output catalog convention);
        other keys (e.g. a Kafka ``options.subscribe`` topic string) are
        intentionally left untouched so unrelated ``${...}`` templating (e.g.
        Redpanda Connect's bloblang ``${!...}`` syntax) is never touched.

        Pass ``keys={"path", "checkpoint_location"}`` to also cover streaming
        nodes' inline I/O (``nodes_config``), which declare their storage
        location under ``path`` and their Structured Streaming checkpoint
        under ``checkpoint_location`` instead of a catalog ``filepath``.
        """
        target_keys = keys if keys is not None else _DEFAULT_PATH_KEYS

        def _rec(node: Any):
            if isinstance(node, dict):
                for key in target_keys:
                    val = node.get(key)
                    if isinstance(val, str):
                        node[key] = VariableInterpolator.interpolate(val, variables)
                for v in node.values():
                    _rec(v)
            elif isinstance(node, list):
                for item in node:
                    _rec(item)

        _rec(config)

    @staticmethod
    def interpolate_structure(
        value: Any, variables: Dict[str, Any], *, copy: bool = False, _depth: int = 0
    ) -> Any:
        """Recursively interpolate variables in any nested structure of dicts/lists/strings."""
        VariableInterpolator._check_max_depth(_depth, "structure")

        if isinstance(value, str):
            return VariableInterpolator.interpolate(value, variables, _depth=_depth)

        if isinstance(value, list):
            items = [
                VariableInterpolator.interpolate_structure(
                    item, variables, copy=True, _depth=_depth + 1
                )
                for item in value
            ]
            if copy:
                return items
            value[:] = items
            return value

        if isinstance(value, dict):
            mapping = {
                key: VariableInterpolator.interpolate_structure(
                    item, variables, copy=True, _depth=_depth + 1
                )
                for key, item in value.items()
            }
            if copy:
                return mapping
            value.clear()
            value.update(mapping)
            return value

        return value
