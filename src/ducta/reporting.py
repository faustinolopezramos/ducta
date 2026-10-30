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

What the engine shows while a pipeline runs.

``core`` and ``check`` report progress through the reporter set here instead of
importing the CLI's presentation (``ducta.console.ux``): the engine must not depend
on the layers built on top of it. The ``ducta`` command and the API server install
``ducta.console.ux.reporter.ConsoleReporter``; without one — Ducta used as a
library — the base reporter only logs, and Ducta logs nothing unless the
application enables it (``logger.enable("ducta")``).
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from loguru import logger


class RunReporter:
    """The base reporter: one log line where the console would print."""

    def is_compact(self) -> bool:
        """Whether the CLI's compact view is on (the engine then prints less)."""
        return False

    def node_started(self, node: str) -> None:
        logger.info("Starting execution of node: {}", node)

    def node_completed(
        self, node: str, duration: float, outputs: Optional[List[Tuple[str, Optional[int]]]]
    ) -> None:
        logger.info("Node '{}' completed successfully", node)

    def node_failed(self, node: str, error: Exception) -> None:
        logger.error("Node '{}' failed: {}", node, error)

    def section(self, kind: str, title: str, subtitle: Optional[str] = None) -> None:
        """A banner between the phases of a run (schema, summary…)."""

    def schema(self, node: str, df: Any, is_spark: bool) -> None:
        """The schema of a node's result."""

    def output_saved(self, node: str) -> None:
        logger.info("Output saved successfully for node '{}'", node)

    def quality_report(self, report: Any) -> bool:
        """Show *report* the reporter's way; False leaves it to the quality engine."""
        return False

    def quality_summary(self, reports: Sequence[Any]) -> bool:
        """Show *reports* the reporter's way; False leaves it to the quality engine."""
        return False


_reporter: RunReporter = RunReporter()


def get_reporter() -> RunReporter:
    return _reporter


def set_reporter(reporter: Optional[RunReporter]) -> RunReporter:
    """Install *reporter* (None: the base one) and return the one it replaces."""
    global _reporter
    previous, _reporter = _reporter, reporter or RunReporter()
    return previous
