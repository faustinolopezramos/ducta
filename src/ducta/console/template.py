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
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.console.core import VALID_NAME_RE as _VALID_NAME_RE
from ducta.console.core import ConfigFormat, DuctaError, ExitCode

try:
    import yaml  # type: ignore

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Path constants to avoid duplicated literals
DATA_BRONZE = "data/bronze"
DATA_SILVER = "data/silver"
DATA_GOLD = "data/gold"
PIPELINES_ETL_MODULE = "pipelines.etl"
_TEMPLATE_CANCELLED_MSG = "Template generation cancelled"


class TemplateType(Enum):
    """Available template types for project generation."""

    MEDALLION_BASIC = "medallion_basic"
    ML_READY = "ml_ready"
    STREAMING_CORE = "streaming_core"
    HYBRID = "hybrid"


class TemplateError(DuctaError):
    """Exception for template-related errors."""

    def __init__(self, message: str):
        super().__init__(message, ExitCode.CONFIGURATION_ERROR)


class TemplateFactory:
    """Factory for creating template instances."""

    @staticmethod
    def create_template(
        template_type: TemplateType,
        project_name: str,
        config_format: ConfigFormat = ConfigFormat.YAML,
    ) -> Any:
        """Create a template instance based on the given type."""
        if template_type == TemplateType.MEDALLION_BASIC:
            return MedallionBasicTemplate(project_name, config_format)
        if template_type == TemplateType.ML_READY:
            return MLReadyTemplate(project_name, config_format)
        if template_type == TemplateType.STREAMING_CORE:
            return StreamingCoreTemplate(project_name, config_format)
        if template_type == TemplateType.HYBRID:
            return HybridTemplate(project_name, config_format)
        raise TemplateError(f"Unknown template type: {template_type}")

    @staticmethod
    def list_available_templates() -> List[Dict[str, str]]:
        """List all available templates with their metadata."""
        return [
            {
                "type": "medallion_basic",
                "name": "Medallion Basic",
                "description": "Functional Medallion template: minimal, clean, and production-ready",
            },
            {
                "type": "ml_ready",
                "name": "ML Ready",
                "description": "Medallion + ML: Integrated experiment tracking and model registry",
            },
            {
                "type": "streaming_core",
                "name": "Streaming Core",
                "description": "Real-time Ready: file-stream → Parquet streaming orchestration",
            },
            {
                "type": "hybrid",
                "name": "Hybrid",
                "description": "Batch + Streaming: a batch stage feeds a streaming stage",
            },
        ]


class MedallionBasicTemplate:
    """Functional Medallion template: minimal, clean, and production-ready."""

    # File extension mapping by format
    FORMAT_EXTENSIONS = {
        ConfigFormat.YAML: ".yaml",
        ConfigFormat.JSON: ".json",
        ConfigFormat.TOML: ".toml",
    }

    def __init__(self, project_name: str, config_format: ConfigFormat = ConfigFormat.YAML):
        self.project_name = project_name
        self.config_format = config_format
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def generate_settings_json(self) -> Dict[str, Any]:
        """Generate environment configuration with paths matching the format."""
        file_ext = self.FORMAT_EXTENSIONS[self.config_format]

        # Common path patterns for each environment
        config_paths = {
            "base": {
                "global_settings_path": f"config/global_settings{file_ext}",
                "pipelines_config_path": f"config/pipelines{file_ext}",
                "nodes_config_path": f"config/nodes{file_ext}",
                "input_config_path": f"config/input{file_ext}",
                "output_config_path": f"config/output{file_ext}",
            },
            "dev": {
                "global_settings_path": f"config/dev/global_settings{file_ext}",
                "input_config_path": f"config/dev/input{file_ext}",
                "output_config_path": f"config/dev/output{file_ext}",
            },
            "sandbox": {
                "global_settings_path": f"config/sandbox/global_settings{file_ext}",
                "input_config_path": f"config/sandbox/input{file_ext}",
                "output_config_path": f"config/sandbox/output{file_ext}",
            },
            "prod": {
                "global_settings_path": f"config/prod/global_settings{file_ext}",
                "input_config_path": f"config/prod/input{file_ext}",
                "output_config_path": f"config/prod/output{file_ext}",
            },
        }

        return {"base_path": ".", "env_config": config_paths}

    def get_common_global_settings(self) -> Dict[str, Any]:
        """Get common global settings for all templates."""
        return {
            "project_name": self.project_name,
            "version": "1.0.0",
            "created_at": self.timestamp,
            "template_type": "medallion_basic",
            "architecture": "medallion",
            "layers": ["bronze", "silver", "gold"],
            "mode": "local",  # change to 'databricks' or 'distributed' if needed
            # Base dirs for ${input_path}/${output_path} interpolation in the
            # I/O catalogs; required by Context validation.
            "input_path": "data",
            "output_path": "data",
            "max_parallel_nodes": 4,
            "fail_on_error": True,
        }

    def generate_global_settings(self) -> Dict[str, Any]:
        base_settings = self.get_common_global_settings()
        base_settings.update(
            {
                "default_date": "2025-01-01",
                "spark_master": "local[4]",
                "max_retries": 2,
                "fail_on_error": True,
                # Quality: add custom check modules and reusable profiles here.
                # Extensions are Python modules containing @register_check classes.
                # Profiles are reusable bundles of check defaults applied per-node.
                "quality": {
                    "extensions": [],
                    "profiles": {
                        "default": {
                            "checks": {
                                "empty_dataset": {"enabled": True},
                            }
                        },
                    },
                },
            }
        )
        return base_settings

    def generate_pipelines_config(self) -> Dict[str, Any]:
        """Single, focused ETL pipeline showcasing Ducta capabilities."""
        return {
            "etl": {
                "description": "Complete ETL pipeline: Extract → Transform → Load",
                "type": "batch",
                "nodes": ["extract", "transform", "load"],
                "inputs": ["source_data"],
                "outputs": ["gold.etl.final_output"],
                # The sample ETL is not incremental — it must run without
                # --start-date/--end-date, as the generated README promises.
                "requires_dates": False,
            },
        }

    def generate_nodes_config(self) -> Dict[str, Any]:
        """Three nodes whose checks actually assert what the code just did.

        The checks are deliberately not decoration. Silver's ``null_rate`` and
        ``duplicates`` pass only because `transform` dropped nulls and
        duplicates; break that function and the ``quality_gate`` blocks the run
        before gold is ever written. That is the behaviour worth seeing on a
        first run, and the previous template never showed it: five spotless rows
        against ``row_count: {min: 1}`` can only ever pass.
        """
        return {
            "extract": {
                "description": "Bronze: land the source exactly as it arrived",
                "module": PIPELINES_ETL_MODULE,
                "function": "extract",
                "input": ["source_data"],
                "output": ["bronze.etl.raw_data"],
                "dependencies": [],
                # Checks on the INPUT, before the node runs: fail early if the
                # source is not what this pipeline was written against.
                "sanity_checks": {
                    "enabled": True,
                    "fail_fast": True,
                    "checks": {
                        "empty_dataset": {"enabled": True},
                        "schema": {
                            "enabled": True,
                            "expected_columns": [
                                "order_id",
                                "category",
                                "amount",
                                "order_date",
                            ],
                        },
                    },
                },
            },
            "transform": {
                "description": "Silver: deduplicate and drop incomplete rows",
                "module": PIPELINES_ETL_MODULE,
                "function": "transform",
                "input": ["bronze.etl.raw_data"],
                "output": ["silver.etl.clean_data"],
                "dependencies": ["extract"],
                # Checks on the OUTPUT, after the node runs and BEFORE the write.
                # A blocking gate here means bad data never reaches storage.
                "data_quality": {
                    "enabled": True,
                    "fail_fast": False,
                    "checks": {
                        # `columns` (a list) and `threshold`, not `column`/`max`.
                        "null_rate": {
                            "enabled": True,
                            "columns": ["amount"],
                            "threshold": 0.0,
                        },
                        "duplicates": {
                            "enabled": True,
                            "columns": ["order_id"],
                            "max_duplicate_rate": 0.0,
                        },
                        # A floor, not a ceiling: catches a transform that
                        # silently drops most of the data.
                        "row_count": {"enabled": True, "min": 400},
                    },
                    "quality_gate": {
                        "enabled": True,
                        "max_errors": 0,
                        # skip_downstream: gold is skipped, the run reports the
                        # block, and nothing bad is written. Use `stop_all` to
                        # abort the whole run instead.
                        "behavior": "skip_downstream",
                    },
                },
            },
            "load": {
                "description": "Gold: aggregate into one row per category",
                "module": PIPELINES_ETL_MODULE,
                "function": "load",
                "input": ["silver.etl.clean_data"],
                "output": ["gold.etl.final_output"],
                "dependencies": ["transform"],
                "data_quality": {
                    "enabled": True,
                    "checks": {
                        "empty_dataset": {"enabled": True},
                        "row_count": {"enabled": True, "min": 1},
                    },
                },
            },
        }

    def generate_input_config(self) -> Dict[str, Any]:
        """Input catalog: the external source plus intermediate datasets.

        Intermediate datasets must appear here too — downstream nodes read
        their inputs through this catalog, from the paths the output layer
        writes to ({output_path}/{environment}/{schema}/{sub_folder}/{table}).
        """
        return {
            "source_data": {
                "description": "Source dataset (supports CSV, JSON, Parquet)",
                "format": "csv",
                "filepath": "data/input.csv",
                "options": {
                    "header": True,
                    "inferSchema": True,
                },
            },
            "bronze.etl.raw_data": {
                "description": "Raw data extracted by the 'extract' node",
                "format": "parquet",
                "filepath": "${output_path}/${environment}/bronze/etl/raw_data",
            },
            "silver.etl.clean_data": {
                "description": "Clean data produced by the 'transform' node",
                "format": "parquet",
                "filepath": "${output_path}/${environment}/silver/etl/clean_data",
            },
        }

    def generate_output_config(self) -> Dict[str, Any]:
        """Output catalog keyed by schema.sub_folder.table_name.

        Paths are derived from the key as
        {output_path}/{environment}/{schema}/{sub_folder}/{table_name}.
        """
        return {
            "bronze.etl.raw_data": {
                "description": "Extracted raw data (bronze layer)",
                "format": "parquet",
                "write_mode": "overwrite",
            },
            "silver.etl.clean_data": {
                "description": "Transformed clean data (silver layer)",
                "format": "parquet",
                "write_mode": "overwrite",
            },
            "gold.etl.final_output": {
                "description": "Final output ready for consumption (gold layer)",
                "format": "csv",
                "write_mode": "overwrite",
            },
        }

    #: Rows whose ``amount`` is blank, so `transform` has real nulls to drop and
    #: the silver null_rate check has something to have actually verified.
    _NULL_ROWS = frozenset({37, 88, 145, 190, 233, 271, 318, 366, 402, 447, 480, 495})
    #: Orders repeated verbatim at the end of the file, so deduplication is a
    #: visible step rather than a claim.
    _DUPLICATED_ORDERS = (12, 74, 155, 219, 288, 341, 409, 468)
    _CATEGORIES = ("electronics", "grocery", "apparel", "home", "toys")

    def get_sample_data(self) -> str:
        """A deliberately dirty CSV, so the medallion layers have work to do.

        The previous sample was five spotless rows, which meant every quality
        check passed trivially and bronze, silver and gold came out byte-for-byte
        identical — a "medallion" demo with no refinement in it, and a quality
        demo where nothing was ever caught.

        This one carries 12 rows with a missing ``amount`` and 8 verbatim
        duplicates, so the run tells a story you can read straight off the
        certificate: 508 rows in bronze, 488 in silver once `transform` cleans
        them, 5 in gold after aggregation. The silver checks then pass *because*
        the transform did its job — break the transform and the gate blocks.

        Deterministic on purpose: the same scaffold must produce the same
        fingerprints, or the certificate demo is not reproducible.
        """
        header = "order_id,category,amount,order_date"
        rows = []
        for order_id in range(1, 501):
            category = self._CATEGORIES[order_id % len(self._CATEGORIES)]
            # Blank (not 0) — a missing amount, which is what null_rate is about.
            amount = "" if order_id in self._NULL_ROWS else f"{50 + (order_id * 7) % 450}.00"
            day = (order_id % 28) + 1
            rows.append(f"{order_id},{category},{amount},2025-01-{day:02d}")

        by_id = {int(r.split(",", 1)[0]): r for r in rows}
        rows.extend(by_id[order_id] for order_id in self._DUPLICATED_ORDERS)

        return "\n".join([header, *rows]) + "\n"


