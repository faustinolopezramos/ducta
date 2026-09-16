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

PIPELINES_ETL_MODULE = "pipelines.etl"
_TEMPLATE_CANCELLED_MSG = "Template generation cancelled"


class TemplateType(Enum):
    """Available template types for project generation."""

    MEDALLION_BASIC = "medallion_basic"
    STREAMING_BASIC = "streaming_basic"


class TemplateError(DuctaError):
    """Exception for template-related errors."""

    def __init__(self, message: str):
        super().__init__(message, ExitCode.CONFIGURATION_ERROR)


class TemplateFactory:
    """Factory for creating template instances."""

    #: One place naming every template. The registry and the listing are derived
    #: from it, so adding a template cannot leave `--list-templates` behind.
    @staticmethod
    def _registry() -> Dict[TemplateType, Any]:
        return {
            TemplateType.MEDALLION_BASIC: MedallionBasicTemplate,
            TemplateType.STREAMING_BASIC: StreamingBasicTemplate,
        }

    @staticmethod
    def create_template(
        template_type: TemplateType,
        project_name: str,
        config_format: ConfigFormat = ConfigFormat.YAML,
    ) -> Any:
        """Create a template instance based on the given type."""
        template_class = TemplateFactory._registry().get(template_type)
        if template_class is None:
            raise TemplateError(f"Unknown template type: {template_type}")
        return template_class(project_name, config_format)

    @staticmethod
    def list_available_templates() -> List[Dict[str, str]]:
        """List all available templates with their metadata."""
        return [
            {
                "type": template_type.value,
                "name": template_class.TEMPLATE_NAME,
                "description": template_class.TEMPLATE_DESCRIPTION,
            }
            for template_type, template_class in TemplateFactory._registry().items()
        ]


class BaseTemplate:
    """What every project scaffold shares, whatever kind of pipeline it ships.

    The env_config layout, the base global config and the file-extension map
    are properties of a *Ducta project*, not of any one template. Keeping them
    here is what makes a second template a matter of describing its pipeline
    rather than restating the project structure around it.

    A subclass supplies the five config documents (``generate_*_config``), its
    sample data, and the module of Python its nodes point at.
    """

    # File extension mapping by format
    FORMAT_EXTENSIONS = {
        ConfigFormat.YAML: ".yaml",
        ConfigFormat.JSON: ".json",
        ConfigFormat.TOML: ".toml",
    }

    #: Shown by `ducta template --list-templates`.
    TEMPLATE_NAME = "Base"
    TEMPLATE_DESCRIPTION = ""
    #: Dotted module the generated nodes import their functions from, and the
    #: file the generator writes that module to.
    SAMPLE_MODULE = "pipelines.etl"
    SAMPLE_MODULE_PATH = ("pipelines", "etl.py")
    #: The pipeline `ducta start --pipeline <name>` should run first.
    DEFAULT_PIPELINE = "etl"

    def __init__(self, project_name: str, config_format: ConfigFormat = ConfigFormat.YAML):
        self.project_name = project_name
        self.config_format = config_format
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def generate_sample_code(self) -> Optional[str]:
        """The Python module backing this template's nodes, or None if it needs none."""
        return None

    def get_sample_data(self) -> Optional[str]:
        """CSV seed data written to ``data/input.csv``, or None if unused."""
        return None

    def generate_settings_json(self) -> Dict[str, Any]:
        """Generate environment configuration with paths matching the format."""
        file_ext = self.FORMAT_EXTENSIONS[self.config_format]

        # Common path patterns for each environment
        config_paths = {
            "base": {
                "global_config_path": f"config/global_config{file_ext}",
                "pipelines_config_path": f"config/pipelines{file_ext}",
                "nodes_config_path": f"config/nodes{file_ext}",
                "input_config_path": f"config/input{file_ext}",
                "output_config_path": f"config/output{file_ext}",
            },
            "dev": {
                "global_config_path": f"config/dev/global_config{file_ext}",
                "input_config_path": f"config/dev/input{file_ext}",
                "output_config_path": f"config/dev/output{file_ext}",
            },
            "sandbox": {
                "global_config_path": f"config/sandbox/global_config{file_ext}",
                "input_config_path": f"config/sandbox/input{file_ext}",
                "output_config_path": f"config/sandbox/output{file_ext}",
            },
            "prod": {
                "global_config_path": f"config/prod/global_config{file_ext}",
                "input_config_path": f"config/prod/input{file_ext}",
                "output_config_path": f"config/prod/output{file_ext}",
            },
        }

        return {"base_path": ".", "env_config": config_paths}

    #: Stamped into global_config for documentation/provenance. Subclasses
    #: override to describe their own shape.
    TEMPLATE_TYPE = "base"
    ARCHITECTURE = "generic"
    LAYERS: List[str] = []

    def get_common_global_config(self) -> Dict[str, Any]:
        """Get common global config for all templates."""
        settings: Dict[str, Any] = {
            "project_name": self.project_name,
            "version": "1.0.0",
            "created_at": self.timestamp,
            "template_type": self.TEMPLATE_TYPE,
            "architecture": self.ARCHITECTURE,
            "mode": "local",  # change to 'databricks' or 'distributed' if needed
            # Base dirs for ${input_path}/${output_path} interpolation in the
            # I/O catalogs; required by Context validation.
            "input_path": "data",
            "output_path": "data",
            "max_parallel_nodes": 4,
            "fail_on_error": True,
        }
        if self.LAYERS:
            settings["layers"] = list(self.LAYERS)
        return settings


