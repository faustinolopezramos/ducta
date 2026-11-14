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

Schema display and persistence of a node's result frame.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.core.execution.cancellation import ensure_not_cancelled
from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.settings import CoreSettings
from ducta.reporting import get_reporter


def _compact_view() -> bool:
    """Whether the CLI's compact view is on (never, outside the CLI)."""
    try:
        return get_reporter().is_compact()
    except Exception:  # noqa: BLE001 — presentation must never break a run
        return False


#: Set on an exception once its failure has been shown.
_REPORTED = "_ducta_failure_reported"


def report_node_failure(error: Exception, node_name: str) -> None:
    """Show a failed node's error the reporter's way (a rich, developer-facing
    breakdown on the terminal), falling back to a plain log line.

    Shared by ``NodeExecutor`` and ``ParallelCoordinator``, which previously
    each carried an identical try/import/format/except-fallback copy of this.

    The error is marked once shown: it travels from the node's thread to the
    coordinator, which reports it again, and the terminal printed every failure
    twice.
    """
    if getattr(error, _REPORTED, False):
        return
    try:
        get_reporter().node_failed(node_name, error)
    except Exception:
        logger.error("Node '{}' failed: {}", node_name, error)
    try:
        setattr(error, _REPORTED, True)
    except Exception:  # noqa: BLE001 — a type that refuses attributes is shown again, no worse
        pass


class OutputWriter:
    """Validates and persists node output DataFrames."""

    def __init__(
        self,
        output_manager: Any,
        context: Any,
        is_ml_layer: bool = False,
        settings: Optional[CoreSettings] = None,
    ) -> None:
        self.output_manager = output_manager
        self.context = context
        self.settings = settings or CoreSettings.from_context(context)
        self.is_ml_layer = is_ml_layer

    def display_schema(self, result_df: Any, node_name: str) -> None:
        """Print the 'DATA SCHEMA' panel for a node result (Spark or pandas)."""
        is_spark = hasattr(result_df, "printSchema")
        is_pandas = False
        if not is_spark:
            try:
                import pandas as pd  # type: ignore

                is_pandas = isinstance(result_df, pd.DataFrame)
            except Exception:
                is_pandas = False

        if not (is_spark or is_pandas):
            return
        if _compact_view():
            return  # the compact view shows rows per output; --verbose shows schemas

        node_display_name = node_name.replace(".", " › ")
        try:
            reporter = get_reporter()
            reporter.section("schema", "DATA SCHEMA", node_display_name)
            reporter.schema(node_display_name, result_df, is_spark)
        except Exception as e:
            logger.warning("Could not format schema as table: {}", e)

    def save(
        self,
        result_df: Any,
        node_config: Dict[str, Any],
        node_name: str,
        start_date: Optional[str],
        end_date: Optional[str],
        ml_info: Dict[str, Any],
    ) -> None:
        """Enhanced validation and output saving with ML metadata."""
        # A node that outlived its timeout has already been reported failed;
        # its output must not land. (Writes already under way are Spark jobs
        # carrying the node's tag, and were cancelled with it.)
        ensure_not_cancelled(self.context, node_name)

        if isinstance(result_df, str) and ("://" in result_df or "model_registry" in result_df):
            logger.info("Node '{}' output is an artifact URI. Skipping standard saving.", node_name)
            return

        # A node that declares no outputs runs for its effect (notify, audit,
        # train-and-register): there is nothing to write, so what it returns is
        # neither validated nor saved. The schema and `config validate` accept
        # such a node; validating its return value made it fail every run.
        if not node_config.get("output"):
            logger.debug(
                "Node '{}' declares no outputs; its return value ({}) is not saved.",
                node_name,
                type(result_df).__name__,
            )
            return

        PipelineValidator.validate_dataframe_schema(result_df)
        self.display_schema(result_df, node_name)

        # The single resolved environment. This used to be re-derived here with
        # its own precedence order, which the chain-reuse check then had to
        # replicate by hand to target the same path this write uses.
        env = self.settings.env

        output_params = {
            "node": node_config,
            "dataframe": result_df,
            "start_date": start_date,
            "end_date": end_date,
        }

        if self.is_ml_layer:
            output_params["model_version"] = ml_info["model_version"]

        self.output_manager.save_output(env, **output_params)

        try:
            get_reporter().output_saved(node_name)
        except Exception:
            logger.info("Output saved successfully for node '{}'", node_name)
