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

The model, when there is one. The agents' rule-based parts run without it:
no provider configured, no key, no ``ai`` extra — they still work.
"""

from __future__ import annotations

from typing import Optional, Tuple

from ducta.ai.errors import AIError
from ducta.ai.providers import LLMProvider


def optional_provider() -> Tuple[Optional[LLMProvider], str]:
    """The configured provider and ``""``; or ``None`` and why there is none."""
    try:
        from ducta.ai.config import load_config
        from ducta.ai.providers import make_provider

        return make_provider(load_config()), ""
    except AIError as e:
        return None, e.message
    except ImportError as e:  # pragma: no cover — a package the model needs is missing
        return None, str(e)
