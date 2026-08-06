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
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

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

# `--project-name` becomes a directory name (default output path) and
# `--sandbox-developers` entries become `config/sandbox_<dev>` directory
# names — both were used unvalidated, so e.g. `--project-name ../../etc` or
# `--sandbox-developers ../../tmp/evil` escaped the intended output directory
# via mkdir(parents=True). Restrict both to a safe identifier charset.
_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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
        """Three nodes demonstrating Ducta's core capabilities."""
        return {
            "extract": {
                "description": "Extract: Load data from source",
                "module": PIPELINES_ETL_MODULE,
                "function": "extract",
                "input": ["source_data"],
                "output": ["bronze.etl.raw_data"],
                "dependencies": [],
                "sanity_checks": {
                    "enabled": True,
                    "fail_fast": True,
                    "profile": "default",
                    "checks": {
                        "null_rate": {
                            "enabled": True,
                            "threshold": 0.10,
                        },
                    },
                },
            },
            "transform": {
                "description": "Transform: Validate and clean data",
                "module": PIPELINES_ETL_MODULE,
                "function": "transform",
                "input": ["bronze.etl.raw_data"],
                "output": ["silver.etl.clean_data"],
                "dependencies": ["extract"],
                "sanity_checks": {
                    "enabled": True,
                    "fail_fast": True,
                    "checks": {
                        "empty_dataset": {"enabled": True},
                        "schema": {
                            "enabled": False,
                            "expected_columns": [],
                        },
                    },
                },
                "data_quality": {
                    "enabled": True,
                    "fail_fast": False,
                    "checks": {
                        "row_count": {
                            "enabled": True,
                            "min": 1,
                        },
                        "drift_detection": {
                            "enabled": False,
                            "columns": [],
                        },
                    },
                },
            },
            "load": {
                "description": "Load: Persist processed data",
                "module": PIPELINES_ETL_MODULE,
                "function": "load",
                "input": ["silver.etl.clean_data"],
                "output": ["gold.etl.final_output"],
                "dependencies": ["transform"],
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

    def get_sample_data(self) -> str:
        """CSV seeded into data/input.csv. Overridden per template for its node code."""
        return (
            "id,name,value,date\n"
            "1,Product A,150,2025-01-01\n"
            "2,Product B,200,2025-01-02\n"
            "3,Product C,180,2025-01-03\n"
            "4,Product D,220,2025-01-04\n"
            "5,Product E,195,2025-01-05\n"
        )


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

    def generate_nodes_config(self) -> Dict[str, Any]:
        nodes = super().generate_nodes_config()
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
            "metrics": ["f1", "baseline_f1"],
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

This sample encodes the five habits every Ducta training node should keep:

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
5. Baseline comparison: metrics are reported relative to a trivial
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


def train(
    clean_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ml_context: "Optional[MLNodeContext]" = None,
) -> Any:
    """Train a model with declarative split, config-driven params and baseline gate."""
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import f1_score

    from ducta.mlrun import persist_model, split_dataframe

    ml_context = ml_context or {}

    # Hyperparameters: versioned config first, safe defaults for local runs
    params = {"n_estimators": 100, "max_depth": 5, **(ml_context.get("hyperparams") or {})}
    seed = ml_context.get("node_seed", 42)

    df = clean_data.toPandas() if hasattr(clean_data, "toPandas") else clean_data

    # Split criteria from the pipeline config ('split' block); the fallback
    # only covers local runs without one. Returns (train, test) or
    # (train, val, test) when the config sets val_size — tune on val, never
    # on test.
    split_cfg = ml_context.get("split") or {
        "method": "stratified",
        "stratify_col": TARGET_COLUMN,
        "test_size": 0.2,
    }
    parts = split_dataframe(df, split_cfg, default_seed=seed)
    train_df, test_df = parts[0], parts[-1]

    X_train = train_df.drop(TARGET_COLUMN, axis=1)
    y_train = train_df[TARGET_COLUMN]
    X_test = test_df.drop(TARGET_COLUMN, axis=1)
    y_test = test_df[TARGET_COLUMN]

    # Anti-leakage: fill values are LEARNED from train only, then applied
    # everywhere. Same rule for scalers, encoders and feature selection.
    fill_values = X_train.median(numeric_only=True)
    X_train = X_train.fillna(fill_values)
    X_test = X_test.fillna(fill_values)

    # Trivial baseline: the floor any model must beat to add value
    baseline = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    baseline_f1 = f1_score(y_test, baseline.predict(X_test))

    model = RandomForestClassifier(**params, random_state=seed).fit(X_train, y_train)
    f1 = f1_score(y_test, model.predict(X_test))

    logger.info("f1={:.4f} | baseline_f1={:.4f} | lift={:.4f}", f1, baseline_f1, f1 - baseline_f1)

    # Log to the pipeline-level experiment run if MLOps is configured
    mlops = ml_context.get("mlops_context")
    run_id = ml_context.get("mlops_run_id")
    if mlops and run_id and getattr(mlops, "experiment_tracker", None):
        tracker = mlops.experiment_tracker
        split_params = {f"split_{k}": v for k, v in dict(split_cfg).items() if v is not None}
        for key, value in {**params, "seed": seed, **split_params}.items():
            tracker.log_parameter(run_id, key, value)
        tracker.log_metric(run_id, "f1", f1)
        tracker.log_metric(run_id, "baseline_f1", baseline_f1)
        tracker.log_metric(run_id, "f1_lift", f1 - baseline_f1)

    if f1 <= baseline_f1:
        logger.warning(
            "Model does NOT beat the trivial baseline ({:.4f} <= {:.4f}) - "
            "it adds no value yet. Review features/hyperparams before promoting.",
            f1,
            baseline_f1,
        )

    # Persist the model reproducibly: the registry versions it by design, with a
    # run/version-stamped local file as fallback. Returning the artifact dict makes
    # the executor record the URI and skip the standard output save. Never returns a
    # raw model object (there is no object writer in the output catalog).
    return persist_model(
        model,
        ml_context,
        name="demo_model",
        framework="sklearn",
        metrics={"f1": f1, "baseline_f1": baseline_f1},
        hyperparameters=params,
    )
'''
        ml_file = self.output_path / "pipelines" / "ml.py"
        self._write_text_file(ml_file, ml_code)

    def _generate_etl_sample_code(self) -> None:
        """Generate a single, focused ETL pipeline module."""
        etl_code = '''"""
ETL Pipeline: Extract → Transform → Load
Demonstrates Ducta's core capabilities:
- Multi-format I/O (CSV, Parquet, JSON)
- Data validation and transformation
- Dependency management between nodes
- Structured logging with loguru
"""
from typing import Any, Optional
from loguru import logger


def extract(
    source_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """
    Extract: Load and validate raw data from source.

    Ducta automatically loads data based on config:
    - Format: CSV, Parquet, JSON, Delta
    - Options: header, inferSchema, encoding, etc.

    Args:
        source_data: Loaded DataFrame from input config

    Returns:
        Raw data ready for transformation
    """
    logger.info("📥 Extracting data from source")

    if source_data is None:
        raise ValueError("No data provided from source")

    # Get record count
    records = source_data.count() if hasattr(source_data, "count") else len(source_data)
    logger.info("✓ Extracted {:,} records", records)

    return source_data


def transform(
    raw_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """
    Transform: Validate and clean data.

    Demonstrates:
    - Input validation
    - Data quality checks
    - Schema validation

    Args:
        raw_data: Raw DataFrame from extract node

    Returns:
        Clean, validated DataFrame
    """
    logger.info("⚙️  Transforming data")

    if raw_data is None:
        raise ValueError("raw_data cannot be None")

    # Check for required columns
    if hasattr(raw_data, "columns"):
        columns = set(raw_data.columns)
        logger.debug("Available columns: {}", columns)

    # Check for null values — only when the column actually exists, so this
    # boilerplate stays quiet on datasets without an 'id' column.
    if hasattr(raw_data, "filter") and "id" in getattr(raw_data, "columns", []):
        null_records = raw_data.filter("id IS NULL").count()
        if null_records > 0:
            logger.warning("Found {} records with NULL id", null_records)
            # Optionally remove: raw_data = raw_data.filter("id IS NOT NULL")

    # Add any transformation logic here
    # Example (PySpark):
    # from pyspark.sql.functions import upper, trim
    # raw_data = raw_data.withColumn("name", trim(upper(col("name"))))

    logger.info("✓ Data transformation complete")
    return raw_data


def load(
    clean_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """
    Load: Persist processed data to output destination.

    Ducta handles output based on config:
    - Format: CSV, Parquet, JSON, Delta
    - Write mode: overwrite, append, etc.
    - Automatic path creation

    Args:
        clean_data: Cleaned DataFrame from transform node

    Returns:
        The same data (for potential chaining)
    """
    logger.info("💾 Loading data to output")

    if clean_data is None:
        raise ValueError("clean_data cannot be None")

    # Get final record count
    records = clean_data.count() if hasattr(clean_data, "count") else len(clean_data)
    logger.info("✓ Loaded {:,} records to output destination", records)

    # Ducta automatically writes the data based on output config
    # No need to call write() yourself - just return the DataFrame
    return clean_data
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
3. Add the module path to ``global_settings.quality.extensions``:

   .. code-block:: toml

       [quality]
       extensions = ["pipelines.checks.custom_checks"]

4. Reference the check in any node config:

   .. code-block:: toml

       [nodes.my_node.sanity_checks.checks.positive_prices]
       enabled = true
       column = "price"
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
            neg_count = adapter.count_where(f"{column} <= 0")
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

A production-ready ETL pipeline built with **Ducta**.

## What's Ducta?

Ducta is a data pipeline framework that provides:
- ✅ **Multi-format I/O**: CSV, JSON, Parquet, Delta, etc.
- ✅ **Data Validation**: Schema checks, null handling, transformations
- ✅ **Dependency Management**: Automatic node sequencing
- ✅ **Multi-Environment Support**: dev, sandbox, prod configurations
- ✅ **Structured Logging**: Professional terminal output with loguru
- ✅ **Error Handling**: Retry logic, detailed error diagnostics

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. View available pipelines
```bash
ducta config list-pipelines --env dev
```

### 3. Run the ETL pipeline
```bash
# Full pipeline
ducta start -e dev -p etl

# Specific node
ducta start -e dev -p etl -n extract

# Validate configuration
ducta start -e dev -p etl --validate-only

# Debug mode
ducta start -e dev -p etl --log-level DEBUG
```

## Project Structure

```
{template.project_name}/
├── config/                    # Configuration files
│   ├── global_settings.yaml  # Project settings
│   ├── pipelines.yaml        # Pipeline definitions
│   ├── nodes.yaml            # Node implementations
│   ├── input.yaml            # Input sources
│   ├── output.yaml           # Output destinations
│   ├── dev/                  # Dev environment overrides
│   ├── sandbox/              # Sandbox environment overrides
│   └── prod/                 # Prod environment overrides
├── pipelines/                 # Implementation
│   └── etl.py                # Extract-Transform-Load functions
├── data/                      # Data directories
│   ├── input.csv             # Sample input
│   ├── raw/                  # Raw extracted data
│   ├── processed/            # Transformed data
│   └── output.csv            # Final output
└── requirements.txt          # Dependencies
```

## Pipeline Flow

```
source_data (CSV)
     ↓
[extract] → raw_data (Parquet)
     ↓
[transform] → clean_data (Parquet)
     ↓
[load] → final_output (CSV)
```

## Key Features Demonstrated

1. **Multi-Format Support**: Reads CSV, outputs CSV (Parquet intermediate)
2. **Automatic Data Loading**: Ducta loads source_data based on input config
3. **Automatic Data Saving**: Ducta saves outputs based on output config
4. **Dependency Chain**: extract → transform → load (automatic sequencing)
5. **Validation & Logging**: Built-in data quality checks and structured logging
6. **Environment Config**: Override settings per environment (dev/sandbox/prod)

## Configuration Highlights

- **inputs**: Define data sources with format & validation rules
- **outputs**: Define destinations with write modes & auto-creation
- **nodes**: Map functions to data inputs/outputs with dependencies
- **pipelines**: Compose nodes into executable workflows

## Next Steps

1. Replace `data/input.csv` with your actual data
2. Customize `pipelines/etl.py` functions for your use case
3. Update `config/input.yaml` and `config/output.yaml` for your data sources
4. Add environment-specific configs in `config/dev/`, `config/prod/`, etc.
5. Extend with additional pipelines as needed

## For More Information

- Run `Ducta --help` for all CLI options
- Check Ducta docs: https://github.com/faustinolopezramos/ducta

Generated on: {template.timestamp}
"""
        readme_file = self.output_path / "README.md"
        self._write_text_file(readme_file, readme_content)

        # requirements.txt - minimal but complete
        requirements = """Ducta>=0.1.0
pyspark>=3.4.0
pandas>=1.5.0
loguru>=0.7.0
pyyaml>=6.0
pytest>=7.4.0
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

        # Sample input data (template-specific: ML needs numeric features + target)
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

            # Validate required inputs
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
            # Validate template type
            try:
                template_enum = TemplateType(template_type)
            except ValueError:
                available = [t.value for t in TemplateType]
                logger.error("Invalid template type: {}", template_type)
                logger.info("Available types: {}", ", ".join(available))
                return ExitCode.VALIDATION_ERROR.value

            # Validate config format
            try:
                format_enum = ConfigFormat(config_format)
            except ValueError:
                available = [f.value for f in ConfigFormat]
                logger.error("Invalid config format: {}", config_format)
                logger.info("Available formats: {}", ", ".join(available))
                return ExitCode.VALIDATION_ERROR.value

            # Set default output path
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
