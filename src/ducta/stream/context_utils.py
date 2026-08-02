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

from typing import Any


def get_context_value(context: Any, key: str, default: Any = None) -> Any:
    """Read *key* from *context*, which may be a plain dict or an attribute-based object.

    Several collaborators in this package (readers, writers, the pipeline
    manager) already duck-type ``context`` this way; this is the shared,
    single implementation of that lookup.
    """
    if isinstance(context, dict):
        return context.get(key, default)
    return getattr(context, key, default)
