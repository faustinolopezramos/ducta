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


class IOManagerError(Exception):
    """Base exception for all IO Manager operations."""

    pass


class ConfigurationError(IOManagerError):
    """Raised when configuration is invalid or missing."""

    pass


class DataValidationError(IOManagerError):
    """Raised when data validation fails."""

    pass


class FormatNotSupportedError(IOManagerError):
    """Raised when a data format is not supported."""

    pass


class WriteOperationError(IOManagerError):
    """Raised when write operations fail."""

    pass


class ReadOperationError(IOManagerError):
    """Raised when read operations fail."""

    pass


class MissingDependencyError(ReadOperationError):
    """Raised when ``skip_missing=True`` and a node's required inputs are not
    yet available (e.g. an upstream dependency hasn't run). Distinct from
    ``ReadOperationError`` so callers can skip the node cleanly instead of
    treating it as a hard failure."""

    pass
