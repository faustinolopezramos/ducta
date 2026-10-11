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

from ducta.core.errors import DuctaError


class AIError(DuctaError):
    """A model could not be configured, reached, or understood.

    The message is written for the person at the terminal: it names what to
    run or set to fix it, and never contains an API key.
    """

    exit_code = 5  # ExitCode.DEPENDENCY_ERROR: the model could not be reached or understood
    http_status = 502


class AIConfigError(AIError):
    """The request or the configuration is wrong: no provider, no key, nothing to do."""

    exit_code = 2  # ExitCode.CONFIGURATION_ERROR
    http_status = 400


class AIEnvironmentError(AIError):
    """Ducta cannot do it here: a package is missing, or a file cannot be written."""

    exit_code = 5  # ExitCode.DEPENDENCY_ERROR
    http_status = 500


class AINotFoundError(AIError):
    """A draft or pipeline that does not exist."""

    exit_code = 1
    http_status = 404


class AIConflictError(AIError):
    """A draft that can no longer be applied as it is."""

    exit_code = 1
    http_status = 409


class AICancelledError(AIError):
    """The person who started a draft stopped it."""

    exit_code = 1
    http_status = 409
