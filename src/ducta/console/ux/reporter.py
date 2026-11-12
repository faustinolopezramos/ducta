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

The engine's progress on the terminal: the classic log or the compact view.

Installed by the ``ducta`` command and the API server (whose run log is what the
engine prints) with ``ducta.reporting.set_reporter``. Presentation must never
break a run: every method falls back to the base reporter's log line.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from ducta.reporting import RunReporter


def _short(node: str) -> str:
    return node.split(".")[-1] if "." in node else node


class ConsoleReporter(RunReporter):
    def is_compact(self) -> bool:
        try:
            from ducta.console.ux import view

            return view.is_compact()
        except Exception:  # noqa: BLE001 — presentation must never break a run
            return False

    def node_started(self, node: str) -> None:
        try:
            from ducta.console.ux.rich_logger import log_node_start

            log_node_start(_short(node), "")
        except Exception:  # noqa: BLE001
            super().node_started(node)

    def node_completed(
        self, node: str, duration: float, outputs: Optional[List[Tuple[str, Optional[int]]]]
    ) -> None:
        try:
            from ducta.console.ux.rich_logger import log_node_complete

            log_node_complete(_short(node), duration, outputs=outputs)
        except Exception:  # noqa: BLE001
            super().node_completed(node, duration, outputs)

    def node_failed(self, node: str, error: Exception) -> None:
        try:
            from ducta.console.ux import view

            if view.is_compact():
                # One line now; the full error once, when the command ends. Both
                # the node runner and the coordinator report a failure, and the
                # classic breakdown below printed it twice.
                view.node_failed(node, error)
                return

            from ducta.console.ux.error_analyzer import format_error_for_developer
            from ducta.console.ux.rich_logger import RichLoggerManager

            format_error_for_developer(error, node, RichLoggerManager.get_error_console())
        except Exception:  # noqa: BLE001
            super().node_failed(node, error)

    def section(self, kind: str, title: str, subtitle: Optional[str] = None) -> None:
        if self.is_compact():
            return  # banners are classic-view furniture
        try:
            from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

            console = RichLoggerManager.get_console()
            console.print()
            print_process_separator(kind, title, subtitle, console)
            console.print()
        except Exception:  # noqa: BLE001
            pass

    def schema(self, node: str, df: Any, is_spark: bool) -> None:
        from loguru import logger

        try:
            from ducta.console.ux.rich_logger import RichLoggerManager

            console = RichLoggerManager.get_console()
            if is_spark:
                from ducta.spark_jvm import schema_tree

                schema_output = schema_tree(df)
                if not schema_output:
                    logger.debug("Could not extract the schema tree of {}", node)

                from ducta.console.ux.schema_formatter import print_spark_schema

                print_spark_schema(schema_output, title=node, console=console)
            else:
                from ducta.console.ux.schema_formatter import print_pandas_schema

                print_pandas_schema(df, title=node, console=console)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not format schema as table: {}", e)

    def output_saved(self, node: str) -> None:
        if self.is_compact():
            return  # the node's own line says where it wrote
        try:
            from rich.text import Text  # type: ignore

            from ducta.console.ux.rich_logger import RichLoggerManager

            console = RichLoggerManager.get_console()
            line = Text("  ")
            line.append("✓ ", style="bright_green")
            line.append(f"Output saved for node '{node}'")
            console.print(line)
            console.print()
        except Exception:  # noqa: BLE001
            super().output_saved(node)

    @staticmethod
    def _quiet() -> bool:
        """``-q`` on the classic log: errors only."""
        try:
            from ducta.console.ux.rich_logger import RichLoggerManager

            return bool(RichLoggerManager.get_console().quiet)
        except Exception:  # noqa: BLE001
            return False

    def quality_report(self, report: Any) -> bool:
        # The compact view counts passing checks on the node's line and prints
        # only the ones that fail or warn; the classic view keeps the engine's table.
        if not self.is_compact():
            # Under -q a passing report is not shown; a failing one is an error.
            return self._quiet() and bool(getattr(report, "passed", False))
        from ducta.console.ux import view

        view.quality_report(report)
        return True

    def quality_summary(self, reports: Sequence[Any]) -> bool:
        if not self.is_compact():
            return self._quiet()
        from ducta.console.ux import view

        view.quality_summary(reports)
        return True
