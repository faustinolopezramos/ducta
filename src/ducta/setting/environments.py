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

from typing import Optional

DEFAULT_ENVIRONMENTS = ["base", "dev", "sandbox", "staging", "prod"]

ENV_ALIASES = {
    "development": "dev",
    "prod": "prod",
    "production": "prod",
    "staging": "staging",
    "test": "sandbox",
    "testing": "sandbox",
}


def is_sandbox_environment(env_name: str) -> bool:
    """Check if environment name is a sandbox environment (sandbox or sandbox_*)."""
    if not env_name:
        return False
    return env_name == "sandbox" or env_name.startswith("sandbox_")


def get_base_environment(env_name: str) -> str:
    """Get base environment name (e.g., sandbox_juan -> sandbox)."""
    if is_sandbox_environment(env_name):
        return "sandbox"
    return env_name


def normalize_environment(env_name: Optional[str]) -> Optional[str]:
    """Normalize environment name: lower-case, map aliases, and trim."""
    if not env_name:
        return None
    env = env_name.strip().lower()

    if not env:
        return None

    if env in ENV_ALIASES:
        return ENV_ALIASES[env]

    if is_sandbox_environment(env):
        if env == "sandbox":
            return "sandbox"
        dev = env.split("_", 1)[1]
        safe_dev = "".join(c for c in dev if c.isalnum() or c == "_")
        return f"sandbox_{safe_dev}" if safe_dev else "sandbox"

    return env


def sanitize_env_for_path(env_name: Optional[str]) -> str:
    """Sanitize an environment name for use as a filesystem path segment.

    Falls back to "base" for empty/None input, and strips path separators
    and traversal sequences so a hostile/malformed env string can never
    escape the intended directory (e.g. "../../etc", "prod/../../x").
    """
    if not env_name:
        return "base"
    candidate = str(env_name).strip().replace("/", "_").replace("\\", "_")
    candidate = candidate.replace("..", "_")
    candidate = "".join(c for c in candidate if c.isalnum() or c in ("_", "-"))
    return candidate or "base"
