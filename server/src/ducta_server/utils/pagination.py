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

from typing import List, Sequence, Tuple, TypeVar

T = TypeVar("T")


def paginate(items: Sequence[T], skip: int, limit: int) -> Tuple[List[T], int]:
    """Slice *items* for a page and report the total count.

    Returns ``(page, total)`` where ``page`` is ``items[skip:skip+limit]``.
    A non-positive ``limit`` means "no upper bound" — the page runs from
    ``skip`` to the end of ``items``.
    """
    total = len(items)
    if limit > 0:
        return list(items[skip : skip + limit]), total
    return list(items[skip:]), total
