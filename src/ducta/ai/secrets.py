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

Where an API key comes from: the environment first, then the OS keychain.

The environment wins so CI and containers behave the same as today's JDBC
credentials. The keychain (macOS Keychain, Windows Credential Locker, Secret
Service on Linux, through ``keyring``) is what ``ducta ai login`` — and later
the UI — writes to, so a key is never in a file Ducta owns. There is no
plain-text fallback: without a keychain backend, the key goes in a variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import urlparse

from ducta.ai.config import ANTHROPIC, PRESETS, AIConfig
from ducta.ai.errors import AIConfigError, AIEnvironmentError

#: The keychain "service" every Ducta key is stored under; see :func:`keychain_user`.
KEYRING_SERVICE = "ducta-ai"


def keychain_user(provider: str, base_url: Optional[str] = None) -> str:
    """The keychain entry a key for *provider* at *base_url* lives under.

    A key is bound to where it is sent: the provider's name for its own endpoint,
    ``provider@host`` for any other. Pointing a provider at another URL then
    finds no key, instead of sending the stored one to that host.
    """
    preset = PRESETS.get(provider)
    default = (preset.base_url or "").rstrip("/") if preset else ""
    url = (base_url or "").rstrip("/")
    if not url or url == default:
        return provider
    parsed = urlparse(url)
    # Host and port only: a user or password in the URL is never part of the entry's name.
    where = (
        f"{parsed.hostname}:{parsed.port}" if parsed.hostname and parsed.port else parsed.hostname
    )
    return f"{provider}@{where or url}"


@dataclass(frozen=True)
class ResolvedKey:
    value: Optional[str]
    #: ``env:NAME``, ``keychain`` or ``none`` — safe to print.
    source: str

    @property
    def masked(self) -> str:
        return mask(self.value)


def mask(key: Optional[str]) -> str:
    if not key:
        return "—"
    return f"{key[:3]}…{key[-4:]}" if len(key) > 12 else "…"


def _keyring():
    try:
        import keyring  # type: ignore
        from keyring.errors import NoKeyringError  # type: ignore  # noqa: F401
    except ImportError:
        return None
    return keyring


def keychain_available() -> bool:
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        from keyring.backends.fail import Keyring as FailKeyring  # type: ignore

        return not isinstance(keyring.get_keyring(), FailKeyring)
    except Exception:  # noqa: BLE001 — a broken backend is "not available"
        return False


def env_key_allowed(config: AIConfig) -> bool:
    """Whether ``config.api_key_env`` may be read for where *config* sends requests.

    A provider's own variable (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``) holds
    the key to its own endpoint: pointed at another URL, it is not sent there
    — like a keychain key, which is bound to its endpoint.
    """
    preset = PRESETS.get(config.provider)
    own = preset.api_key_env if preset else None
    return not (own and config.custom_endpoint and config.api_key_env == own)


def resolve_key(config: AIConfig, env: Optional[Mapping[str, str]] = None) -> ResolvedKey:
    env = os.environ if env is None else env
    if config.api_key_env and env_key_allowed(config) and env.get(config.api_key_env):
        return ResolvedKey(env[config.api_key_env], f"env:{config.api_key_env}")
    keyring = _keyring()
    if keyring is not None:
        try:
            stored = keyring.get_password(
                KEYRING_SERVICE, keychain_user(config.provider, config.base_url)
            )
        except Exception:  # noqa: BLE001 — a locked/absent keychain is "no key"
            stored = None
        if stored:
            return ResolvedKey(stored, "keychain")
    return ResolvedKey(None, "none")


def require_key(config: AIConfig, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The key, or ``None`` for a local model; raises when a remote one has none."""
    env = os.environ if env is None else env
    resolved = resolve_key(config, env)
    if resolved.value or config.is_local:
        return resolved.value
    if config.api_key_env is None and config.kind != ANTHROPIC:
        # A self-hosted endpoint on the network may not need one either.
        return None
    if not env_key_allowed(config):
        raise AIConfigError(
            f"{config.api_key_env} is the key for {config.label}'s own endpoint and is not "
            f"sent to {config.endpoint}: name another variable (`ducta ai setup --api-key-env "
            "NAME`), or run `ducta ai login` to keep a key for that endpoint."
        )
    where = f"set {config.api_key_env}, or " if config.api_key_env else ""
    raise AIConfigError(
        f"{config.label} needs an API key: {where}run `ducta ai login` to keep it in the "
        "system keychain."
    )


def store_key(provider: str, key: str, base_url: Optional[str] = None) -> None:
    keyring = _keyring()
    if keyring is None or not keychain_available():
        raise AIConfigError(
            "No system keychain is available (install it with `pip install keyring`). "
            "Put the key in an environment variable instead."
        )
    if not key.strip():
        raise AIConfigError("The API key is empty")
    try:
        keyring.set_password(KEYRING_SERVICE, keychain_user(provider, base_url), key.strip())
    except Exception as e:  # noqa: BLE001 — locked, denied, a broken backend
        raise AIEnvironmentError(
            f"The system keychain did not store the key ({type(e).__name__}). Unlock it and "
            "try again, or put the key in an environment variable."
        ) from e


def delete_key(provider: str, base_url: Optional[str] = None) -> bool:
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, keychain_user(provider, base_url))
    except Exception:  # noqa: BLE001 — nothing stored is not an error
        return False
    return True
