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

Pipeline executors, one module per pipeline type.

Previously one 2k-line ``executor.py``. Splitting it by pipeline type makes the
batch/hybrid divergence visible: when both lived in the same file it was easy for
hybrid to quietly miss phases batch had, which is exactly what happened.

This package is the import path. Import the concrete class from its module
(``ducta.core.executors.batch``) or the name from here; ``ducta.core`` also
re-exports all five.
"""

from __future__ import annotations

from ducta.core.executors.base import BaseExecutor
from ducta.core.executors.batch import BatchExecutor
from ducta.core.executors.facade import PipelineExecutor
from ducta.core.executors.hybrid import HybridExecutor
from ducta.core.executors.streaming import StreamingExecutor

__all__ = [
    "BaseExecutor",
    "BatchExecutor",
    "HybridExecutor",
    "PipelineExecutor",
    "StreamingExecutor",
]
