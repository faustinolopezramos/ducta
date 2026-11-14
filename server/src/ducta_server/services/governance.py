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

The governance check the server enforces on a run request: protected
environments take the ``pipeline.execute.protected`` permission (operators and
admins have it, developers do not). The rules themselves live in
:mod:`ducta.project_store.governance`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ducta.project_store.governance import PROTECTED_PERMISSION, protected_environments


def check_can_run(user: Any, env: str, project_root: Optional[Path]) -> None:
    """Raise 403 when *user* may not run in *env*."""
    from fastapi import HTTPException

    if env in protected_environments(project_root) and not user.has_permission(
        PROTECTED_PERMISSION
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"'{env}' is a protected environment: running there takes the "
                f"'{PROTECTED_PERMISSION}' permission (operator or admin)"
            ),
        )
