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

import re

from ducta.console.commands.ingestion_setup import IngestionSetupCommands
from ducta.console.core import ExitCode

_TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class InitCommands:
    """Handles ingestion commands - routes to IngestionSetupCommands."""

    @staticmethod
    def _is_valid_table_name(name: str) -> bool:
        """Return True if `name` is a safe SQL identifier."""
        return bool(name) and bool(_TABLE_NAME_PATTERN.match(name))

    @staticmethod
    def handle(parsed_args) -> int:
        """Route ingestion commands."""
        init_cmd = getattr(parsed_args, "init_command", None)
        if init_cmd == "ingestion":
            # Route to ingestion setup commands
            return IngestionSetupCommands.handle(parsed_args)

        return ExitCode.GENERAL_ERROR.value
