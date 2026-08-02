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
    install_command = f"pip install Ducta[{feature}]"

    return f"""
╔═══════════════════════════════════════════════════════════════════════╗
║                         MISSING DEPENDENCY                            ║
╚═══════════════════════════════════════════════════════════════════════╝

The module '{module_name}' is not installed.

This dependency is required to use distributed data processing
features in ducta. To install it, run:

    {install_command}

Alternatively, you can install all optional dependencies:

    pip install Ducta[all]

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
        "uvicorn": "api",
        "motor": "api",
        "pymongo": "api",
        "sqlalchemy": "database",
        "psycopg2": "database",
        "mlflow": "mlops",
        "databricks": "mlops",
        "prometheus_client": "monitoring",
    }

    return module_to_feature.get(module_name)


def main() -> None:
    """
    Entry point for the ducta CLI wrapper.
    Intercepts missing module errors and shows friendly messages.
    """
    try:
        from ducta.console.cli import main as Ducta_main

        Ducta_main()
    except ModuleNotFoundError as e:
        missing_module = str(e).split("'")[1] if "'" in str(e) else "unknown"
        feature = _identify_feature_for_module(missing_module)
        message = _get_missing_dependency_message(missing_module, feature or "all")
        print(message, file=sys.stderr)

        sys.exit(1)
    except Exception:
        # Propagate all other errors normally
        raise


if __name__ == "__main__":
    main()
