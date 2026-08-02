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

import sys

from loguru import logger


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure loguru for structured output."""
    logger.enable("ducta")  # Library is disabled by default (see ducta/__init__.py)
    logger.remove()  # Remove default handler

    if fmt == "json":
        # With serialize=True loguru produces its own JSON output;
        # a custom format string is ignored, so we omit it.
        logger.add(
            sys.stdout,
            level=level.upper(),
            serialize=True,
            colorize=False,
        )
    else:
        # Human-readable for local development
        # Removed colorize=True and complex icons to avoid UnicodeEncodeError on Windows
        log_format = (
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
        )
        logger.add(
            sys.stdout,
            level=level.upper(),
            format=log_format,
            colorize=False,
        )

    logger.debug("Logging configured: level={level}, format={fmt}", level=level, fmt=fmt)
