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

from typing import FrozenSet

SERVER_SECRETS: FrozenSet[str] = frozenset(
    {
        "JWT_SECRET_KEY",
        "DUCTA_ADMIN_PASSWORD",
        "DATABASE_URL",
        "DUCTA_SMTP_USER",
        "DUCTA_SMTP_PASSWORD",
        "RATE_LIMIT_REDIS_URL",
        "REVOCATION_REDIS_URL",
    }
)


def is_server_secret(name: str) -> bool:
    """Whether the environment variable *name* is one of the server's own secrets."""
    return str(name).strip().upper() in SERVER_SECRETS