class MLReadyTemplate(MedallionBasicTemplate):
    """Medallion + ML: Integrated experiment tracking and model registry."""

    def get_common_global_settings(self) -> Dict[str, Any]:
        settings = super().get_common_global_settings()
        settings.update(
            {
                "template_type": "ml_ready",
                # Reproducibility: seeds random/numpy/torch globally and provides
                # a deterministic per-node seed via ml_context["node_seed"].
                "random_seed": 42,
                "mlops": {
                    "experiment_name": self.project_name,
                    "tracking_uri": "sqlite:///mlflow.db",
                    "registry_uri": "sqlite:///registry.db",
                },
            }
        )
        return settings

    def generate_pipelines_config(self) -> Dict[str, Any]:
        config = super().generate_pipelines_config()
        config["train"] = {
            "description": "Model Training Pipeline",
            # The "ml" pipeline type delivers ml_context (seed/split/hyperparams) to every node.
            "type": "ml",
            # The sample training run is not incremental — runs without --start-date/--end-date.
            "requires_dates": False,
            "nodes": ["extract", "transform", "train_model"],
            "inputs": ["source_data"],
            # The model is self-persisted by the node via ducta.mlrun.persist_model
            # (versioned in the model registry, or a stamped local file as fallback),
            # so there is no model output in the I/O catalog.
            "outputs": [],
            # Versioned hyperparameters: delivered to nodes via ml_context
            "hyperparams": {"n_estimators": 100, "max_depth": 5},
            # Declarative split, delivered via ml_context["split"]. val_size is
            # what keeps model selection off the test set: candidates are
            # compared on validation, and test is scored once at the end.
            "split": {
                "method": "stratified",
                "stratify_col": "target",
                "test_size": 0.2,
                "val_size": 0.2,
            },
            # Average the selection metric over this many folds instead of one
            # validation split (delivered via ml_context["cv_folds"]).
            "cv_folds": 3,
        }
        return config

    def get_sample_data(self) -> str:
        """Numeric, binary-labeled dataset the sample `train` node can fit directly.

        Purely numeric features (RandomForest fits them without encoding) and a
        balanced binary `target` column so the stratified split has both classes.
        Features are separable so the model beats the trivial baseline.
        """
        rows = ["feature_1,feature_2,feature_3,target"]
        # 10 rows per class, class 0 low / class 1 high on feature_1 & feature_3.
        for i in range(10):
            rows.append(f"{0.1 + i * 0.03:.2f},{1.0 + i * 0.05:.2f},{0.2 + i * 0.02:.2f},0")
        for i in range(10):
            rows.append(f"{0.9 + i * 0.03:.2f},{1.0 + i * 0.05:.2f},{0.9 + i * 0.02:.2f},1")
        return "\n".join(rows) + "\n"

    #: The columns of this template's own sample CSV, which is numeric and
    #: already clean — nothing like the medallion sales data.
    _ML_COLUMNS = ("feature_1", "feature_2", "feature_3", "target")

    def generate_nodes_config(self) -> Dict[str, Any]:
        nodes = super().generate_nodes_config()

        # The `train` pipeline reuses medallion's `extract` and `transform`
        # nodes, but not its data. Their inherited checks assert the medallion
        # schema (order_id/category/amount) against this template's numeric
        # feature table, so every one of them would fail here and the gate would
        # block the run on the very first scaffold. Retune them to this dataset.
        nodes["extract"]["sanity_checks"]["checks"]["schema"]["expected_columns"] = list(
            self._ML_COLUMNS
        )
        transform_dq = nodes["transform"]["data_quality"]
        transform_dq["checks"] = {
            # A missing label makes a row untrainable, so this is the one that
            # matters before a split.
            "null_rate": {
                "enabled": True,
                "columns": list(self._ML_COLUMNS),
                "threshold": 0.0,
            },
            "row_count": {"enabled": True, "min": 10},
        }
        nodes["load"]["data_quality"]["checks"]["row_count"]["min"] = 1

        nodes["train_model"] = {
            "description": "Train ML model",
            "module": "pipelines.ml",
            "function": "train",
            "input": ["silver.etl.clean_data"],
            # No catalog output: the node persists the model itself and returns its
            # artifact URI (see pipelines/ml.py:train -> persist_model).
            "output": [],
            "dependencies": ["transform"],
            "ml_stage": "training",
            # Node-level hyperparams override pipeline-level ones
            "hyperparams": {},
            # val_f1 is the selection metric (computed on validation/CV folds);
            # test_f1 is the unbiased estimate, reported but never selected on.
            "metrics": ["val_f1", "baseline_f1", "test_f1"],
        }
        return nodes


