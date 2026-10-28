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

What the log file may hold and who may read it.

The file sink is always at DEBUG and keeps seven days: the one place where a stray
``password=…`` from a driver, a URL with a login or a bearer token would outlive the run.
It is created for its owner alone and passes every message through the same redaction
the AI features apply to what they send out. No dependency on ``rich``: the plain
logger setup uses it too.
"""

from __future__ import annotations

import os
import re
import traceback
import zipfile
from typing import Any, Callable, Optional

#: Cheap test before the real patterns: most messages mention none of these.
_MAY_HOLD_SECRET = re.compile(
    r"://|pass|pwd|secret|token|key|sig|bearer|authoriz|credential", re.IGNORECASE
)

_redact: Optional[Callable[[str], str]] = None


def private_file_opener(path: str, flags: int) -> int:
    """``open`` for a log file: created readable and writable by its owner only."""
    return os.open(path, flags, 0o600)


def private_zip(path: str) -> None:
    """Loguru ``compression`` for a rotated log: a zip created for its owner alone.

    ``compression="zip"`` creates the archive with the process umask (usually 0644), so
    a week of DEBUG logs became readable by everyone once rotated.
    """
    fd = os.open(f"{path}.zip", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(path, os.path.basename(path))
    os.remove(path)


def _redacted(text: str) -> str:
    global _redact
    if not _MAY_HOLD_SECRET.search(text):
        return text
    if _redact is None:
        from ducta.ai.context import redact  # imported on first use: it is not light

        _redact = redact
    return _redact(text)


def redacting_filter(record: Any) -> bool:
    """A loguru filter that masks credentials in the message; it never drops a record."""
    message = record.get("message")
    if not isinstance(message, str):
        return True
    try:
        record["message"] = _redacted(message)
    except Exception:  # noqa: BLE001 — logging must never fail because of its own safety net
        pass
    return True


def file_format(template: str) -> Callable[[Any], str]:
    """A loguru ``format`` for the log file: ``template``, then the traceback redacted.

    With a string format loguru appends the raw ``{exception}``: a driver error echoing
    ``jdbc:…?password=…`` in a ``logger.exception`` went to the file as it was. A
    callable format gets no traceback unless it adds one, so this adds the redacted one.
    """

    def render(record: Any) -> str:
        exception = record.get("exception")
        if not exception:
            return template + "\n"
        try:
            text = "".join(
                traceback.format_exception(exception.type, exception.value, exception.traceback)
            )
            text = _redacted(text)
        except Exception:  # noqa: BLE001 — never lose the line for its traceback
            text = f"{getattr(exception.type, '__name__', 'Exception')} (traceback not shown)"
        record["extra"]["_redacted_exception"] = text.rstrip("\n")
        return template + "\n{extra[_redacted_exception]}\n"

    return render
