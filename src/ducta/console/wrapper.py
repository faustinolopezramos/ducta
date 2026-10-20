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

import sys
from typing import Optional


def _get_missing_dependency_message(module_name: str, feature: str) -> str:
    """
    Generate a user-friendly message for a missing dependency.

    Args:
        module_name: Name of the missing module
        feature: Name of the feature that requires the module

    Returns:
        Formatted message to display to the user
    """
    install_command = f'pip install "ducta[{feature}]"'

    return f"""
╔═══════════════════════════════════════════════════════════════════════╗
║                         MISSING DEPENDENCY                            ║
╚═══════════════════════════════════════════════════════════════════════╝

The module '{module_name}' is not installed.

This command needs an optional part of ducta. To install it, run:

    {install_command}

Alternatively, you can install all optional dependencies:

    pip install "ducta[all]"

For more information, refer to the documentation at:
https://ducta.readthedocs.io/

┌───────────────────────────────────────────────────────────────────────┐
│ If the problem persists, open an issue at:                             │
│ https://github.com/faustinolopezramos/ducta/issues                            │
└───────────────────────────────────────────────────────────────────────┘
"""


def _identify_feature_for_module(module_name: str) -> Optional[str]:
    """
    Map a missing module to its extras feature group.
    """
    # Module-to-feature mapping
    module_to_feature = {
        "pyspark": "spark",
        "pyarrow": "spark",
        "fastapi": "api",
        "starlette": "api",
        "uvicorn": "api",
        "jwt": "api",
        "bcrypt": "api",
        "sqlalchemy": "database",
        "alembic": "database",
        "psycopg2": "database",
        "mlflow": "mlops",
        "sklearn": "mlops",
        "optuna": "mlops",
        "databricks": "databricks",
        "delta": "delta",
        "prometheus_client": "monitoring",
        "httpx": "ai",
        "anthropic": "ai",
        "keyring": "ai",
        "ruamel": "ai",
    }

    return module_to_feature.get(module_name)


def main() -> int:
    """
    Entry point for the ducta CLI wrapper.
    Intercepts missing module errors and shows friendly messages.

    Returns the CLI's exit code. This is the process's exit status: the
    ``ducta`` console script declared in pyproject.toml is invoked as
    ``sys.exit(main())``. Calling the CLI and dropping what it returned made
    that ``sys.exit(None)`` — so every failure exited 0, and no script wrapping
    ``ducta`` could tell a broken run from a clean one.
    """
    try:
        from ducta.console.cli import main as Ducta_main

        return Ducta_main()
    except ModuleNotFoundError as e:
        # `e.name` is the module as imported ("ruamel.yaml"); the map is by package.
        missing_module = (e.name or "").split(".")[0] or "unknown"
        feature = _identify_feature_for_module(missing_module)
        if feature is None and missing_module.startswith("ducta"):
            raise  # a broken install of ducta itself: no extra fixes that
        message = _get_missing_dependency_message(missing_module, feature or "all")
        print(message, file=sys.stderr)

        return 1
    except Exception:
        # Propagate all other errors normally
        raise


if __name__ == "__main__":
    sys.exit(main())
