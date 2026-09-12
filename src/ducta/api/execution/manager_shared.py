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

from ducta.api.models.execution import ExecutionStatus

#: Statuses at which an execution is done and will not transition further.
#:
#: Shared between manager_dispatch (retry eligibility) and manager_streaming
#: (when to stop the SSE log stream) — kept here, not in either mixin file,
#: to avoid an import cycle between the two.
_TERMINAL_STATUSES = frozenset(
    {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)