class StreamingCoreTemplate(MedallionBasicTemplate):
    """Real-time Ready: a file-stream → Parquet streaming pipeline.

    Uses a file-stream source (a watched directory) with an ``availableNow``
    trigger, so the sample runs to completion locally and in CI without a Kafka
    broker. The generated README shows how to swap in Kafka for a live source.

    Streaming nodes follow the streaming engine's config model (different from
    batch): the ``input``/``output`` are declared **inline** (format + options +
    schema), and the transform is referenced as ``function: {module, key}`` and
    registered by ``register_transforms(registry)`` in ``pipelines/streaming.py``.
    """

    STREAM_SOURCE = "data/stream_source"
    STREAM_OUT = "data/stream_out"
    STREAM_CHECKPOINT = "data/checkpoints/stream_ingest"
    STREAM_SCHEMA = "id INT, value DOUBLE, event_ts STRING"

    def get_common_global_settings(self) -> Dict[str, Any]:
        settings = super().get_common_global_settings()
        settings.update({"template_type": "streaming_core"})
        return settings

    def generate_pipelines_config(self) -> Dict[str, Any]:
        return {
            "ingest_stream": {
                "description": "File-stream ingestion (JSON → Parquet), terminates via availableNow",
                "type": "streaming",
                "nodes": ["stream_ingest"],
            }
        }

    def generate_nodes_config(self) -> Dict[str, Any]:
        return {
            "stream_ingest": self._stream_ingest_node(),
        }

    def _stream_ingest_node(self) -> Dict[str, Any]:
        """A single streaming node: read a JSON file stream, enrich, write Parquet."""
        return {
            "description": "Consume a JSON file stream and write enriched rows to Parquet",
            "type": "streaming",
            # Inline input: a watched directory of JSON files with an explicit schema
            # (streaming file sources require a schema).
            "input": {
                "format": "file_stream",
                "file_format": "json",
                "schema": self.STREAM_SCHEMA,
                "options": {
                    "path": self.STREAM_SOURCE,
                    "maxFilesPerTrigger": "1",
                },
            },
            # Transform resolved from the registry populated by register_transforms().
            "function": {
                "module": "pipelines.streaming",
                "key": "enrich",
            },
            "output": {
                "format": "parquet",
                "path": self.STREAM_OUT,
            },
            "streaming": {
                "checkpoint_location": self.STREAM_CHECKPOINT,
                "output_mode": "append",
                # available_now: process all data currently available, then stop —
                # so `ducta stream run --mode sync` terminates on its own.
                "trigger": {"type": "available_now"},
            },
        }

    def generate_input_config(self) -> Dict[str, Any]:
        # Streaming nodes carry their input inline; no I/O catalog needed.
        return {}

    def generate_output_config(self) -> Dict[str, Any]:
        # Streaming nodes carry their output inline; no I/O catalog needed.
        return {}


class HybridTemplate(MedallionBasicTemplate):
    """Batch + Streaming in one pipeline: a batch stage feeds a streaming stage.

    ``prepare`` (batch) lands the source rows as Parquet in the bronze layer;
    ``stream_ingest`` (streaming) reads that same directory as a file stream and
    writes enriched rows to Parquet, terminating via an ``available_now`` trigger.
    Exercises the HybridExecutor's batch→streaming cross-stage flow.
    """

    # Where the batch stage writes (schema.sub_folder.table → this local path) and
    # where the streaming stage reads from.
    BRONZE_PATH = "data/base/bronze/hybrid/events"
    STREAM_OUT = "data/hybrid_out"
    STREAM_CHECKPOINT = "data/checkpoints/hybrid_stream"
    STREAM_SCHEMA = "id INT, value DOUBLE, event_ts STRING"

    def get_common_global_settings(self) -> Dict[str, Any]:
        settings = super().get_common_global_settings()
        settings.update({"template_type": "hybrid"})
        return settings

    def get_sample_data(self) -> str:
        """Rows matching the streaming schema (id INT, value DOUBLE, event_ts STRING).

        ``event_ts`` is a plain label (not an ISO timestamp) so CSV inferSchema
        keeps it as a string — the batch stage writes Parquet with a string column
        and the streaming stage reads it back with the same declared schema.
        """
        rows = ["id,value,event_ts"]
        for i in range(1, 6):
            rows.append(f"{i},{i * 10.0:.1f},evt_{i}")
        return "\n".join(rows) + "\n"

    def generate_pipelines_config(self) -> Dict[str, Any]:
        return {
            "flow": {
                "description": "Hybrid: batch prepare (Parquet) → streaming enrich (Parquet)",
                "type": "hybrid",
                "requires_dates": False,
                "nodes": ["prepare", "stream_ingest"],
            }
        }

    def generate_nodes_config(self) -> Dict[str, Any]:
        return {
            "prepare": {
                "description": "Batch stage: land source rows in the bronze layer",
                "module": "pipelines.hybrid",
                "function": "prepare",
                "input": ["source_data"],
                "output": ["bronze.hybrid.events"],
                "dependencies": [],
            },
            "stream_ingest": {
                "description": "Streaming stage: read the bronze dir as a file stream",
                "type": "streaming",
                "dependencies": ["prepare"],
                "input": {
                    "format": "file_stream",
                    "file_format": "parquet",
                    "schema": self.STREAM_SCHEMA,
                    "options": {
                        "path": self.BRONZE_PATH,
                        "maxFilesPerTrigger": "1",
                    },
                },
                "function": {
                    "module": "pipelines.hybrid",
                    "key": "enrich",
                },
                "output": {
                    "format": "parquet",
                    "path": self.STREAM_OUT,
                },
                "streaming": {
                    "checkpoint_location": self.STREAM_CHECKPOINT,
                    "output_mode": "append",
                    "trigger": {"type": "available_now"},
                },
            },
        }

    def generate_input_config(self) -> Dict[str, Any]:
        return {
            "source_data": {
                "description": "Source dataset for the batch stage",
                "format": "csv",
                "filepath": "data/input.csv",
                "options": {"header": True, "inferSchema": True},
            },
        }

    def generate_output_config(self) -> Dict[str, Any]:
        return {
            "bronze.hybrid.events": {
                "description": "Batch-prepared events (bronze layer), read by the stream",
                "format": "parquet",
                "write_mode": "overwrite",
            },
        }


