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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ducta.check.core import QualityReport
from ducta.check.serialization import GateResultSerializer, QualityReportSerializer
from ducta.check.storage import DEFAULT_PIPELINE_NAME, _sanitize_dataset_name, _sanitize_run_id
from ducta.gate.factories import WriterFactory


@dataclass
class QualityOutputConfig:
    """Configuration for quality output persistence."""

    enabled: bool = False
    format: str = "parquet"
    write_mode: str = "overwrite"
    partition_by: Optional[List[str]] = None
    base_path: Optional[str] = None  # e.g., "{workspace}/quality"
    per_node: bool = True
    global_summary: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "format": self.format,
            "write_mode": self.write_mode,
            "partition_by": self.partition_by,
            "base_path": self.base_path,
            "per_node": self.per_node,
            "global_summary": self.global_summary,
        }


@dataclass
class QualityOutputPath:
    """Result of quality output persistence."""

    report_type: str  # "sanity", "dq", "gate"
    node_name: str
    run_id: str
    output_path: str
    format: str
    rows_written: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "report_type": self.report_type,
            "node_name": self.node_name,
            "run_id": self.run_id,
            "output_path": self.output_path,
            "format": self.format,
            "rows_written": self.rows_written,
            "timestamp": self.timestamp,
        }


class QualityOutputManager:
    def __init__(self, context: Any):
        self.context = context
        self.writer_factory = WriterFactory(context)

    def persist_quality_report(
        self,
        report: QualityReport,
        node_name: str,
        run_id: str,
        config: QualityOutputConfig,
        report_type: str = "dq",
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> Optional[QualityOutputPath]:
        return self._persist(
            QualityReportSerializer.to_spark_dataframe(report, self.context),
            node_name,
            run_id,
            config,
            report_type,
            pipeline_name,
        )

    def persist_gate_result(
        self,
        gate_result: Any,
        node_name: str,
        run_id: str,
        config: QualityOutputConfig,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> Optional[QualityOutputPath]:
        return self._persist(
            GateResultSerializer.to_spark_dataframe(gate_result, self.context),
            node_name,
            run_id,
            config,
            "gate",
            pipeline_name,
        )

    def _persist(
        self,
        spark_df: Any,
        node_name: str,
        run_id: str,
        config: QualityOutputConfig,
        report_type: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> Optional[QualityOutputPath]:
        if not config.enabled:
            return None
        try:
            output_path = self._resolve_output_path(
                config.base_path, node_name, run_id, report_type, pipeline_name
            )
            rows = self._write_dataframe(
                spark_df,
                output_path,
                format=config.format,
                write_mode=config.write_mode,
                partition_by=config.partition_by,
            )
            logger.info(
                f"Persisted {report_type} report for node '{node_name}' to {output_path} ({rows} rows)"
            )
            return QualityOutputPath(
                report_type=report_type,
                node_name=node_name,
                run_id=run_id,
                output_path=output_path,
                format=config.format,
                rows_written=rows,
            )
        except Exception as e:
            logger.error(f"Failed to persist {report_type} report: {e}")
            raise

    def _write_dataframe(
        self, spark_df, output_path, format=None, write_mode=None, partition_by=None
    ):  # noqa: A002
        fmt = format
        rows = spark_df.count()
        writer = self.writer_factory.get_handler(fmt)
        writer.write(
            spark_df,
            output_path,
            {
                "mode": write_mode,
                "format": fmt.lower(),
                **(partition_by and {"partitionBy": partition_by} or {}),
            },
        )
        return rows

    def _resolve_output_path(
        self,
        base_path: Optional[str],
        node_name: str,
        run_id: str,
        report_type: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> str:
        if not base_path:
            base_path = str(
                Path(getattr(self.context, "workspace_path", ".ducta/quality")) / "quality"
            )
        if "${" in base_path:
            global_settings = getattr(self.context, "global_settings", {}) or {}
            if global_settings:
                from ducta.setting.interpolator import VariableInterpolator

                base_path = VariableInterpolator.interpolate(base_path, global_settings)
        # Sanitize each identifier-derived path component (defense in depth,
        # matching check/storage.py and stream/checkpoints.py) so none of them
        # can escape base_path via "/" or "..". pipeline_name scopes reports
        # the same way check/storage.py scopes reports/history/baselines, so
        # two pipelines with a same-named node never collide here either.
        safe_report_type = _sanitize_dataset_name(report_type)
        safe_pipeline_name = _sanitize_dataset_name(pipeline_name)
        safe_node_name = _sanitize_dataset_name(node_name)
        safe_run_id = _sanitize_run_id(run_id)
        return str(
            Path(base_path) / safe_report_type / safe_pipeline_name / safe_node_name / safe_run_id
        )

    def get_persisted_reports(
        self,
        node_name: str,
        run_id: str,
        report_type: str = "dq",
        base_path: Optional[str] = None,
        format: str = "parquet",
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> Optional[Any]:
        """Read back a report previously written by ``persist_quality_report``.

        ``format`` must match the ``QualityOutputConfig.format`` used for the
        write — the output path never carries a file extension (see
        ``_resolve_output_path``), so it can't be inferred from the path.
        """
        try:
            output_path = self._resolve_output_path(
                base_path, node_name, run_id, report_type, pipeline_name
            )
            ws = getattr(self.context, "workspace_path", None)
            if ws and not Path(output_path).exists():
                logger.warning(f"Persisted report not found at {output_path}")
                return None
            from ducta.gate.factories import ReaderFactory

            return ReaderFactory(self.context).get_handler(format.lower()).read(output_path, {})
        except Exception as e:
            logger.error(f"Failed to load persisted report: {e}")
            return None
