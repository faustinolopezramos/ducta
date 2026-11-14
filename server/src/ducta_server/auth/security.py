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

Security-critical logic shared between `auth.users.UserStore` (in-memory) and
`db.stores.user_store.DatabaseUserStore` (SQLAlchemy-backed). The two stores
are otherwise sync vs. async and don't share a base class, but this rule and
this timing-attack mitigation must not be allowed to drift between them.
"""

from __future__ import annotations

from typing import Callable, Optional


def resolve_admin_password(env_password: Optional[str], *, is_production: bool) -> str:
    """Apply the shared admin-password production-safety rule.

    Returns the password to seed the admin user with. In production, a
    missing or insecure-default (``"admin"``) password is a hard error;
    outside production, an unset password defaults to ``"admin"``.
    """
    if is_production:
        if not env_password:
            raise RuntimeError(
                "DUCTA_ADMIN_PASSWORD must be set in production when auth is enabled."
            )
        if env_password == "admin":
            raise RuntimeError(
                "DUCTA_ADMIN_PASSWORD cannot use insecure default value in production."
            )
    return env_password or "admin"


def probe_or_verify(
    username_found: bool,
    password: str,
    stored_hash: Optional[str],
    dummy_hash: str,
    verify_fn: Callable[[str, str], bool],
) -> bool:
    """Constant-time-probe pattern to prevent user-enumeration via timing.

    When the username wasn't found, still call *verify_fn* (against a dummy
    hash) so a nonexistent username doesn't return faster than a wrong
    password would — then report "invalid". Only when the username was
    found does the real hash get checked.
    """
    if not username_found:
        verify_fn("__dummy_probe__", dummy_hash)
        return False
    return verify_fn(password, stored_hash)  # type: ignore[arg-type]
