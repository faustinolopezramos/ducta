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

from typing import Any, Mapping, Optional


def get_context_value(context: Any, key: str, default: Any = None) -> Any:
    """Read *key* from *context*, which may be a plain dict/Mapping or an
    attribute-based object.

    Several collaborators in ``ducta.core`` (settings, the run ledger, MLOps
    integration) already duck-type ``context`` this way; this is the shared,
    single implementation of that lookup — mirrors
    ``ducta.stream.context_utils.get_context_value``, which solved the same
    duplication in that module.
    """
    if isinstance(context, Mapping):
        return context.get(key, default)
    return getattr(context, key, default)


def set_context_value(context: Any, key: str, value: Any) -> None:
    """Write *key* on *context*, which may be a plain dict or an
    attribute-based object. Does not catch errors — callers that need
    best-effort writes (e.g. the run ledger) wrap this themselves.
    """
    if isinstance(context, dict):
        context[key] = value
    else:
        setattr(context, key, value)


def get_active_env(context: Any) -> Optional[str]:
    """The context's active environment name, under whichever attribute it's
    exposed (``env`` or the legacy ``environment``).

    This is the same quick, duck-typed fallback already used ad hoc across
    the codebase (``mlrun.config._active_env``,
    ``stream.context_utils.get_active_env``) — not a replacement for
    ``CoreSettings._resolve_env``, which additionally consults
    ``global_config`` and is the authoritative resolver used when building a
    ``CoreSettings`` instance.
    """
    return get_context_value(context, "env", None) or get_context_value(
        context, "environment", None
    )
