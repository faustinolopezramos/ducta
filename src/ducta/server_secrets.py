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


#: Not secrets of the server's own login, but not a run's either: the key that signs Run
#: Certificates (when the server runs a pipeline in its own process the server signs the
#: certificate, so the pipeline's code cannot sign one for a run that never happened) and
#: the keys of the model behind Ducta's AI features. A pipeline that calls a model itself
#: sets its key in the project's ``.env``, which the run still reads.
RUN_WITHHELD: FrozenSet[str] = frozenset(
    {
        "DUCTA_CERTIFICATE_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    }
)
#: Ducta's AI settings (``DUCTA_AI_PROVIDER``, ``DUCTA_AI_API_KEY`` …).
RUN_WITHHELD_PREFIXES = ("DUCTA_AI_",)


def is_server_secret(name: str) -> bool:
    """Whether the environment variable *name* is one of the server's own secrets."""
    return str(name).strip().upper() in SERVER_SECRETS


def withheld_from_runs(name: str) -> bool:
    """Whether *name* stays out of the environment of a run's process (and of node tests)."""
    upper = str(name).strip().upper()
    return (
        upper in SERVER_SECRETS
        or upper in RUN_WITHHELD
        or any(upper.startswith(p) for p in RUN_WITHHELD_PREFIXES)
    )