class MedallionBasicTemplate(BaseTemplate):
    """Functional Medallion template: minimal, clean, and production-ready."""

    TEMPLATE_NAME = "Medallion Basic"
    TEMPLATE_DESCRIPTION = (
        "Batch ETL across bronze/silver/gold, with quality gates that block on real defects"
    )
    TEMPLATE_TYPE = "medallion_basic"
    ARCHITECTURE = "medallion"
    LAYERS = ["bronze", "silver", "gold"]
    SAMPLE_MODULE = PIPELINES_ETL_MODULE
    SAMPLE_MODULE_PATH = ("pipelines", "etl.py")
    DEFAULT_PIPELINE = "etl"

    def generate_global_config(self) -> Dict[str, Any]:
        base_settings = self.get_common_global_config()
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
                "description": "Silver: deduplicate, drop incomplete and invalid rows",
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
                        # A negative amount is a refund or entry error, not a
                        # missing value — null_rate and duplicates both pass on
                        # these rows untouched, so this is the check that would
                        # actually notice if `transform` stopped filtering them.
                        "range": {
                            "enabled": True,
                            "column": "amount",
                            "min": 0,
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
    #: Rows with a negative ``amount`` — a refund or entry error, not a missing
    #: value — so the silver `range` check has a defect only *it* catches
    #: (null_rate and duplicates would both pass on these rows untouched).
    _NEGATIVE_AMOUNT_ROWS = frozenset({15, 60, 120, 175, 260, 305, 355, 390, 430, 475})
    _CATEGORIES = ("electronics", "grocery", "apparel", "home", "toys")

    def get_sample_data(self) -> str:
        """A deliberately dirty CSV, so the medallion layers have work to do."""
        header = "order_id,category,amount,order_date"
        rows = []
        for order_id in range(1, 501):
            category = self._CATEGORIES[order_id % len(self._CATEGORIES)]
            base_amount = f"{50 + (order_id * 7) % 450}.00"
            if order_id in self._NULL_ROWS:
                # Blank (not 0) — a missing amount, which is what null_rate is about.
                amount = ""
            elif order_id in self._NEGATIVE_AMOUNT_ROWS:
                amount = f"-{base_amount}"
            else:
                amount = base_amount
            day = (order_id % 28) + 1
            rows.append(f"{order_id},{category},{amount},2025-01-{day:02d}")

        by_id = {int(r.split(",", 1)[0]): r for r in rows}
        rows.extend(by_id[order_id] for order_id in self._DUPLICATED_ORDERS)

        return "\n".join([header, *rows]) + "\n"


class StreamingBasicTemplate(BaseTemplate):
    """A working Structured Streaming project: file source -> transform -> sink.

    Streaming is the type whose configuration is least guessable from the batch
    scaffold, and until now it had no scaffold at all. Three things work
    differently here and each is wrong in a way that is hard to diagnose from a
    blank file:

    * a streaming node's function is a **dict** naming a registered transform,
      not a ``module``/``function`` pair, and it is called ``fn(df)`` or
      ``fn(df, params)`` — not with ``start_date``/``end_date``;
    * ordering between streaming nodes uses ``depends_on``;
    * every node needs its own ``checkpoint_location``, and two nodes sharing
      one corrupts both.

    The source is ``file_stream`` on purpose: it runs with nothing installed but
    Spark, so the scaffold works before anyone stands up Kafka. The
    ``kafka``-shaped alternative is written out in the generated README.
    """

    TEMPLATE_NAME = "Streaming Basic"
    TEMPLATE_DESCRIPTION = (
        "Structured Streaming: file source, registered transforms, per-node checkpoints"
    )
    TEMPLATE_TYPE = "streaming_basic"
    ARCHITECTURE = "streaming"
    LAYERS = ["bronze", "silver"]
    SAMPLE_MODULE = "pipelines.transforms"
    SAMPLE_MODULE_PATH = ("pipelines", "transforms.py")
    DEFAULT_PIPELINE = "events_stream"

    def generate_global_config(self) -> Dict[str, Any]:
        settings = self.get_common_global_config()
        settings.update(
            {
                "spark_master": "local[4]",
                # Imported and called before any streaming pipeline starts, so
                # the transforms below are in the registry by the time the nodes
                # that name them are built. Without this the CLI needs
                # --transforms-modules on every run.
                "streaming_transform_modules": [self.SAMPLE_MODULE],
                # Long-running queries: no run certificate is emitted for an
                # async streaming pipeline, so leaving this on costs nothing and
                # covers the `--mode sync` case.
                "max_streaming_pipelines": 5,
            }
        )
        return settings

    def generate_pipelines_config(self) -> Dict[str, Any]:
        return {
            "events_stream": {
                "description": "Ingest a file stream, clean it, and land it as Delta-ready Parquet",
                "type": "streaming",
                "nodes": ["ingest_events", "clean_events"],
                # Streaming pipelines are not date-ranged: they run until stopped.
                "requires_dates": False,
            },
        }

    def generate_nodes_config(self) -> Dict[str, Any]:
        """Two streaming nodes, wired the way streaming nodes actually wire up.

        Note what is *not* here: no ``module``/``function``, no ``dependencies``.
        A streaming node names a transform registered in the registry, and orders
        itself with ``depends_on``.
        """
        return {
            "ingest_events": {
                "description": "Bronze: land the raw event stream exactly as it arrives",
                "type": "streaming",
                "input": {
                    "format": "file_stream",
                    # `file_format`, not options.format: the reader passes
                    # options straight to Spark, and Spark has no "format"
                    # option — it would be accepted and ignored.
                    "file_format": "json",
                    # Top level, not inside options, and required: Structured
                    # Streaming cannot infer a schema from a stream. Get it
                    # wrong and you get an empty stream, not an error.
                    "schema": "event_id STRING, category STRING, amount DOUBLE, ts TIMESTAMP",
                    "options": {
                        # The path belongs in options; the top-level spelling is
                        # deprecated and warns.
                        "path": "${input_path}/events",
                        # One file per micro-batch, so the demo shows several
                        # batches instead of swallowing every seed file at once.
                        "maxFilesPerTrigger": 1,
                    },
                },
                "output": {
                    "format": "parquet",
                    "path": "${output_path}/${environment}/bronze/events",
                },
                "streaming": {
                    # Per node. Two nodes sharing a checkpoint corrupt each
                    # other's offsets; delete this directory to replay from the start.
                    "checkpoint_location": "${output_path}/${environment}/_ckpt/ingest_events",
                    "trigger": {"type": "processing_time", "interval": "5 seconds"},
                    "output_mode": "append",
                },
            },
            "clean_events": {
                "description": "Silver: drop incomplete events and stamp an ingest time",
                "type": "streaming",
                # Ordering between streaming nodes. Not `dependencies` — that is
                # the batch/ML key. Ducta reads both, but `depends_on` is what
                # the streaming engine orders its startup waves by.
                "depends_on": ["ingest_events"],
                "input": {
                    "format": "file_stream",
                    "file_format": "parquet",
                    "schema": "event_id STRING, category STRING, amount DOUBLE, ts TIMESTAMP",
                    "options": {"path": "${output_path}/${environment}/bronze/events"},
                },
                # A dict naming a transform in the registry by its `key`, with
                # its params. `module` makes the query manager import it and call
                # register_transforms() before the lookup, so the node works even
                # if global_config.streaming_transform_modules is removed.
                "function": {
                    "key": "clean_events",
                    "module": self.SAMPLE_MODULE,
                    "params": {"min_amount": 0.0},
                },
                "output": {
                    "format": "parquet",
                    "path": "${output_path}/${environment}/silver/events",
                },
                "streaming": {
                    "checkpoint_location": "${output_path}/${environment}/_ckpt/clean_events",
                    "trigger": {"type": "processing_time", "interval": "5 seconds"},
                    "output_mode": "append",
                },
            },
        }

    def generate_input_config(self) -> Dict[str, Any]:
        """Streaming nodes carry their I/O inline, so the catalogs stay empty.

        Kept as valid empty documents because Context requires all five.
        """
        return {}

    def generate_output_config(self) -> Dict[str, Any]:
        return {}

    def get_sample_data(self) -> Optional[str]:
        """No CSV seed: the generator writes JSON events into the watched folder."""
        return None

    #: Seed events dropped into ``data/events/`` so the stream has something to
    #: read on the first run. Two carry a null amount, so `clean_events` has
    #: real work to do and the row counts visibly differ between layers.
    SAMPLE_EVENTS = [
        '{"event_id": "e1", "category": "electronics", "amount": 42.5, "ts": "2026-01-01T10:00:00"}',
        '{"event_id": "e2", "category": "grocery", "amount": 7.25, "ts": "2026-01-01T10:00:05"}',
        '{"event_id": "e3", "category": "apparel", "amount": null, "ts": "2026-01-01T10:00:09"}',
        '{"event_id": "e4", "category": "home", "amount": 88.0, "ts": "2026-01-01T10:00:14"}',
        '{"event_id": "e5", "category": "toys", "amount": null, "ts": "2026-01-01T10:00:21"}',
    ]

    def generate_sample_code(self) -> Optional[str]:
        return '''"""
Streaming transforms for the `events_stream` pipeline.

A streaming transform is NOT a batch node function. It takes the streaming
DataFrame and returns one; it gets no ``start_date``/``end_date``, because a
stream has no date range. Two shapes are accepted:

    def fn(df)            -> DataFrame
    def fn(df, params)    -> DataFrame     # `params` is the node's function.params

Nodes reference a transform by the name it was registered under, not by import
path:

    function: {name: "clean_events", params: {min_amount: 0.0}}

`register_transforms` is called automatically before the pipeline starts,
because `global_config.streaming_transform_modules` names this module. Run
`ducta stream run --pipeline events_stream --config environment.yaml` and drop
another .json file into data/events/ to watch it picked up.
"""
from typing import Any, Dict

from loguru import logger


def clean_events(df: Any, params: Dict[str, Any] | None = None) -> Any:
    """Drop events with no amount, and stamp when Ducta saw them.

    This is where a streaming job earns its silver layer: the bronze node lands
    everything, and this one decides what counts as usable. The two seed events
    with a null amount are dropped here, so bronze and silver visibly differ.
    """
    from pyspark.sql import functions as F

    params = params or {}
    min_amount = float(params.get("min_amount", 0.0))

    cleaned = (
        df.filter(F.col("amount").isNotNull())
        .filter(F.col("amount") >= F.lit(min_amount))
        .withColumn("ingested_at", F.current_timestamp())
    )
    logger.info("clean_events: filtering nulls and amounts below {}", min_amount)
    return cleaned


def register_transforms(registry: Any) -> None:
    """Called by Ducta before the pipeline starts.

    The registry maps a name to a callable; `function: {name: ...}` in
    config/nodes.yaml is what looks it up.
    """
    registry.register("clean_events", clean_events)
    logger.info("Registered streaming transforms: clean_events")
'''

    def generate_readme(self, ext: str) -> str:
        """README for a streaming project, which runs differently from a batch one."""
        return f"""# {self.project_name}

A **Structured Streaming** pipeline built with **Ducta**.

## Run it

```bash
pip install -r requirements.txt

# Start the stream (runs until you stop it)
ducta stream run --config environment{ext} --pipeline events_stream --env dev

# In another shell: watch it, then stop it
ducta stream status --config environment{ext} --env dev
ducta stream stop   --config environment{ext} --env dev --execution-id <id>
```

`data/events/` ships five seed events. Two have a null `amount`, so the silver
layer visibly drops rows the bronze layer kept. Drop another `.json` file into
that folder while the stream runs and watch it get picked up.

## What is different from a batch pipeline

Three things, and each is hard to guess from the batch scaffold:

**1. A streaming node's function is a dict, not `module` + `function`.**

```yaml
function: {{key: "clean_events", module: "pipelines.transforms", params: {{min_amount: 0.0}}}}
```

It names a transform registered in `pipelines/transforms.py`, and it is called
`fn(df)` or `fn(df, params)` — no `start_date`/`end_date`, because a stream has
no date range. `global_config.streaming_transform_modules` makes Ducta import
and register them for you.

**2. Ordering uses `depends_on`, not `dependencies`.**

```yaml
clean_events:
  depends_on: ["ingest_events"]
```

**3. Every node needs its own `checkpoint_location`.**

Two nodes sharing one corrupt each other's offsets. Delete a node's checkpoint
directory to replay its source from the beginning.

## Switching the source to Kafka

Replace the `input` block of `ingest_events`:

```yaml
input:
  format: kafka
  options:
    kafka.bootstrap.servers: "localhost:9092"
    subscribe: "events"
    startingOffsets: "latest"
```

Kafka delivers `key`/`value` as bytes, so your transform casts them:
`df.selectExpr("CAST(value AS STRING) as json")` and then `from_json`.

## What streaming does *not* get

Quality checks, data fingerprints and run certificates are batch/ML features.
A streaming pipeline started with `--mode async` emits no run certificate: it
has no end to certify. Use `--mode sync` with a `once` or `availableNow`
trigger if you want a terminating run.

## Layout

```
{self.project_name}/
├── config/                  # the five config documents, per environment
├── pipelines/transforms.py  # your streaming transforms + register_transforms
├── data/events/             # the watched source directory
└── environment{ext}         # which config file each --env resolves to
```

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


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
        self.template = template

        # Create directory structure
        self._create_directory_structure(developer_sandboxes)

        # Generate configuration files
        self._generate_config_files(template, developer_sandboxes)

        # Generate sample code if requested
        if create_sample_code:
            self._generate_sample_code(template)

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
            "global_config": template.generate_global_config(),
            "pipelines": template.generate_pipelines_config(),
            "nodes": template.generate_nodes_config(),
            "input": template.generate_input_config(),
            "output": template.generate_output_config(),
        }

        # Generate main settings file with format-specific writer
        settings_file = self.output_path / self._settings_filename

        self._writer(settings_file, template.generate_settings_json())

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

    def _generate_sample_code(self, template: Optional[BaseTemplate] = None) -> None:
        """Write the Python module this template's nodes point at.

        Asks the template for its own code rather than hard-coding the ETL one:
        a streaming template's module is a transform registry, not a set of
        batch node functions, and they are not interchangeable.
        """
        code = template.generate_sample_code() if template is not None else None
        if code is None:
            # No template-supplied module: the medallion ETL is the historical
            # default, kept so an older caller still scaffolds something usable.
            self._generate_etl_sample_code()
            return

        package, filename = template.SAMPLE_MODULE_PATH
        package_dir = self.output_path / package
        package_dir.mkdir(parents=True, exist_ok=True)
        init_file = package_dir / "__init__.py"
        if not init_file.exists():
            self._write_text_file(init_file, "")
        self._write_text_file(package_dir / filename, code)

    def _generate_etl_sample_code(self) -> None:
        """Generate a single, focused ETL pipeline module."""
        etl_code = '''"""
Medallion ETL: bronze -> silver -> gold

Each layer does real work, and the quality checks in ``config/nodes.yaml``
verify that it did. The sample data ships deliberately dirty (12 rows with a
missing amount, 8 verbatim duplicates, 10 rows with a negative amount), so:

    bronze  508 rows   raw, exactly as it arrived
    silver  478 rows   deduplicated, missing and negative amounts dropped
    gold      5 rows   one row per category

The silver checks (null_rate, duplicates, range) pass *because* `transform`
cleaned the data. Break `transform` and the quality gate blocks the run before
anything is written -- that is the point of the demo, and you can try it:
comment out the dropna() below and re-run.
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

    Three operations. The first two are schema-agnostic, so they keep working
    when you point the pipeline at your own table; the third only fires on the
    column this template's sample data is actually dirty in:

      1. drop exact duplicate rows
      2. drop rows with a missing value in any column
      3. drop rows where ``VALUE_COLUMN`` is negative, if that column exists --
         a refund or entry error, not a value `dropna()` would ever catch

    The ``data_quality`` checks on this node assert the result: null_rate 0, no
    duplicate order_id, and no negative amount. They are not decoration -- they
    fail if this function stops doing its job, and the gate stops the run
    before gold is written.
    """
    if raw_data is None:
        raise ValueError("raw_data cannot be None")

    # `cleaned` is reassigned at each stage (not chained through separate
    # names) so that commenting out any *one* of the three lines below to try
    # the quality gate still leaves it bound to the previous stage's result --
    # not undefined. That is the whole point of the exercise in the README.
    before = _row_count(raw_data)

    cleaned = raw_data.dropDuplicates() if hasattr(raw_data, "dropDuplicates") else raw_data.drop_duplicates()
    after_dedup = _row_count(cleaned)

    cleaned = cleaned.dropna()
    after_dropna = _row_count(cleaned)

    if VALUE_COLUMN in list(getattr(cleaned, "columns", [])):
        # `IS NULL OR ... >= 0`, not just `>= 0`: SQL's three-valued logic
        # would otherwise silently drop null amounts here too, so commenting
        # out the dropna() line above would stop demonstrating anything -- the
        # range filter would have already removed the rows null_rate expects
        # to catch. Each cleaning step should only remove the defect it owns.
        cleaned = (
            cleaned.filter(f"{VALUE_COLUMN} IS NULL OR {VALUE_COLUMN} >= 0")
            if hasattr(cleaned, "filter")
            else cleaned[cleaned[VALUE_COLUMN].isna() | (cleaned[VALUE_COLUMN] >= 0)]
        )
    after = _row_count(cleaned)

    logger.info(
        "Silver: {:,} -> {:,} rows ({:,} duplicates, {:,} incomplete, {:,} invalid)",
        before,
        after,
        before - after_dedup,
        after_dedup - after_dropna,
        after_dropna - after,
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
        # Keeps the node working when the template is pointed at your own data
        # before you have adjusted the two constants at the top of this file.
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
   ``config/global_config.yaml``:

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
        # The scaffold honours --format, so the README must name the files that
        # actually exist on disk: config/input.json, not config/input.yaml.
        ext = self._file_extension
        # README.md — templates that describe a different pipeline supply their
        # own; the medallion text below would otherwise tell a streaming user to
        # run a batch pipeline that does not exist in their project.
        custom_readme = getattr(template, "generate_readme", None)
        if callable(custom_readme):
            self._write_text_file(self.output_path / "README.md", custom_readme(ext))
            self._write_support_files(template)
            return

        readme_content = f"""# {template.project_name}

A medallion ETL pipeline built with **Ducta**.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline etl
```

The sample data is **deliberately dirty** — 12 rows with a missing `amount`,
8 verbatim duplicates, and 10 rows with a negative `amount` — so the run has
something real to do:

```
bronze  508 rows   raw, exactly as it arrived
silver  478 rows   deduplicated, incomplete and invalid rows dropped
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

`config/nodes{ext}` asserts on the silver layer that `amount` has no nulls, no
negative values, and `order_id` has no duplicates, with `quality_gate.max_errors:
0`. Those checks pass because `transform` cleaned the data. To watch them fail:

1. Open `pipelines/etl.py` and comment out the `cleaned.dropna()` line (or the
   `filter(...)` block right below it) in `transform`.
2. Re-run `ducta start --env dev --pipeline etl`.

The gate blocks, `load` is skipped, and **gold is never written** — the checks
run before the write, so bad data does not reach storage. Undo the change to go
back to a passing run.

## Project structure

```
{template.project_name}/
├── config/
│   ├── global_config{ext}  # project settings, quality profiles
│   ├── pipelines{ext}        # which nodes make up which pipeline
│   ├── nodes{ext}            # per-node I/O, checks and gates
│   ├── input{ext}            # where data is read from
│   ├── output{ext}           # where data is written to
│   └── dev/ sandbox/ prod/   # per-environment overrides
├── pipelines/
│   ├── etl.py                # your transformations (plain functions)
│   └── checks/custom_checks.py
└── data/
    ├── input.csv             # sample source
    └── dev/                  # bronze/ silver/ gold/ written per environment
        ├── quality/           # quality reports, baselines, history
        └── .ducta/            # run certificates, chain state (framework state)
```

## What to change first

1. Point `config/input{ext}` at your own data.
2. Rewrite the three functions in `pipelines/etl.py`. They are ordinary Python
   taking a DataFrame and returning one — no decorators, no framework types.
3. Update the checks in `config/nodes{ext}` to assert what *your* transform
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

        self._write_support_files(template)

    def _write_support_files(self, template: BaseTemplate) -> None:
        """requirements, .gitignore and seed data — identical for every template."""
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

        self._write_seed_data(template)

    def _write_seed_data(self, template: BaseTemplate) -> None:
        """Write whatever seed data this template's first run needs.

        A batch template seeds one CSV the input catalog points at. A streaming
        template seeds *files in a watched directory* — the stream has to have
        something to pick up, and it arrives as separate files rather than one.
        """
        sample_data = template.get_sample_data()
        if sample_data is not None:
            self._write_text_file(self.output_path / "data" / "input.csv", sample_data)

        events = getattr(template, "SAMPLE_EVENTS", None)
        if events:
            events_dir = self.output_path / "data" / "events"
            events_dir.mkdir(parents=True, exist_ok=True)
            # One file per event: `maxFilesPerTrigger: 1` then makes the demo
            # show several micro-batches instead of swallowing everything in one.
            for index, event in enumerate(events, start=1):
                self._write_text_file(events_dir / f"event_{index:03d}.json", event + "\n")

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
        valid_formats = [f.value for f in ConfigFormat]
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

            valid_formats = [f.value for f in ConfigFormat]
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

    @staticmethod
    def _parse_enum_or_error(enum_cls, value: str, label: str, available_label: str):
        """Parse *value* as *enum_cls*, or log the invalid value and its
        allowed options under *label*/*available_label* and return ``None``."""
        try:
            return enum_cls(value)
        except ValueError:
            available = [member.value for member in enum_cls]
            logger.error("Invalid {}: {}", label, value)
            logger.info("Available {}: {}", available_label, ", ".join(available))
            return None

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
            template_enum = self._parse_enum_or_error(
                TemplateType, template_type, "template type", "types"
            )
            if template_enum is None:
                return ExitCode.VALIDATION_ERROR.value

            format_enum = self._parse_enum_or_error(
                ConfigFormat, config_format, "config format", "formats"
            )
            if format_enum is None:
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

            self._show_success_message(
                project_name, output_dir, self.generator.template, self.generator._settings_filename
            )

            return ExitCode.SUCCESS.value

        except Exception as e:
            logger.error("Template generation failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _show_success_message(
        self, project_name: str, output_dir: Path, template: "BaseTemplate", config_filename: str
    ) -> None:
        """Show success message with next steps, tailored to *template*'s
        module path, default pipeline and run command — these differ between
        a batch template (``ducta start``) and a streaming one (``ducta
        stream run``)."""
        logger.success("✅ Project '{}' created successfully!", project_name)
        logger.info("📁 Location: {}", output_dir.absolute())
        logger.info("\n📋 Next steps:")
        logger.info("1️⃣  cd {}", output_dir)
        logger.info("2️⃣  pip install -r requirements.txt")
        logger.info("3️⃣  Update config/input.yaml and config/output.yaml for your data")
        logger.info(
            "4️⃣  Customize {} for your business logic", "/".join(template.SAMPLE_MODULE_PATH)
        )
        logger.info("5️⃣  Update config/dev/input.yaml and output.yaml for dev environment")

        logger.info("\n🚀 Quick start:")
        pipeline = template.DEFAULT_PIPELINE
        if template.ARCHITECTURE == "streaming":
            logger.info("   # Start the stream (runs until you stop it)")
            logger.info(
                "   ducta stream run --config {} --pipeline {} --env dev", config_filename, pipeline
            )
            logger.info("")
            logger.info("   # In another shell: watch it, then stop it")
            logger.info("   ducta stream status --config {} --env dev", config_filename)
            logger.info(
                "   ducta stream stop   --config {} --env dev --execution-id <id>", config_filename
            )
        else:
            logger.info("   # Run the {} pipeline", pipeline)
            logger.info("   ducta start -e dev -p {}", pipeline)
            logger.info("")
            logger.info("   # Run specific node")
            logger.info("   ducta start -e dev -p {} -n extract", pipeline)
            logger.info("")
            logger.info("   # Debug mode")
            logger.info("   ducta start -e dev -p {} --log-level DEBUG", pipeline)
            logger.info("")
            logger.info("   # Validate config")
            logger.info("   ducta start -e dev -p {} --validate-only", pipeline)

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
