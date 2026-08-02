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

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from loguru import logger

try:
    __version__ = version("ducta")
except PackageNotFoundError:  # pragma: no cover - not installed (e.g. running from source)
    __version__ = "0.0.0+unknown"

# Silence the library by default (standard loguru pattern for libraries).
# Ducta emits no log records unless the consuming application explicitly turns
# them on with ``logger.enable("ducta")``. The CLI and API server do this when
# they configure their own handlers. This guarantees Ducta's internal module
# paths (its core) are never exposed to end users through stray import-time logs.
logger.disable("ducta")

__all__ = ["__version__"]
