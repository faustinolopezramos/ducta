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

Node execution: the DAG engine and the components a node passes through.

Previously one 1.9k-line ``node_executor.py`` holding eight classes with
unrelated lifetimes — a thread-safe state machine, a module importer, two
quality phases, an output writer, a JDBC ingester and the coordinator itself.
Now split by responsibility.

This package is the import path. Import the concrete class from its module
(``ducta.core.execution.runner``) or the name from here; ``ducta.core`` also
re-exports all eight.
"""

from __future__ import annotations

from ducta.core.execution.coordinator import ParallelCoordinator
from ducta.core.execution.ingestion import IngestionExecutor
from ducta.core.execution.loader import FunctionLoader
from ducta.core.execution.ml_builder import MLContextBuilder
from ducta.core.execution.output import OutputWriter
from ducta.core.execution.quality import QualityCheckExecutor
from ducta.core.execution.runner import NodeExecutor
from ducta.core.execution.state import ThreadSafeExecutionState

__all__ = [
    "FunctionLoader",
    "IngestionExecutor",
    "MLContextBuilder",
    "NodeExecutor",
    "OutputWriter",
    "ParallelCoordinator",
    "QualityCheckExecutor",
    "ThreadSafeExecutionState",
]
