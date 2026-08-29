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
from enum import Enum
from typing import Dict, List, Optional

DEFAULT_ENVIRONMENTS = ["base", "dev", "sandbox", "staging", "prod"]

ENV_ALIASES = {
    "development": "dev",
    "prod": "prod",
    "production": "prod",
    "staging": "staging",
    "test": "sandbox",
    "testing": "sandbox",
}


class CanonicalEnvironment(str, Enum):
    BASE = "base"
    DEV = "dev"
    SANDBOX = "sandbox"
    STAGING = "staging"
    PROD = "prod"

    def __str__(self) -> str:
        return self.value

    @staticmethod
    def is_local(env: str) -> bool:
        return str(env).lower() in ("base", "dev", "sandbox")

    @staticmethod
    def is_remote(env: str) -> bool:
        return str(env).lower() in ("prod", "staging")

    @staticmethod
    def is_safe(env: str) -> bool:
        return str(env).lower() != "prod"

    @staticmethod
    def is_testing(env: str) -> bool:
        return str(env).lower() == "sandbox"


FALLBACK_CHAINS: Dict[str, List[str]] = {
    CanonicalEnvironment.BASE.value: [CanonicalEnvironment.BASE.value],
    CanonicalEnvironment.DEV.value: [
        CanonicalEnvironment.DEV.value,
        CanonicalEnvironment.BASE.value,
    ],
    CanonicalEnvironment.SANDBOX.value: [
        CanonicalEnvironment.SANDBOX.value,
        CanonicalEnvironment.BASE.value,
    ],
    CanonicalEnvironment.STAGING.value: [
        CanonicalEnvironment.STAGING.value,
        CanonicalEnvironment.PROD.value,
        CanonicalEnvironment.BASE.value,
    ],
    CanonicalEnvironment.PROD.value: [
        CanonicalEnvironment.PROD.value,
        CanonicalEnvironment.BASE.value,
    ],
}


def get_fallback_chain(env: str) -> List[str]:
    normalized = str(env).lower()
    if normalized.startswith("sandbox_") and normalized != "sandbox":
        return [normalized, "sandbox", "base"]
    if normalized in FALLBACK_CHAINS:
        return FALLBACK_CHAINS[normalized]
    raise ValueError(f"Unknown environment '{env}'. Valid: {', '.join(DEFAULT_ENVIRONMENTS)}")


def is_sandbox_environment(env_name: str) -> bool:
    """Check if environment name is a sandbox environment (sandbox or sandbox_*)."""
    if not env_name:
        return False
    return env_name == "sandbox" or env_name.startswith("sandbox_")


def get_sandbox_developer(env_name: str) -> Optional[str]:
    """Extract developer name from sandbox environment name."""
    if not is_sandbox_environment(env_name):
        return None

    if env_name == "sandbox":
        return None  # Generic sandbox

    parts = env_name.split("_", 1)
    if len(parts) == 2 and parts[0] == "sandbox":
        return parts[1]

    return None


def get_base_environment(env_name: str) -> str:
    """Get base environment name (e.g., sandbox_juan -> sandbox)."""
    if is_sandbox_environment(env_name):
        return "sandbox"
    return env_name


def is_valid_environment(env: str) -> bool:
    """
    Check if an environment name is valid (canonical or alias).
    """
    if not isinstance(env, str):
        return False

    normalized = env.strip().lower()

    if normalized in DEFAULT_ENVIRONMENTS:
        return True

    if normalized in ENV_ALIASES:
        return True

    if normalized == "sandbox" or normalized.startswith("sandbox_"):
        return True

    return False


def normalize_environment(env_name: Optional[str]) -> Optional[str]:
    """Normalize environment name: lower-case, map aliases, and trim."""
    if not env_name:
        return None
    env = env_name.strip().lower()

    if not env:
        return None

    if env in ENV_ALIASES:
        return ENV_ALIASES[env]

    if env == "sandbox":
        return "sandbox"
    if env.startswith("sandbox_"):
        dev = env.split("_", 1)[1]
        safe_dev = "".join(c for c in dev if c.isalnum() or c == "_")
        return f"sandbox_{safe_dev}" if safe_dev else "sandbox"

    return env


def allowed_environments() -> List[str]:
    """Return the list of allowed canonical environments."""
    extra = os.getenv("DUCTA_ALLOWED_ENVS", "")
    extras = [e.strip().lower() for e in extra.split(",") if e.strip()] if extra else []
    normalized_extras = [normalize_environment(e) for e in extras]
    uniq = []
    for e in DEFAULT_ENVIRONMENTS + normalized_extras:
        if e and e not in uniq:
            uniq.append(e)
    return uniq


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


def is_allowed_environment(env_name: str) -> bool:
    """Check whether an environment is allowed (after normalization)."""
    if not is_valid_environment(env_name):
        return False

    norm = normalize_environment(env_name)
    if not norm:
        return False

    if norm == "sandbox" or norm.startswith("sandbox_"):
        return True

    return norm in allowed_environments()
