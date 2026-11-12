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

Credentials masked out of text that outlives the run: the log file, the run
certificate, the run result, the error printed on the terminal. A node error
echoing ``jdbc:…?password=…`` went verbatim into the certificate.

One implementation, :func:`ducta.ai.context.redact` (the masking the AI features
apply to what they send out), behind a cheap test: most messages mention no
credential at all, and that module is not light to import.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

#: Cheap test before the real patterns: most messages mention none of these.
_MAY_HOLD_SECRET = re.compile(
    r"://|pass|pwd|secret|token|key|sig|bearer|authoriz|credential", re.IGNORECASE
)

_redact: Optional[Callable[[str], str]] = None


def redact_secrets(text: str) -> str:
    """*text* with credentials masked; may raise (callers that must not, use ``redact_text``)."""
    global _redact
    if not _MAY_HOLD_SECRET.search(text):
        return text
    if _redact is None:
        from ducta.ai.context import redact  # imported on first use: it is not light

        _redact = redact
    return _redact(text)


def redact_text(text: Any) -> Any:
    """*text* with credentials masked (``password=***``); anything not a string as given."""
    if not isinstance(text, str):
        return text
    try:
        return redact_secrets(text)
    except Exception:  # noqa: BLE001 — masking must never fail what it protects
        return text