class TemplateGenerator:
    """Generates complete project templates with directory structure."""

    FORMAT_DESCRIPTORS = {
        ConfigFormat.YAML: ("environment.yaml", ".yaml"),  # Conda-compatible
        ConfigFormat.JSON: ("settings.json", ".json"),  # Pure JSON
        ConfigFormat.TOML: ("environment.toml", ".toml"),  # Type-safe TOML
    }

    def __init__(self, output_path: Path, config_format: ConfigFormat = ConfigFormat.YAML):
        self.output_path = Path(output_path)
        self.config_format = config_format
        descriptor_name, file_ext = self.FORMAT_DESCRIPTORS[config_format]
        self._settings_filename = descriptor_name
        self._file_extension = file_ext
        _writers = {
            ConfigFormat.YAML: self._write_yaml_file,
            ConfigFormat.JSON: self._write_json_file,
            ConfigFormat.TOML: self._write_toml_file,
        }
        self._writer = _writers.get(config_format)
        if not self._writer:
            raise TemplateError(f"Unsupported format: {config_format}")

    def generate_project(
        self,
        template_type: TemplateType,
        project_name: str,
        create_sample_code: bool = True,
        developer_sandboxes: Optional[List[str]] = None,
    ) -> None:
        """Generate complete project structure from template."""
        logger.info("Generating {} template for project '{}'", template_type.value, project_name)

        # Create template instance
        template = TemplateFactory.create_template(template_type, project_name, self.config_format)

        # Create directory structure
        self._create_directory_structure(developer_sandboxes)

        # Generate configuration files
        self._generate_config_files(template, developer_sandboxes)

        # Generate sample code if requested
        if create_sample_code:
            self._generate_sample_code(template_type)

        # Generate additional project files
        self._generate_project_files(template)

        logger.success("Project '{}' generated successfully at {}", project_name, self.output_path)

    def _create_directory_structure(self, developer_sandboxes: Optional[List[str]] = None) -> None:
        """Create minimal but complete project structure."""
        directories = [
            "config",
            "config/dev",
            "config/sandbox",
            "config/prod",
            "pipelines",
            "data",
            "data/bronze",
            "data/silver",
            "data/gold",
            "logs",
        ]

        # Add developer sandbox directories
        if developer_sandboxes:
            for dev in developer_sandboxes:
                directories.append(f"config/sandbox_{dev}")

        for directory in directories:
            dir_path = self.output_path / directory
            dir_path.mkdir(parents=True, exist_ok=True)

            # Create __init__.py for pipelines
            if directory == "pipelines":
                (dir_path / "__init__.py").touch()

    def _generate_config_files(
        self, template: MedallionBasicTemplate, developer_sandboxes: Optional[List[str]] = None
    ) -> None:
        """Generate all configuration files."""
        configs = {
            "global_settings": template.generate_global_settings(),
            "pipelines": template.generate_pipelines_config(),
            "nodes": template.generate_nodes_config(),
            "input": template.generate_input_config(),
            "output": template.generate_output_config(),
        }

        # Generate main settings file with format-specific writer
        settings_file = self.output_path / self._settings_filename

        if self.config_format == ConfigFormat.YAML:
            self._write_yaml_file(settings_file, template.generate_settings_json())
        elif self.config_format == ConfigFormat.TOML:
            self._write_toml_file(settings_file, template.generate_settings_json())
        else:
            self._write_json_file(settings_file, template.generate_settings_json())

        # Generate configuration files for each environment
        environments = ["base", "dev", "sandbox", "prod"]

        # Add developer sandbox environments
        if developer_sandboxes:
            environments.extend([f"sandbox_{dev}" for dev in developer_sandboxes])

        for env in environments:
            config_dir = self.output_path / "config" / (env if env != "base" else "")

            for config_name, config_data in configs.items():
                # Only generate pipelines/nodes for base environment
                if env != "base" and config_name in ["pipelines", "nodes"]:
                    continue

                file_path = config_dir / f"{config_name}{self._file_extension}"
                self._write_config_file(file_path, config_data)

    def _write_config_file(self, file_path: Path, config_data: Dict[str, Any]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer(file_path, config_data)

    def _write_yaml_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Write YAML file."""
        if not HAS_YAML:
            raise TemplateError("PyYAML not available. Install with: pip install PyYAML")

        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, indent=2)

    def _write_json_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Write JSON file."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _write_toml_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Write TOML file."""
        try:
            import tomli_w  # type: ignore
        except ImportError:
            raise TemplateError(
                "TOML template generation requires 'tomli_w'. Install with: pip install tomli-w"
            )
        with open(file_path, "wb") as f:
            tomli_w.dump(data, f)

    def _generate_sample_code(self, template_type: Optional[TemplateType] = None) -> None:
        """Generate the sample pipeline modules for the chosen template type."""
        if template_type == TemplateType.STREAMING_CORE:
            self._generate_streaming_sample_code()
            return
        if template_type == TemplateType.HYBRID:
            self._generate_hybrid_sample_code()
            return
        if template_type == TemplateType.ML_READY:
            self._generate_ml_sample_code()
        self._generate_etl_sample_code()

    def _seed_json_stream_source(self, rel_dir: str) -> None:
        """Seed a directory with sample JSON records for the file-stream source.

        The ``availableNow`` trigger processes exactly what is present at start, so
        these files make the streaming sample produce output on the first run.
        """
        source_dir = self.output_path / rel_dir
        source_dir.mkdir(parents=True, exist_ok=True)
        rows = [
            {"id": 1, "value": 10.5, "event_ts": "2025-01-01T00:00:00"},
            {"id": 2, "value": 20.0, "event_ts": "2025-01-01T00:01:00"},
            {"id": 3, "value": 30.25, "event_ts": "2025-01-01T00:02:00"},
        ]
        for i, row in enumerate(rows):
            (source_dir / f"events_{i}.json").write_text(json.dumps(row) + "\n", encoding="utf-8")

    def _generate_streaming_sample_code(self) -> None:
        """Write pipelines/streaming.py (transform registry) and seed the stream source."""
        streaming_code = '''"""
Streaming transforms for the file-stream → Parquet demo.

Streaming transforms are looked up by key on a TransformationRegistry. Ducta
calls ``register_transforms(registry)`` at runtime, then resolves each streaming
node's ``function: {module: pipelines.streaming, key: <key>}`` against it. Each
transform takes a streaming DataFrame and returns a streaming DataFrame.

To use a live Kafka source instead of the file stream, change the node's input in
config/nodes.yaml to ``format: kafka`` with ``options.kafka.bootstrap.servers`` and
``options.subscribe``; the transform below is unchanged.
"""
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def enrich(df: DataFrame) -> DataFrame:
    """Add a processing timestamp to each streamed row (passthrough otherwise)."""
    return df.withColumn("ingested_at", F.current_timestamp())


def register_transforms(registry) -> None:
    """Register this module's streaming transforms (called by Ducta at runtime)."""
    registry.register("enrich", enrich)
'''
        self._write_text_file(self.output_path / "pipelines" / "streaming.py", streaming_code)
        self._seed_json_stream_source(StreamingCoreTemplate.STREAM_SOURCE)

    def _generate_hybrid_sample_code(self) -> None:
        """Write pipelines/hybrid.py: a batch prepare node + a streaming enrich transform."""
        hybrid_code = '''"""
Hybrid pipeline sample: a batch stage feeds a streaming stage.

- ``prepare`` is a normal batch node (called with the loaded input DataFrame plus
  start_date/end_date) that lands rows as Parquet in the bronze layer.
- ``enrich`` is a streaming transform (registered via register_transforms) that a
  streaming node applies to a file stream reading that same bronze directory.
"""
from typing import Any, Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def prepare(
    source_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Batch stage: pass the source rows through to the bronze layer."""
    return source_data


def enrich(df: DataFrame) -> DataFrame:
    """Streaming stage: add a processing timestamp to each streamed row."""
    return df.withColumn("ingested_at", F.current_timestamp())


def register_transforms(registry) -> None:
    """Register the streaming transform used by the hybrid pipeline's stream node."""
    registry.register("enrich", enrich)
'''
        self._write_text_file(self.output_path / "pipelines" / "hybrid.py", hybrid_code)

    def _generate_ml_sample_code(self) -> None:
        """Generate a best-practice ML training module for the ml_ready template."""
        ml_code = '''"""
ML Training Pipeline (best-practice skeleton)

This sample encodes the habits every Ducta training node should keep:

1. Declarative split: the criteria (method, sizes, columns) live versioned
   in the pipeline config and arrive via ml_context["split"]; the node only
   applies them with ducta.mlrun.split.split_dataframe. Code never
   hardcodes how data is partitioned.
2. Reproducible seed: random_state comes from ml_context["node_seed"]
   (derived from global_settings.random_seed), never unseeded.
3. No leakage: anything that LEARNS from data (imputers, scalers,
   encoders) is fit on train only, then applied to the other splits.
4. Hyperparameters from versioned config (ml_context["hyperparams"]),
   never hardcoded.
5. Selection on validation, NEVER on test. Model choice and hyperparameter
   comparison use the validation split (or cross-validation folds when
   ml_context["cv_folds"] is set). The test set is touched exactly once,
   at the end, to report an unbiased estimate — using it to choose
   anything silently invalidates that estimate.
6. Baseline comparison: metrics are reported relative to a trivial
   baseline (majority class), and any registration gate is relative
   (f1 > baseline_f1 + margin), not an absolute threshold.

Requires scikit-learn: pip install scikit-learn
"""
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:
    # Typed context for autocompletion (ml_context.node_seed, .hyperparams, .split…).
    # MLNodeContext is also a Mapping, so ml_context["split"] / .get(...) still work.
    from ducta.core.ml_context import MLNodeContext

TARGET_COLUMN = "target"  # change to your label column


def _fit_and_score(train_df, eval_df, params, seed):
    """Fit on train_df, score on eval_df. Returns (model, f1, baseline_f1).

    Every learned transformation is fit on train_df only — that is what keeps
    eval_df an honest estimate rather than a number the model already saw.
    """
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import f1_score

    X_train = train_df.drop(TARGET_COLUMN, axis=1)
    y_train = train_df[TARGET_COLUMN]
    X_eval = eval_df.drop(TARGET_COLUMN, axis=1)
    y_eval = eval_df[TARGET_COLUMN]

    # Anti-leakage: fill values are LEARNED from train only, then applied
    # everywhere. Same rule for scalers, encoders and feature selection.
    fill_values = X_train.median(numeric_only=True)
    X_train = X_train.fillna(fill_values)
    X_eval = X_eval.fillna(fill_values)

    baseline = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    baseline_f1 = f1_score(y_eval, baseline.predict(X_eval))

    model = RandomForestClassifier(**params, random_state=seed).fit(X_train, y_train)
    f1 = f1_score(y_eval, model.predict(X_eval))
    return model, f1, baseline_f1


def train(
    clean_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ml_context: "Optional[MLNodeContext]" = None,
) -> Any:
    """Train a model with declarative split, config-driven params and baseline gate."""
    from ducta.mlrun import kfold_splits, persist_model, split_dataframe

    ml_context = ml_context or {}

    # Hyperparameters: versioned config first, safe defaults for local runs
    params = {"n_estimators": 100, "max_depth": 5, **(ml_context.get("hyperparams") or {})}
    seed = ml_context.get("node_seed", 42)

    df = clean_data.toPandas() if hasattr(clean_data, "toPandas") else clean_data

    # Split criteria from the pipeline config ('split' block); the fallback
    # only covers local runs without one. Ask for a validation split so
    # selection never touches test.
    split_cfg = ml_context.get("split") or {
        "method": "stratified",
        "stratify_col": TARGET_COLUMN,
        "test_size": 0.2,
        "val_size": 0.2,
    }
    parts = split_dataframe(df, split_cfg, default_seed=seed)

    # (train, val, test) when the config sets val_size, else (train, test).
    if len(parts) == 3:
        train_df, val_df, test_df = parts
    else:
        train_df, test_df = parts
        val_df = None
        logger.warning(
            "split has no 'val_size': falling back to selecting on test, which "
            "invalidates the final estimate. Add 'val_size' to the pipeline's "
            "split block."
        )

    # --- Selection phase: validation or cross-validation, never test --------
    cv_folds = ml_context.get("cv_folds")
    if cv_folds and val_df is not None:
        # Averaging over folds makes selection far less sensitive to one
        # lucky partition. Folds come from train+val so test stays untouched.
        import pandas as pd

        selection_pool = pd.concat([train_df, val_df])
        scores, baseline_scores = [], []
        for fold_train, fold_val in kfold_splits(
            selection_pool, split_cfg, n_splits=int(cv_folds), default_seed=seed
        ):
            _, fold_f1, fold_baseline_f1 = _fit_and_score(fold_train, fold_val, params, seed)
            scores.append(fold_f1)
            baseline_scores.append(fold_baseline_f1)
        val_f1 = sum(scores) / len(scores)
        baseline_f1 = sum(baseline_scores) / len(baseline_scores)
        logger.info(
            "{}-fold CV f1={:.4f} (per fold: {})",
            cv_folds,
            val_f1,
            ", ".join(f"{s:.4f}" for s in scores),
        )
    elif val_df is not None:
        _, val_f1, baseline_f1 = _fit_and_score(train_df, val_df, params, seed)
        logger.info("validation f1={:.4f} | baseline_f1={:.4f}", val_f1, baseline_f1)
    else:
        _, val_f1, baseline_f1 = _fit_and_score(train_df, test_df, params, seed)

    # --- Final model: refit on everything except test, score on test once ---
    if val_df is not None:
        import pandas as pd

        fit_df = pd.concat([train_df, val_df])
    else:
        fit_df = train_df
    model, test_f1, test_baseline_f1 = _fit_and_score(fit_df, test_df, params, seed)

    logger.info(
        "val_f1={:.4f} | test_f1={:.4f} | baseline_f1={:.4f} | lift={:.4f}",
        val_f1,
        test_f1,
        baseline_f1,
        val_f1 - baseline_f1,
    )

    # Log to the pipeline-level experiment run if MLOps is configured
    mlops = ml_context.get("mlops_context")
    run_id = ml_context.get("mlops_run_id")
    if mlops and run_id and getattr(mlops, "experiment_tracker", None):
        tracker = mlops.experiment_tracker
        split_params = {f"split_{k}": v for k, v in dict(split_cfg).items() if v is not None}
        for key, value in {**params, "seed": seed, **split_params}.items():
            tracker.log_parameter(run_id, key, value)
        # val_f1 is the selection metric: point sweeps and promotion policies
        # at it. test_f1 is reported for the record, never to choose with.
        tracker.log_metric(run_id, "val_f1", val_f1)
        tracker.log_metric(run_id, "baseline_f1", baseline_f1)
        tracker.log_metric(run_id, "val_f1_lift", val_f1 - baseline_f1)
        tracker.log_metric(run_id, "test_f1", test_f1)

    if val_f1 <= baseline_f1:
        logger.warning(
            "Model does NOT beat the trivial baseline ({:.4f} <= {:.4f}) - "
            "it adds no value yet. Review features/hyperparams before promoting.",
            val_f1,
            baseline_f1,
        )

    # Persist the model reproducibly: the registry versions it by design, with a
    # run/version-stamped local file as fallback. Passing X= records the feature
    # contract on the version, so the promotion gate can detect schema drift
    # against whatever is currently in Production. Returning the artifact dict
    # makes the executor record the URI and skip the standard output save.
    return persist_model(
        model,
        ml_context,
        name="demo_model",
        framework="sklearn",
        metrics={
            "val_f1": val_f1,
            "baseline_f1": baseline_f1,
            "test_f1": test_f1,
            "test_baseline_f1": test_baseline_f1,
        },
        hyperparameters=params,
        X=fit_df.drop(TARGET_COLUMN, axis=1),
        y=fit_df[TARGET_COLUMN],
    )
'''
        ml_file = self.output_path / "pipelines" / "ml.py"
        self._write_text_file(ml_file, ml_code)

    def _generate_etl_sample_code(self) -> None:
        """Generate a single, focused ETL pipeline module."""
        etl_code = '''"""
Medallion ETL: bronze -> silver -> gold

Each layer does real work, and the quality checks in ``config/nodes.yaml``
verify that it did. The sample data ships deliberately dirty (12 rows with a
missing amount, 8 verbatim duplicates), so:

    bronze  508 rows   raw, exactly as it arrived
    silver  488 rows   deduplicated and missing amounts dropped
    gold      5 rows   one row per category

The silver checks (null_rate, duplicates) pass *because* `transform` cleaned the
data. Break `transform` and the quality gate blocks the run before anything is
written -- that is the point of the demo, and you can try it: comment out the
dropna() below and re-run.
"""
from typing import Any, Optional

from loguru import logger

#: Gold aggregates by this column. Change both to match your own data.
GROUP_COLUMN = "category"
VALUE_COLUMN = "amount"


def _row_count(df: Any) -> int:
    """Row count for a Spark or pandas DataFrame."""
    return df.count() if hasattr(df, "rdd") else len(df)


def extract(
    source_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Bronze: land the source exactly as it arrived.

    Deliberately does not clean anything. The bronze layer's job is to be a
    faithful, replayable copy of the source -- if you clean here, you can never
    prove what the source actually said.

    Ducta has already loaded ``source_data`` per ``config/input.yaml`` (format,
    header, inferSchema), and will write the return value per
    ``config/output.yaml``. You only write the transformation.
    """
    if source_data is None:
        raise ValueError("No data provided from source")

    logger.info("Bronze: landed {:,} raw rows", _row_count(source_data))
    return source_data


def transform(
    raw_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Silver: make the data trustworthy.

    Two operations, both schema-agnostic so this node also serves the `train`
    pipeline in the ml_ready template:

      1. drop exact duplicate rows
      2. drop rows with a missing value in any column

    The ``data_quality`` checks on this node assert the result: null_rate 0 and
    no duplicate order_id. They are not decoration -- they fail if this function
    stops doing its job, and the gate stops the run before gold is written.
    """
    if raw_data is None:
        raise ValueError("raw_data cannot be None")

    before = _row_count(raw_data)

    deduplicated = (
        raw_data.dropDuplicates() if hasattr(raw_data, "dropDuplicates") else raw_data.drop_duplicates()
    )
    after_dedup = _row_count(deduplicated)

    cleaned = deduplicated.dropna()
    after = _row_count(cleaned)

    logger.info(
        "Silver: {:,} -> {:,} rows ({:,} duplicates, {:,} incomplete)",
        before,
        after,
        before - after_dedup,
        after_dedup - after,
    )
    return cleaned


def load(
    clean_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Gold: aggregate into something a consumer would actually query.

    One row per ``GROUP_COLUMN`` with the order count and the total/average
    ``VALUE_COLUMN``. This is where the medallion pattern pays off: gold is
    small, stable and shaped for reading, while silver stays row-level.
    """
    if clean_data is None:
        raise ValueError("clean_data cannot be None")

    columns = list(getattr(clean_data, "columns", []))
    if GROUP_COLUMN not in columns or VALUE_COLUMN not in columns:
        # Keeps the node working when the template is pointed at other data
        # (the ml_ready sample, or your own) before you have adjusted the two
        # constants at the top of this file.
        logger.warning(
            "Gold: no '{}'/'{}' columns in {}; passing silver through unaggregated. "
            "Set GROUP_COLUMN/VALUE_COLUMN in pipelines/etl.py to aggregate.",
            GROUP_COLUMN,
            VALUE_COLUMN,
            columns,
        )
        return clean_data

    if hasattr(clean_data, "rdd"):  # Spark
        from pyspark.sql import functions as F

        aggregated = (
            clean_data.groupBy(GROUP_COLUMN)
            .agg(
                F.count(F.lit(1)).alias("order_count"),
                F.round(F.sum(VALUE_COLUMN), 2).alias("total_amount"),
                F.round(F.avg(VALUE_COLUMN), 2).alias("avg_amount"),
            )
            .orderBy(GROUP_COLUMN)
        )
    else:  # pandas
        aggregated = (
            clean_data.groupby(GROUP_COLUMN)[VALUE_COLUMN]
            .agg(order_count="count", total_amount="sum", avg_amount="mean")
            .round(2)
            .reset_index()
            .sort_values(GROUP_COLUMN)
        )

    logger.info("Gold: aggregated into {:,} rows by '{}'", _row_count(aggregated), GROUP_COLUMN)
    return aggregated
'''

        etl_file = self.output_path / "pipelines" / "etl.py"
        self._write_text_file(etl_file, etl_code)

        # Generate custom checks example
        checks_dir = self.output_path / "pipelines" / "checks"
        checks_dir.mkdir(parents=True, exist_ok=True)
        (checks_dir / "__init__.py").touch()

        custom_checks_code = '''"""
Custom Quality Checks
=====================
Add your project-specific data quality checks here.

Steps to activate a custom check
---------------------------------
1. Define a class that inherits from ``BaseQualityCheck`` and decorate it with
   ``@register_check("your_check_name")``.
2. Implement the ``run()`` method and return a ``CheckResult``.
3. Add the module path to ``quality.extensions`` in
   ``config/global_settings.yaml``:

   .. code-block:: yaml

       quality:
         extensions:
           - pipelines.checks.custom_checks

4. Reference the check in any node in ``config/nodes.yaml``:

   .. code-block:: yaml

       my_node:
         data_quality:
           enabled: true
           checks:
             positive_values:
               enabled: true
               column: amount

(Scaffolds generated with ``--format toml`` or ``--format json`` use the same
keys in that format.)
"""
from ducta.check import (
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    register_check,
)


# ---------------------------------------------------------------------------
# Example 1: Single-column positivity check
# ---------------------------------------------------------------------------
@register_check("positive_values")
class PositiveValuesCheck(BaseQualityCheck):
    """Fail if any value in *column* is <= 0.

    Config keys
    -----------
    column : str
        Name of the column to check (required).
    severity : str
        "ERROR" or "WARNING" (default: "ERROR").
    """

    def __init__(self):
        super().__init__("positive_values", CheckSeverity.ERROR)

    def run(self, df, config, adapter, context_datasets=None):
        column = getattr(config, "column", None)
        if not column:
            return CheckResult(
                check_name=self.name,
                passed=False,
                severity=CheckSeverity.ERROR,
                message="'column' is required for positive_values check",
            )

        try:
            # Works with Pandas, Polars, and Spark via DFAdapter helpers
            neg_count = adapter.filter_where(f"{column} <= 0")
            if neg_count > 0:
                return CheckResult(
                    check_name=self.name,
                    passed=False,
                    severity=self.severity,
                    message=f"Column '{column}' has {neg_count} non-positive values",
                    details={"column": column, "non_positive_count": neg_count},
                )
            return CheckResult(
                check_name=self.name,
                passed=True,
                severity=self.severity,
                message=f"All values in '{column}' are positive",
            )
        except Exception as exc:
            return CheckResult(
                check_name=self.name,
                passed=False,
                severity=CheckSeverity.ERROR,
                message=f"positive_values check error: {exc}",
                details={"error": str(exc)},
            )


# ---------------------------------------------------------------------------
# Example 2: Referential check between two columns
# ---------------------------------------------------------------------------
# @register_check("email_domain")
# class EmailDomainCheck(BaseQualityCheck):
#     """Verify email values belong to expected domains.
#
#     Config keys
#     -----------
#     column : str
#         Email column to check.
#     allowed_domains : list[str]
#         List of allowed domain strings (e.g. ["example.com"]).
#     """
#
#     def __init__(self):
#         super().__init__("email_domain", CheckSeverity.WARNING)
#
#     def run(self, df, config, adapter, context_datasets=None):
#         column = getattr(config, "column", "email")
#         allowed = getattr(config, "allowed_domains", [])
#         ...
'''
        custom_file = checks_dir / "custom_checks.py"
        self._write_text_file(custom_file, custom_checks_code)

    def _generate_project_files(self, template: MedallionBasicTemplate) -> None:
        """Generate essential project files only."""
        # README.md
        readme_content = f"""# {template.project_name}

A medallion ETL pipeline built with **Ducta**.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline etl
```

The sample data is **deliberately dirty** — 12 rows with a missing `amount` and
8 verbatim duplicates — so the run has something real to do:

```
bronze  508 rows   raw, exactly as it arrived
silver  488 rows   deduplicated, incomplete rows dropped
gold      5 rows   one row per category
```

## Then prove what happened

```bash
ducta certify list                       # every run recorded here
ducta certify show   --run-id <run-id>   # what ran, on which data
ducta certify verify --run-id <run-id>   # tamper check
```

The certificate records a content fingerprint and row count for every dataset at
every layer, so the three row counts above are evidence, not log output. Compare
two runs with `ducta certify diff <run-a> <run-b>`.

## See the quality gate work

`config/nodes.yaml` asserts on the silver layer that `amount` has no nulls and
`order_id` has no duplicates, with `quality_gate.max_errors: 0`. Those checks
pass because `transform` cleaned the data. To watch them fail:

1. Open `pipelines/etl.py` and comment out the `.dropna()` line in `transform`.
2. Re-run `ducta start --env dev --pipeline etl`.

The gate blocks, `load` is skipped, and **gold is never written** — the checks
run before the write, so bad data does not reach storage. Undo the change to go
back to a passing run.

## Project structure

```
{template.project_name}/
├── config/
│   ├── global_settings.yaml  # project settings, quality profiles
│   ├── pipelines.yaml        # which nodes make up which pipeline
│   ├── nodes.yaml            # per-node I/O, checks and gates
│   ├── input.yaml            # where data is read from
│   ├── output.yaml           # where data is written to
│   └── dev/ sandbox/ prod/   # per-environment overrides
├── pipelines/
│   ├── etl.py                # your transformations (plain functions)
│   └── checks/custom_checks.py
├── data/
│   ├── input.csv             # sample source
│   └── dev/                  # bronze/ silver/ gold/ written per environment
└── .ducta/runs/              # run certificates
```

## What to change first

1. Point `config/input.yaml` at your own data.
2. Rewrite the three functions in `pipelines/etl.py`. They are ordinary Python
   taking a DataFrame and returning one — no decorators, no framework types.
3. Update the checks in `config/nodes.yaml` to assert what *your* transform
   guarantees, and set `GROUP_COLUMN`/`VALUE_COLUMN` at the top of `etl.py`.

## Useful commands

```bash
ducta config list-pipelines                  # what is defined here
ducta start --env dev --pipeline etl --validate-only   # config check, no Spark
ducta start --env dev --pipeline etl --log-level DEBUG
ducta server start --port 8000               # web UI (needs the `api` extra)
```

Ducta is alpha — see the
[CHANGELOG](https://github.com/faustinolopezramos/ducta/blob/main/CHANGELOG.md)
before depending on it. Docs: https://github.com/faustinolopezramos/ducta

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        readme_file = self.output_path / "README.md"
        self._write_text_file(readme_file, readme_content)

        # requirements.txt - minimal but complete
        # `ducta[spark]` rather than ducta + a loose pyspark pin: the extra is
        # what the project actually declares as compatible, and pinning pyspark
        # separately invites a combination Ducta was never tested against.
        requirements = """ducta[spark]>=0.1.1
"""
        requirements_file = self.output_path / "requirements.txt"
        self._write_text_file(requirements_file, requirements)

        # .gitignore
        gitignore = """__pycache__/
*.py[cod]
*.so
.Python
env/
venv/
ENV/
build/
dist/
*.egg-info/
.eggs/

# Data
data/raw/
data/processed/
!data/input.csv

# Logs
logs/
*.log

# IDE
.vscode/
.idea/
*.swp
.DS_Store

# Testing
.coverage
.pytest_cache/
htmlcov/

# Spark
metastore_db/
spark-warehouse/
"""
        gitignore_file = self.output_path / ".gitignore"
        self._write_text_file(gitignore_file, gitignore)

        sample_data = template.get_sample_data()
        sample_data_file = self.output_path / "data" / "input.csv"
        self._write_text_file(sample_data_file, sample_data)

    def _write_text_file(self, file_path: Path, content: str) -> None:
        """Write text file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)


