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

import re
from typing import Any

_MAY_HOLD_SECRET = re.compile(
    r"://|pass|pwd|secret|token|key|sig|bearer|authoriz|credential", re.IGNORECASE
)

_PREFIXED_KEY = (
    r"(?:sk-[\w-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_\w{30,}|xox[abp]-[\w-]{10,}"
    r"|dapi[0-9a-f]{32}(?:-\d+)?)"
)
_PRIVATE_KEY = r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"

_SECRETS = (
    (re.compile(_PRIVATE_KEY, re.DOTALL), "***"),
    (re.compile(rf"\b{_PREFIXED_KEY}"), "***"),
    (re.compile(r"(\b[a-zA-Z][\w+.-]{0,32}://[^/\s:@]+:)[^/\s@]+@"), r"\1***@"),
    (
        re.compile(
            r"(?i)(?<![A-Za-z0-9])([\w.-]{0,64}"
            r"(?:password|passwd|pwd|secret|token(?!s\b)|api[_-]?key|access[_-]?key|account[_-]?key)"
            r"[\w.-]{0,64}[\"']?\s*[=:]\s*[\"']?)[^\s\"';,&]+"
        ),
        r"\1***",
    ),
    (
        re.compile(
            r"(?i)\b([\w-]*(?:secret|password|passwd|token|access|api)[\w-]*"
            r"\.(?:key|secret|password|token)[ \t]+)[^\s\"';,&]+"
        ),
        r"\1***",
    ),
    (re.compile(r"(?i)(?<![A-Za-z0-9])(sig\s*=\s*)[^\s\"';,&]+"), r"\1***"),
    (re.compile(r"(?i)\b(bearer\s+)[\w.~+/=-]+"), r"\1***"),
    (
        re.compile(
            r"(?i)\b(authorization[\"']?\s*[=:]\s*[\"']?(?:basic|digest|negotiate)\s+)[^\s\"';,]+"
        ),
        r"\1***",
    ),
)


def redact(text: str) -> str:
    """*text* with the credentials it obviously contains replaced by ``***``."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


def redact_secrets(text: str) -> str:
    """*text* with credentials masked; may raise (callers that must not, use ``redact_text``)."""
    if not _MAY_HOLD_SECRET.search(text):
        return text
    return redact(text)


def redact_text(text: Any) -> Any:
    """*text* with credentials masked (``password=***``); anything not a string as given."""
    if not isinstance(text, str):
        return text
    try:
        return redact_secrets(text)
    except Exception:  # noqa: BLE001 — masking must never fail what it protects
        return text
