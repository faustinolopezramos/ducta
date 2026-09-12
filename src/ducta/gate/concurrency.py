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

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Generic, List, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class ParallelResult(Generic[R]):
    """Outcome of :func:`run_parallel`: results in input order, plus any errors."""

    results: List[Optional[R]] = field(default_factory=list)
    errors: List[Tuple[int, BaseException]] = field(default_factory=list)
    aborted: bool = False


def run_parallel(
    items: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int,
    fail_fast: bool = False,
) -> ParallelResult[R]:
    """Run ``fn(item)`` for every item in a bounded thread pool, preserving order."""
    results: List[Optional[R]] = [None] * len(items)
    errors: List[Tuple[int, BaseException]] = []
    aborted = False

    executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
    try:
        future_to_idx = {executor.submit(fn, item): i for i, item in enumerate(items)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except BaseException as error:  # noqa: BLE001 - caller decides how to handle it
                errors.append((idx, error))
                if fail_fast:
                    aborted = True
                    break
    finally:
        executor.shutdown(wait=not aborted, cancel_futures=aborted)

    return ParallelResult(results=results, errors=errors, aborted=aborted)
