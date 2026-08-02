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

from typing import Any, Dict, Optional

from ducta.gate.context_manager import ContextManager


def compute_fingerprint(
    context_manager: ContextManager,
    *,
    key: str,
    identifier: str,
    dataframe: Any,
    sample_rows: Optional[int] = None,
) -> Any:
    """Compute a DataFingerprint, reading fingerprint_mode/sample_rows from global_settings.

    Does not decide whether fingerprinting should run at all — that is the caller's
    responsibility (see ``BaseIO._record_fingerprint``).
    """
    from ducta.mlrun.fingerprint import DataFingerprint  # optional dependency (mlrun)

    mode = context_manager.get_nested("global_settings.fingerprint_mode", "fast")
    rows = (
        sample_rows
        if sample_rows is not None
        else context_manager.get_nested("global_settings.fingerprint_sample_rows", 100)
    )
    return DataFingerprint.from_file_and_df(key, identifier, dataframe, sample_rows=rows, mode=mode)


def diff_schema_columns(
    previous: Optional[Dict[str, str]], current: Optional[Dict[str, str]]
) -> Optional[str]:
    """Human-readable diff of column name/dtype dicts, or None if nothing changed
    (or either side lacks column-level detail — e.g. an older fingerprint predating
    this field, or a dataframe type where schema capture failed).
    """
    if not previous or not current:
        return None
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    retyped = sorted(col for col in (set(previous) & set(current)) if previous[col] != current[col])
    if not (added or removed or retyped):
        return None
    parts = []
    if added:
        parts.append(f"added={added}")
    if removed:
        parts.append(f"removed={removed}")
    if retyped:
        parts.append(f"type_changed={retyped}")
    return "; ".join(parts)