class TemplateCommand:
    """Handles the --template command functionality."""

    def __init__(self):
        self.generator = None

    def handle_template_command(
        self,
        template_type: Optional[str] = None,
        project_name: Optional[str] = None,
        output_path: Optional[str] = None,
        config_format: str = "yaml",
        create_sample_code: bool = True,
        list_templates: bool = False,
        interactive: bool = False,
        sandbox_developers: Optional[List[str]] = None,
    ) -> int:
        """Handle template generation command."""
        try:
            if list_templates:
                return self._list_templates()

            if interactive:
                return self._interactive_generation()

            validation_error = self._validate_inputs(template_type, project_name)
            if validation_error:
                return validation_error

            validation_error = self._validate_sandbox_developers(sandbox_developers)
            if validation_error:
                return validation_error

            return self._generate_template(
                template_type,
                project_name,
                output_path,
                config_format,
                create_sample_code,
                sandbox_developers,
            )

        except TemplateError as e:
            logger.error("Template error: {}", e)
            return e.exit_code
        except Exception as e:
            logger.error("Unexpected error: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _list_templates(self) -> int:
        """List all available templates."""
        templates = TemplateFactory.list_available_templates()

        logger.info("Available template types:")
        for template in templates:
            logger.info("  {:20} - {}", template["type"], template["name"])
            logger.info("  {}   {}", " " * 20, template["description"])
            logger.info("")

        logger.info("Usage:")
        logger.info("  ducta template --template <type> --project-name <name> [options]")
        logger.info("")
        logger.info("Examples:")
        logger.info("  ducta template --template medallion_basic --project-name my_pipeline")
        logger.info(
            "  ducta template --template medallion_basic --project-name my_pipeline --format json"
        )

        return ExitCode.SUCCESS.value

    def _validate_inputs(
        self, template_type: Optional[str], project_name: Optional[str]
    ) -> Optional[int]:
        """Validate required command-line inputs."""
        if not template_type or not project_name:
            logger.error("Template type and project name are required")
            logger.info("Use --list-templates to see available templates")
            return ExitCode.VALIDATION_ERROR.value

        error = self._validate_project_name(project_name)
        if error:
            return error

        return None

    def _validate_project_name(self, project_name: str) -> Optional[int]:
        """Validate project name."""
        if not project_name:
            logger.error("Project name cannot be empty")
            return ExitCode.VALIDATION_ERROR.value
        if not _VALID_NAME_RE.match(project_name):
            logger.error(
                "Invalid project name '{}'. Use only letters, numbers, underscores, and hyphens.",
                project_name,
            )
            return ExitCode.VALIDATION_ERROR.value
        return None

    def _validate_sandbox_developers(
        self, sandbox_developers: Optional[List[str]]
    ) -> Optional[int]:
        """Validate --sandbox-developers entries (each becomes a directory name)."""
        for dev in sandbox_developers or []:
            if not dev or not _VALID_NAME_RE.match(dev):
                logger.error(
                    "Invalid sandbox developer name '{}'. Use only letters, numbers, "
                    "underscores, and hyphens.",
                    dev,
                )
                return ExitCode.VALIDATION_ERROR.value
        return None

    def _validate_config_format(self, format_str: str) -> Optional[int]:
        """Validate config format string."""
        valid_formats = ["yaml", "json", "toml"]
        if format_str not in valid_formats:
            logger.error(
                "Invalid format '{}'. Use one of: {}", format_str, ", ".join(valid_formats)
            )
            return ExitCode.VALIDATION_ERROR.value
        return None

    def _interactive_generation(self) -> int:
        """Interactive template generation."""
        try:
            templates = TemplateFactory.list_available_templates()
            selected_template = self._select_template(templates)
            if selected_template is None:
                return ExitCode.GENERAL_ERROR.value

            project_name = input("Enter project name: ").strip()
            validation_error = self._validate_project_name(project_name)
            if validation_error:
                return validation_error

            default_output = f"./{project_name}"
            output_path = (
                input(f"Output path (default: {default_output}): ").strip() or default_output
            )

            valid_formats = ["yaml", "json", "toml"]
            print(f"\nConfig formats: {', '.join(valid_formats)}")
            config_format = self._prompt_config_format()
            if config_format is None:
                return ExitCode.GENERAL_ERROR.value

            create_code = input("Generate sample code? (Y/n): ").strip().lower()
            create_sample_code = create_code != "n"

            return self._generate_template(
                selected_template["type"],
                project_name,
                output_path,
                config_format,
                create_sample_code,
            )

        except Exception as e:
            logger.error("Interactive generation failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _select_template(self, templates: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Prompt the user to select a template from the list; return None if cancelled."""
        print("\nAvailable templates:")
        for i, template in enumerate(templates, 1):
            print(f"  {i}. {template['name']} - {template['description']}")
        while True:
            try:
                choice = input(f"\nSelect template (1-{len(templates)}): ").strip()
                if choice.isdigit():
                    index = int(choice) - 1
                    if 0 <= index < len(templates):
                        return templates[index]
                # Invalid selection -> prompt again
                print("Invalid selection. Please try again or press Ctrl+C to cancel.")
            except (KeyboardInterrupt, EOFError):
                logger.info(_TEMPLATE_CANCELLED_MSG)
                return None

    def _prompt_config_format(self) -> Optional[str]:
        """Prompt for config format and validate; return None on validation error."""
        config_format = input("Config format (default: yaml): ").strip().lower()
        if not config_format:
            return "yaml"
        validation_error = self._validate_config_format(config_format)
        if validation_error:
            return None
        return config_format

    def _generate_template(
        self,
        template_type: str,
        project_name: str,
        output_path: Optional[str],
        config_format: str,
        create_sample_code: bool,
        sandbox_developers: Optional[List[str]] = None,
    ) -> int:
        """Generate template with specified parameters."""
        try:
            try:
                template_enum = TemplateType(template_type)
            except ValueError:
                available = [t.value for t in TemplateType]
                logger.error("Invalid template type: {}", template_type)
                logger.info("Available types: {}", ", ".join(available))
                return ExitCode.VALIDATION_ERROR.value

            try:
                format_enum = ConfigFormat(config_format)
            except ValueError:
                available = [f.value for f in ConfigFormat]
                logger.error("Invalid config format: {}", config_format)
                logger.info("Available formats: {}", ", ".join(available))
                return ExitCode.VALIDATION_ERROR.value

            if not output_path:
                output_path = f"./{project_name}"

            output_dir = Path(output_path)

            if output_dir.exists() and any(output_dir.iterdir()):
                logger.warning("Directory {} already exists and is not empty", output_dir)
                logger.info(_TEMPLATE_CANCELLED_MSG)
                return ExitCode.VALIDATION_ERROR.value

            self.generator = TemplateGenerator(output_dir, format_enum)
            self.generator.generate_project(
                template_enum, project_name, create_sample_code, sandbox_developers
            )

            self._show_success_message(project_name, output_dir)

            return ExitCode.SUCCESS.value

        except Exception as e:
            logger.error("Template generation failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _show_success_message(self, project_name: str, output_dir: Path) -> None:
        """Show success message with next steps."""
        logger.success("✅ Project '{}' created successfully!", project_name)
        logger.info("📁 Location: {}", output_dir.absolute())
        logger.info("\n📋 Next steps:")
        logger.info("1️⃣  cd {}", output_dir)
        logger.info("2️⃣  pip install -r requirements.txt")
        logger.info("3️⃣  Update config/input.yaml and config/output.yaml for your data")
        logger.info("4️⃣  Customize pipelines/etl.py for your business logic")
        logger.info("5️⃣  Update config/dev/input.yaml and output.yaml for dev environment")

        logger.info("\n🚀 Quick start:")
        logger.info("   # Run the ETL pipeline")
        logger.info("   ducta start -e dev -p etl")
        logger.info("")
        logger.info("   # Run specific node")
        logger.info("   ducta start -e dev -p etl -n extract")
        logger.info("")
        logger.info("   # Debug mode")
        logger.info("   ducta start -e dev -p etl --log-level DEBUG")
        logger.info("")
        logger.info("   # Validate config")
        logger.info("   ducta start -e dev -p etl --validate-only")

        logger.info("\n✨ Features ready to use:")
        logger.info("   ✓ Multi-format I/O (CSV → Parquet → CSV)")
        logger.info("   ✓ Automatic data loading and saving")
        logger.info("   ✓ Data validation and transformation")
        logger.info("   ✓ Multi-environment configs (dev/sandbox/prod)")
        logger.info("   ✓ Structured logging with loguru")
        logger.info("   ✓ Dependency management between nodes")

        logger.info("\n📖 More info: Check README.md or run 'Ducta --help'")


def handle_template_command(parsed_args) -> int:
    """Handle template command execution from CLI."""
    template_cmd = TemplateCommand()

    return template_cmd.handle_template_command(
        template_type=parsed_args.template,
        project_name=parsed_args.project_name,
        output_path=parsed_args.output_path,
        config_format=parsed_args.format,
        create_sample_code=not parsed_args.no_sample_code,
        list_templates=parsed_args.list_templates,
        sandbox_developers=getattr(parsed_args, "sandbox_developers", None),
    )
