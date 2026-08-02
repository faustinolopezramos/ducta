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

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from ducta.check.core import QualityReport


class QualityReportSerializer:
    @staticmethod
    def to_dict_records(report: QualityReport) -> List[Dict[str, Any]]:
        records = []
        for r in report.results:
            records.append(
                {
                    "run_id": report.run_id or "unknown",
                    "dataset_name": report.dataset_name,
                    "check_name": r.check_name,
                    "passed": r.passed,
                    "severity": r.severity.value,
                    "message": r.message,
                    "details_json": json.dumps(r.details, default=str),
                    "executed_at": r.executed_at,
                    "report_created_at": report.created_at,
                    "report_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "workspace_path": report.workspace_path or "unknown",
                    "score": report.score,
                }
            )
        return records

    @staticmethod
    def to_pandas_dataframe(report: QualityReport):
        import pandas as pd

        records = QualityReportSerializer.to_dict_records(report)
        return pd.DataFrame(records)

    @staticmethod
    def to_spark_dataframe(report: QualityReport, context: Any):
        try:
            spark = context.spark
        except AttributeError:
            raise ValueError("context must have 'spark' attribute (SparkSession)")
        records = QualityReportSerializer.to_dict_records(report)
        if not records:
            return spark.createDataFrame(
                [], schema="run_id STRING, dataset_name STRING, check_name STRING, passed BOOLEAN"
            )
        return spark.createDataFrame(records)

    @staticmethod
    def to_json_lines(report: QualityReport) -> List[str]:
        return [json.dumps(r, default=str) for r in QualityReportSerializer.to_dict_records(report)]

    @staticmethod
    def to_parquet_metadata(report: QualityReport) -> Dict[str, str]:
        return {
            "run_id": report.run_id or "unknown",
            "dataset_name": report.dataset_name,
            "passed": str(report.passed),
            "score": str(report.score) if report.score is not None else "N/A",
            "errors_count": str(report.errors_count),
            "warnings_count": str(report.warnings_count),
            "checks_count": str(report.checks_count),
            "created_at": report.created_at,
            "elapsed_seconds": str(report.elapsed_seconds),
        }


class GateResultSerializer:
    @staticmethod
    def to_dict(gate_result: Any) -> Dict[str, Any]:
        return (
            gate_result.to_dict()
            if hasattr(gate_result, "to_dict")
            else {
                "gate_name": getattr(gate_result, "gate_name", "quality_gate"),
                "action": str(getattr(gate_result, "action", "unknown")),
                "triggered_rules": getattr(gate_result, "triggered_rules", []),
                "score": getattr(gate_result, "score", None),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def to_json_string(gate_result: Any) -> str:
        return json.dumps(GateResultSerializer.to_dict(gate_result), indent=2, default=str)

    @staticmethod
    def to_pandas_dataframe(gate_result: Any):
        import pandas as pd

        data = GateResultSerializer.to_dict(gate_result)
        data["triggered_rules"] = json.dumps(data.get("triggered_rules", []))
        return pd.DataFrame([data])

    @staticmethod
    def to_spark_dataframe(gate_result: Any, context: Any):
        try:
            spark = context.spark
        except AttributeError:
            raise ValueError("context must have 'spark' attribute (SparkSession)")
        data = GateResultSerializer.to_dict(gate_result)
        data["triggered_rules"] = json.dumps(data.get("triggered_rules", []))
        return spark.createDataFrame([data])
