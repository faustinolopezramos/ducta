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

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.console.core import VALID_NAME_RE as _VALID_NAME_RE
from ducta.console.core import ConfigFormat, DuctaError, ExitCode

PIPELINES_ETL_MODULE = "pipelines.etl"
_TEMPLATE_CANCELLED_MSG = "Template generation cancelled"


class TemplateType(Enum):
    """Available template types for project generation."""

    MEDALLION_BASIC = "medallion_basic"
    STREAMING_BASIC = "streaming_basic"
    ML_BASIC = "ml_basic"
    HYBRID_BASIC = "hybrid_basic"


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
            TemplateType.ML_BASIC: MLBasicTemplate,
            TemplateType.HYBRID_BASIC: HybridBasicTemplate,
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

    A template *is* the text of a project's three kinds of file: ``ducta.yaml``,
    ``catalog.yaml`` and one ``pipelines/<name>.yaml`` per pipeline. They are
    written as YAML text, not built from dicts, so the generated files carry the
    comments that explain each non-obvious key, which is most of what a template
    is for. ``tests/console`` generates every template and runs it through the
    project validator, so the text cannot drift from the schema.

    A subclass supplies those three texts, its sample data, the module of Python
    its nodes point at, and a README.
    """

    #: Shown by `ducta template --list-templates`.
    TEMPLATE_NAME = "Base"
    TEMPLATE_DESCRIPTION = ""
    #: Dotted module the generated nodes import their functions from, and the
    #: file the generator writes that module to.
    SAMPLE_MODULE = "pipelines.etl"
    SAMPLE_MODULE_PATH = ("pipelines", "etl.py")
    #: The pipeline `ducta start --pipeline <name>` should run first.
    DEFAULT_PIPELINE = "etl"
    #: Descriptive only: written to the project's ``metadata``.
    TEMPLATE_TYPE = "base"
    ARCHITECTURE = "generic"
    #: What `pip install -r requirements.txt` installs.
    REQUIREMENTS = "ducta[spark]>=0.1.1\n"
    #: Appended to the generated ``.gitignore``.
    GITIGNORE_EXTRA = ""

    def __init__(self, project_name: str, config_format: ConfigFormat = ConfigFormat.YAML):
        self.project_name = project_name
        self.config_format = config_format
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        #: Written explicitly into ``settings`` so the project's evidence
        #: policy is a visible choice, not an invisible default.
        self.evidence_level = "record"
        #: ``--sandbox-developers``: each gets a ``sandbox_<name>`` environment.
        self.developer_sandboxes: List[str] = []

    # ── what a subclass supplies ─────────────────────────────────────────────

    def project_yaml(self) -> str:
        """The text of ``ducta.yaml``."""
        raise NotImplementedError

    def catalog_yaml(self) -> str:
        """The text of ``catalog.yaml``."""
        raise NotImplementedError

    def pipeline_yamls(self) -> Dict[str, str]:
        """``{pipeline name: text of pipelines/<name>.yaml}``."""
        raise NotImplementedError

    def readme(self) -> str:
        """The text of the project's ``README.md``."""
        raise NotImplementedError

    def generate_sample_code(self) -> Optional[str]:
        """The Python module backing this template's nodes, or None if it needs none."""
        return None

    def get_sample_data(self) -> Optional[str]:
        """CSV seed data written to ``data/input.csv``, or None if unused."""
        return None

    def seed_files(self) -> Dict[str, str]:
        """Further seed data: ``{path relative to the project: text}``."""
        return {}

    def quick_start(self) -> List[str]:
        """The commands the generator prints for a first run."""
        pipeline = self.DEFAULT_PIPELINE
        return [
            f"# Run the {pipeline} pipeline",
            f"ducta start -e dev -p {pipeline}",
            "",
            "# Run one node, or turn on debug logging",
            f"ducta start -e dev -p {pipeline} -n <node>",
            f"ducta start -e dev -p {pipeline} --log-level DEBUG",
            "",
            "# Validate config, no Spark",
            "ducta config validate --env dev",
        ]

    # ── shared by the texts ──────────────────────────────────────────────────

    def _render(self, text: str) -> str:
        """Fill the ``@@…@@`` markers; YAML's own braces make ``str.format`` unusable."""
        return (
            text.replace("@@PROJECT@@", self.project_name)
            .replace("@@EVIDENCE@@", self.evidence_level)
            .replace("@@SPARK@@", self._SPARK_NOTE)
        )

    #: PySpark 3.5 bundles an Arrow that cannot run on JDK 21: any Spark -> pandas
    #: conversion (a model's `toPandas()`, some quality checks) logs a leaked-memory
    #: error. Arrow only makes the conversion faster, so it is switched off here.
    _SPARK_NOTE = (
        "  # PySpark 3.5's bundled Arrow cannot run on JDK 21: converting Spark data to\n"
        "  # pandas logs a leaked-memory error. Remove this on JDK 8, 11 or 17 to get the\n"
        "  # faster Arrow conversion.\n"
        "  spark_config:\n"
        '    spark.sql.execution.arrow.pyspark.enabled: "false"\n'
    )

    def _sandbox_note(self) -> str:
        """A comment naming the developer sandboxes, if any were requested."""
        if not self.developer_sandboxes:
            return ""
        names = ", ".join(f"sandbox_{dev}" for dev in self.developer_sandboxes)
        return (
            f"  # Developer sandboxes ({names}) need no entry here: each one uses\n"
            "  # the `sandbox` overrides, and only needs its own when it differs.\n"
        )


class MedallionBasicTemplate(BaseTemplate):
    """Functional Medallion template: minimal, clean, and production-ready."""

    TEMPLATE_NAME = "Medallion Basic"
    TEMPLATE_DESCRIPTION = (
        "Batch ETL across bronze/silver/gold, with quality gates that block on real defects"
    )
    TEMPLATE_TYPE = "medallion_basic"
    ARCHITECTURE = "medallion"
    SAMPLE_MODULE = PIPELINES_ETL_MODULE
    SAMPLE_MODULE_PATH = ("pipelines", "etl.py")
    DEFAULT_PIPELINE = "etl"

    def project_yaml(self) -> str:
        return self._render(
            """\
# yaml-language-server: $schema=.ducta/schema/project.json
#
# The project: its name, where data lives, engine settings, and what changes
# per environment. Datasets are in catalog.yaml, pipelines in pipelines/.
version: 2
project: @@PROJECT@@
description: Medallion ETL (bronze, silver, gold) with quality gates

# Base directories. Reference them anywhere as ${paths.input} / ${paths.output}.
paths: {input: data, output: data}

# Every engine setting. `ducta config schema` lists them all.
settings:
  mode: local                  # local | distributed | databricks
  max_parallel_nodes: 4
  fail_on_error: true
  # off | record | required | signed: what a run can prove about itself.
  evidence_level: @@EVIDENCE@@
@@SPARK@@  quality:
    # Modules with your own @register_check classes (see pipelines/checks/).
    # extensions: [pipelines.checks.custom_checks]
    profiles:
      default:
        checks:
          empty_dataset: {enabled: true}

# Values a dataset or node gets unless it sets its own. Here: the format of each
# layer, so catalog.yaml only says what is specific to a dataset. Also available:
# defaults.node (retry, timeout_seconds, ...) and a per-pipeline `defaults:`.
defaults:
  catalog:
    "bronze.*": {format: parquet}
    "silver.*": {format: parquet}
    "gold.*": {format: csv}

# An environment states only what differs from the base project above.
environments:
  dev:
    settings: {max_parallel_nodes: 1, log_level: DEBUG}
  prod:
    settings: {max_parallel_nodes: 8}
"""
            + self._sandbox_note()
            + """
# Free-form notes. Ducta does not read this block.
metadata:
  template: medallion_basic
  layers: [bronze, silver, gold]
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# Every dataset, once, whether a node reads it, writes it, or both.
# A dotted name (schema.folder.table) with no `path` is stored at
# ${paths.output}/${env}/<schema>/<folder>/<table>.

source_data:
  description: Source orders (CSV, JSON or Parquet)
  format: csv
  path: data/input.csv
  options: {header: true, inferSchema: true}
  # A contract: checked every time a node reads this dataset, before it runs.
  checks:
    fail_fast: true
    empty_dataset: true
    schema: {expected_columns: [order_id, category, amount, order_date]}

# The format of bronze.*, silver.* and gold.* comes from `defaults.catalog` in
# ducta.yaml; a dataset states only what is its own. Datasets are overwritten on
# each run unless you add `write: {mode: append}` (or merge).
bronze.etl.raw_data:
  description: Raw data landed by `extract` (bronze)

silver.etl.clean_data:
  description: Clean data produced by `transform` (silver)

gold.etl.final_output:
  description: Final output, one row per category (gold)
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "etl": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# The file name is the pipeline name. Run order comes from the datasets:
# `transform` reads what `extract` writes, so it runs after it (use `after:`
# only when nothing connects two nodes).
description: "Complete ETL pipeline: Extract → Transform → Load"
type: batch
requires_dates: false        # not incremental: runs without --start-date/--end-date

nodes:
  extract:
    description: "Bronze: land the source exactly as it arrived"
    run: pipelines.etl:extract
    inputs: {source_data: source_data}     # {function parameter: dataset}
    outputs: [bronze.etl.raw_data]

  transform:
    description: "Silver: deduplicate, drop incomplete and invalid rows"
    run: pipelines.etl:transform
    inputs: {raw_data: bronze.etl.raw_data}
    outputs: [silver.etl.clean_data]
    # Checks on this node's OUTPUT, evaluated before it is written. They pass
    # only because `transform` cleans the data: break it and the gate blocks
    # the run before gold exists.
    quality:
      fail_fast: false
      null_rate: {columns: [amount], threshold: 0.0}
      duplicates: {columns: [order_id], max_duplicate_rate: 0.0}
      # A negative amount is a refund or an entry error, not a missing value:
      # null_rate and duplicates both pass on it, so only this check notices.
      range: {column: amount, min: 0}
      # A floor, not a ceiling: catches a transform that drops most rows.
      row_count: {min: 400}
      # skip_downstream: gold is skipped and nothing bad is written.
      # Use stop_all to abort the whole run instead.
      gate: {max_errors: 0, on_fail: skip_downstream}

  load:
    description: "Gold: aggregate into one row per category"
    run: pipelines.etl:load
    inputs: {clean_data: silver.etl.clean_data}
    outputs: [gold.etl.final_output]
    quality:
      empty_dataset: true
      row_count: {min: 1}
"""
        }

    def readme(self) -> str:
        return _medallion_readme_v2(self)

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
    * ordering between nodes uses ``dependencies``, as in batch;
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
    SAMPLE_MODULE = "pipelines.transforms"
    SAMPLE_MODULE_PATH = ("pipelines", "transforms.py")
    DEFAULT_PIPELINE = "events_stream"

    def project_yaml(self) -> str:
        return self._render(
            """\
# yaml-language-server: $schema=.ducta/schema/project.json
#
# The project: its name, where data lives, engine settings, and what changes
# per environment. Stream nodes declare their own sources and sinks, so
# catalog.yaml is empty; the pipeline is in pipelines/events_stream.yaml.
version: 2
project: @@PROJECT@@
description: Structured Streaming - file source, registered transforms, per-node checkpoints

# Base directories. Reference them anywhere as ${paths.input} / ${paths.output}.
paths: {input: data, output: data}

settings:
  mode: local                  # local | distributed | databricks
  max_parallel_nodes: 4
  fail_on_error: true
  # off | record | required | signed: what a run can prove about itself.
  evidence_level: @@EVIDENCE@@
@@SPARK@@  # Imported before any stream starts, so the transforms are registered by the
  # time the nodes that name them are built. Without it, every run needs
  # --transforms-modules.
  streaming_transform_modules: [pipelines.transforms]
  # Upper bound on streaming pipelines running at once.
  max_streaming_pipelines: 5

# Every stream node runs like this unless it says otherwise. `trigger` is an
# interval ('5s', '2 minutes') or 'available_now' for a run that finishes.
defaults:
  stream:
    streaming: {trigger: 5s, output_mode: append}

# An environment states only what differs from the base project above.
environments:
  dev:
    settings: {log_level: DEBUG}
"""
            + self._sandbox_note()
            + """
# Free-form notes. Ducta does not read this block.
metadata:
  template: streaming_basic
  layers: [bronze, silver]
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# Empty on purpose: every node in this project is a stream node, and stream
# nodes declare their sources and sinks inline
# (pipelines/events_stream.yaml). Batch datasets go here.
{}
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "events_stream": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# A stream node differs from a batch node in three ways:
#   * it names a registered transform (`transform: {key: ...}`), not
#     `run: module:function`, and the transform takes (df) or (df, params);
#   * its input and output are inline, so Ducta cannot infer the order between
#     nodes: say it with `after:`;
#   * every node needs its OWN checkpoint_location. Two nodes sharing one
#     corrupt each other's offsets; delete the directory to replay from the start.
description: Ingest a file stream, clean it, and land it as Delta-ready Parquet
type: streaming
requires_dates: false        # a stream has no date range: it runs until stopped

nodes:
  ingest_events:
    description: "Bronze: land the raw event stream exactly as it arrives"
    kind: stream
    stream:
      input:
        format: file_stream
        # `file_format`, not options.format: Spark has no "format" option, so it
        # would be accepted and ignored.
        file_format: json
        # Top level, not inside options, and required: a stream cannot infer its
        # schema. Get it wrong and you get an empty stream, not an error.
        schema: event_id STRING, category STRING, amount DOUBLE, ts TIMESTAMP
        options:
          path: ${paths.input}/events
          # One file per micro-batch, so the demo shows several batches instead
          # of swallowing every seed file at once.
          maxFilesPerTrigger: 1
      output:
        format: parquet
        path: ${paths.output}/${env}/bronze/events
      streaming:
        checkpoint_location: ${paths.output}/${env}/_ckpt/ingest_events

  clean_events:
    description: "Silver: drop incomplete events and stamp an ingest time"
    kind: stream
    after: [ingest_events]
    stream:
      # `module` is imported and its register_transforms() called before the
      # lookup, so the node works even without streaming_transform_modules.
      transform:
        key: clean_events
        module: pipelines.transforms
        params: {min_amount: 0.0}
      input:
        format: file_stream
        file_format: parquet
        schema: event_id STRING, category STRING, amount DOUBLE, ts TIMESTAMP
        options: {path: "${paths.output}/${env}/bronze/events"}
      output:
        format: parquet
        path: ${paths.output}/${env}/silver/events
      streaming:
        checkpoint_location: ${paths.output}/${env}/_ckpt/clean_events
"""
        }

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
    def fn(df, params)    -> DataFrame     # `params` is the node's transform.params

Nodes reference a transform by the name it was registered under, not by import
path — in pipelines/events_stream.yaml:

    transform: {key: clean_events, module: pipelines.transforms, params: {min_amount: 0.0}}

`register_transforms` is called automatically before the node starts, because
the transform names this module. Run
`ducta stream run --pipeline events_stream --env dev` and drop another .json
file into data/events/ to watch it picked up.
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

    The registry maps a name to a callable; a stream node's `transform: {key: ...}`
    in its pipeline file is what looks it up.
    """
    registry.register("clean_events", clean_events)
    logger.info("Registered streaming transforms: clean_events")
'''

    def quick_start(self) -> List[str]:
        pipeline = self.DEFAULT_PIPELINE
        return [
            "# Start the stream (runs until you stop it)",
            f"ducta stream run --pipeline {pipeline} --env dev",
            "",
            "# In another shell: watch it, then stop it",
            "ducta stream status --env dev",
            "ducta stream stop --env dev --execution-id <id>",
        ]

    def readme(self) -> str:
        """README for a streaming project, which runs differently from a batch one."""
        return f"""# {self.project_name}

A **Structured Streaming** pipeline built with **Ducta**.

## Run it

```bash
pip install -r requirements.txt

# Start the stream (runs until you stop it)
ducta stream run --pipeline events_stream --env dev

# In another shell: watch it, then stop it
ducta stream status --env dev
ducta stream stop --env dev --execution-id <id>
```

`data/events/` ships five seed events. Two have a null `amount`, so the silver
layer visibly drops rows the bronze layer kept. Drop another `.json` file into
that folder while the stream runs and watch it get picked up.

## What is different from a batch pipeline

**1. A stream node names a registered transform, not `run: module:function`.**

```yaml
clean_events:
  kind: stream
  stream:
    transform: {{key: clean_events, module: pipelines.transforms, params: {{min_amount: 0.0}}}}
```

`module` is imported and its `register_transforms(registry)` registers the
function under `key`. It is called `fn(df)` or `fn(df, params)` — no
`start_date`/`end_date`, because a stream has no date range.

**2. Ordering is explicit: `after: [ingest_events]`.** A stream node's input
and output are inline paths, not catalog datasets, so Ducta cannot infer it.

**3. Every node needs its own `checkpoint_location`.** Two nodes sharing one
corrupt each other's offsets. Delete a node's checkpoint directory to replay
its source from the beginning.

## A run that finishes: backfills and CI

With a terminating trigger the queries process what exists and stop; a node
waits for the node it reads from to finish first. Set it for one environment
in `ducta.yaml`:

```yaml
environments:
  sandbox:
    pipelines.events_stream.nodes.ingest_events.stream.streaming.trigger: {{type: available_now}}
    pipelines.events_stream.nodes.clean_events.stream.streaming.trigger: {{type: available_now}}
```

```bash
ducta stream run --pipeline events_stream --env sandbox --mode sync
```

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

## Layout

```
{self.project_name}/
├── ducta.yaml                    # project, paths, settings, per-environment overrides
├── catalog.yaml                  # datasets (stream nodes declare their own I/O)
├── pipelines/events_stream.yaml  # the pipeline and its stream nodes
├── pipelines/transforms.py       # your streaming transforms + register_transforms
└── data/events/                  # the watched source directory
```

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


class MLBasicTemplate(BaseTemplate):
    """A churn model end to end: features in Spark, training in scikit-learn.

    What a first ML pipeline gets wrong is rarely the model: it is an unseeded
    split, hyperparameters buried in code, and a model shipped without asking
    whether it beats predicting the majority class. Each is declared in the
    pipeline file here (``split``, ``hyperparams``) or enforced by the node
    (the baseline gate), and the README says which is which.
    """

    TEMPLATE_NAME = "ML Basic"
    TEMPLATE_DESCRIPTION = (
        "Churn model: Spark features, scikit-learn training, declarative split, "
        "versioned hyperparameters and a baseline gate"
    )
    TEMPLATE_TYPE = "ml_basic"
    ARCHITECTURE = "ml"
    SAMPLE_MODULE = "pipelines.churn"
    SAMPLE_MODULE_PATH = ("pipelines", "churn.py")
    DEFAULT_PIPELINE = "churn_model"
    REQUIREMENTS = "ducta[spark,mlops]>=0.1.1\n"
    GITIGNORE_EXTRA = "\n# Models and experiment tracking\nmodels/\nmlops_data/\n"

    def quick_start(self) -> List[str]:
        pipeline = self.DEFAULT_PIPELINE
        return [
            "# Train the model (tracked, with a baseline gate)",
            f"ducta start -e dev -p {pipeline}",
            "",
            "# Override a hyperparameter for one run",
            f"ducta start -e dev -p {pipeline} --hyperparams '{{\"max_depth\": 3}}'",
            "",
            "# Validate config, no Spark",
            "ducta config validate --env dev",
        ]

    def project_yaml(self) -> str:
        return self._render(
            """\
# yaml-language-server: $schema=.ducta/schema/project.json
#
# The project: its name, where data lives, engine settings, and what changes
# per environment. Datasets are in catalog.yaml, the pipeline in pipelines/.
version: 2
project: @@PROJECT@@
description: Customer churn model - Spark features, scikit-learn training

# Base directories. Reference them anywhere as ${paths.input} / ${paths.output}.
paths: {input: data, output: data}

settings:
  mode: local                  # local | distributed | databricks
  max_parallel_nodes: 2
  fail_on_error: true
  # off | record | required | signed: what a run can prove about itself.
  evidence_level: @@EVIDENCE@@
  # Seeds random / numpy and gives every node its own deterministic seed
  # (ml_context["node_seed"]), so a run can be repeated exactly.
  random_seed: 42
@@SPARK@@  # Experiments, runs and the model registry. `type: ml` pipelines are tracked
  # automatically; mlops_required: true aborts a run that cannot be tracked.
  mlops_enabled: true
  mlops_required: false
  mlops_path: mlops_data

# Values a dataset or node gets unless it sets its own: the format per layer.
defaults:
  catalog:
    "silver.*": {format: parquet}
    "gold.*": {format: csv}

# An environment states only what differs from the base project above.
environments:
  dev:
    settings: {log_level: DEBUG}
  prod:
    # In production a model that cannot be tracked must not be shipped.
    settings: {mlops_required: true}
"""
            + self._sandbox_note()
            + """
# Free-form notes. Ducta does not read this block.
metadata:
  template: ml_basic
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# Every dataset, once. The format of silver.* and gold.* comes from
# `defaults.catalog` in ducta.yaml.

customers:
  description: One row per customer, with whether they churned
  format: csv
  path: data/customers.csv
  options: {header: true, inferSchema: true}
  # A contract: checked every time a node reads this dataset, before it runs.
  checks:
    fail_fast: true
    empty_dataset: true
    schema:
      expected_columns: [customer_id, tenure_months, monthly_spend, support_calls, plan, churned]

silver.churn.features:
  description: Clean, de-duplicated model inputs

gold.churn.metrics:
  description: What the trained model scored, against the baseline
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "churn_model": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# An ML pipeline versions what a notebook would bury in code: the split and the
# hyperparameters live here, so every run records exactly what it used. Override
# hyperparameters for one run with `--hyperparams '{"max_depth": 3}'`.
description: "Churn: prepare features, train, register the model"
type: ml
requires_dates: false
model_version: "1.0.0"

hyperparams: {n_estimators: 100, max_depth: 6}

# Applied by the training node with ducta.mlrun.split_dataframe. Model selection
# happens on `val`; `test` is scored once, at the end, for an honest estimate.
split: {method: stratified, stratify_col: churned, test_size: 0.2, val_size: 0.2, seed: 42}

nodes:
  prepare_features:
    description: "Drop duplicates and incomplete rows; keep what the model may see"
    run: pipelines.churn:prepare_features
    inputs: {customers: customers}
    outputs: [silver.churn.features]
    # Checks on this node's OUTPUT, before it is written.
    quality:
      empty_dataset: true
      null_rate: {columns: [tenure_months, monthly_spend, plan, churned], threshold: 0.0}
      duplicates: {columns: [customer_id], max_duplicate_rate: 0.0}
      range: {column: tenure_months, min: 0}
      row_count: {min: 500}
      gate: {max_errors: 0, on_fail: skip_downstream}

  train:
    description: "Train a random forest; register it only if it beats the baseline"
    run: pipelines.churn:train
    ml_stage: training
    inputs: {features: silver.churn.features}
    outputs: [gold.churn.metrics]
"""
        }

    #: Customers with a blank ``monthly_spend`` and customers repeated verbatim,
    #: so the feature node has something real to drop (as in the medallion data).
    _BLANK_SPEND = frozenset({17, 83, 140, 222, 301, 377, 450, 512, 560, 589})
    _DUPLICATED = (5, 99, 187, 264, 333, 401)
    _PLANS = ("basic", "plus", "pro")

    def seed_files(self) -> Dict[str, str]:
        """``data/customers.csv``: churn driven by support calls, short tenure and the basic plan."""
        scored = []
        for i in range(1, 601):
            plan = self._PLANS[i % 3]
            noise = (((i * 1103515245 + 12345) % 2147483648) / 2147483648 - 0.5) * 3.0
            support = (i * 5) % 7
            tenure = 1 + (i * 7) % 60
            plan_effect = 1.0 if plan == "basic" else -0.5 if plan == "pro" else 0.0
            score = 0.7 * support - 0.04 * tenure + plan_effect + noise
            scored.append((i, tenure, support, plan, score))
        cutoff = sorted(s[4] for s in scored)[int(len(scored) * 0.7)]
        rows = []
        for i, tenure, support, plan, score in scored:
            if i in self._BLANK_SPEND:
                spend = ""
            else:
                spend = f"{20 + (i * 13) % 80 + (15 if plan == 'pro' else 0)}.00"
            rows.append(f"{i},{tenure},{spend},{support},{plan},{1 if score > cutoff else 0}")
        by_id = {int(r.split(",", 1)[0]): r for r in rows}
        rows.extend(by_id[i] for i in self._DUPLICATED)
        header = "customer_id,tenure_months,monthly_spend,support_calls,plan,churned"
        return {"data/customers.csv": "\n".join([header, *rows]) + "\n"}

    def generate_sample_code(self) -> Optional[str]:
        return '''"""
Churn model: prepare features in Spark, then train and register with scikit-learn.

``prepare_features`` receives and returns a Spark DataFrame. ``train`` converts
its input to pandas, which is what scikit-learn takes. Ducta also hands any node
that accepts it an
``ml_context``: the versioned hyperparameters and split, a deterministic seed,
and the experiment tracker and model registry of the run it already opened.

Four habits this module keeps, and your own nodes should too:

1. a reproducible split, with the seed from config, never an unseeded one;
2. hyperparameters from ``pipelines/churn_model.yaml``, never hard-coded;
3. a baseline: a model is only worth registering if it beats the trivial one;
4. the test set is scored once, after the model is chosen on validation data.
"""
from typing import Any, Optional

from loguru import logger


def prepare_features(
    customers: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Drop duplicates and incomplete rows, and keep only what the model may see.

    Rows with a missing value are dropped, not filled: inventing a spend of 0
    would teach the model that "unknown" means "free", and would also make the
    ``null_rate`` check in the pipeline pass for the wrong reason.
    """
    from pyspark.sql import functions as F

    before = customers.count()
    cleaned = (
        customers.dropDuplicates(["customer_id"])
        .dropna(subset=["tenure_months", "monthly_spend", "plan", "churned"])
        .withColumn("churned", F.col("churned").cast("int"))
        .select(
            "customer_id",
            "tenure_months",
            "monthly_spend",
            "support_calls",
            "plan",
            "churned",
        )
    )
    logger.info("Features: kept {:,} of {:,} customers", cleaned.count(), before)
    return cleaned


def train(features: Any, ml_context: Any = None) -> Any:
    """Train a random forest and register it if it beats the majority-class baseline."""
    import pandas as pd
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import f1_score, roc_auc_score

    from ducta.mlrun import persist_model, split_dataframe

    ml_context = ml_context or {}
    params = {"n_estimators": 100, "max_depth": 6, **(ml_context.get("hyperparams") or {})}
    seed = ml_context.get("node_seed", 42)

    # The model needs pandas. Converting here, not in the catalog, works whether
    # the dataset is read back from disk or handed over in memory.
    if hasattr(features, "toPandas"):
        features = features.toPandas()

    # One-hot encode `plan`; it has three fixed values, so doing it before the
    # split leaks nothing.
    data = pd.get_dummies(features.drop(columns=["customer_id"]), columns=["plan"], dtype=int)

    # The split is declared in pipelines/churn_model.yaml. Passing ml_context
    # lets the run certificate prove this is the split that actually ran.
    train_df, val_df, test_df = split_dataframe(
        data, ml_context.get("split"), default_seed=seed, ml_context=ml_context
    )
    target = "churned"
    x_train, y_train = train_df.drop(columns=[target]), train_df[target]
    x_val, y_val = val_df.drop(columns=[target]), val_df[target]
    x_test, y_test = test_df.drop(columns=[target]), test_df[target]

    baseline = DummyClassifier(strategy="prior").fit(x_train, y_train)
    baseline_auc = roc_auc_score(y_val, baseline.predict_proba(x_val)[:, 1])  # 0.5: no signal

    model = RandomForestClassifier(**params, random_state=seed).fit(x_train, y_train)
    val_auc = roc_auc_score(y_val, model.predict_proba(x_val)[:, 1])
    # Scored once, after the model is chosen: never used to tune or to decide.
    test_auc = roc_auc_score(y_test, model.predict_proba(x_test)[:, 1])
    test_f1 = f1_score(y_test, model.predict(x_test))
    logger.info("AUC val={:.3f} test={:.3f} (baseline {:.3f})", val_auc, test_auc, baseline_auc)

    # A gate relative to the baseline, not an absolute threshold: on imbalanced
    # data the majority-class predictor can clear almost any fixed bar.
    if val_auc < baseline_auc + 0.05:
        raise ValueError(
            f"The model does not beat the baseline: val AUC {val_auc:.3f} vs {baseline_auc:.3f}"
        )

    metrics = {
        "val_auc": float(val_auc),
        "test_auc": float(test_auc),
        "test_f1": float(test_f1),
        "baseline_auc": float(baseline_auc),
    }
    persist_model(
        model,
        ml_context,
        name="churn-model",
        framework="sklearn",
        metrics=metrics,
        hyperparameters=params,
        X=x_train,
        y=y_train,
    )
    return pd.DataFrame([metrics])
'''

    def readme(self) -> str:
        return f"""# {self.project_name}

A **customer churn** pipeline built with **Ducta**: features in Spark, a
scikit-learn model, and the things that make a model trustworthy declared in
configuration rather than buried in code.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline churn_model
```

`data/customers.csv` is deliberately imperfect: 10 customers with no
`monthly_spend` and 6 repeated rows, so `prepare_features` has work to do and
its quality gate has something to verify.

```
customers          606 rows   as they arrived
silver features    590 rows   de-duplicated, incomplete rows dropped
gold metrics         1 row    val / test AUC, F1 and the baseline AUC
```

## What lives where

| | Where | Why there |
|---|---|---|
| Split (stratified, 60/20/20, seed 42) | `pipelines/churn_model.yaml` | versioned and recorded with every run |
| Hyperparameters | `pipelines/churn_model.yaml` | override once with `--hyperparams '{{"max_depth": 3}}'` |
| Random seed | `ducta.yaml` (`random_seed`) | one number makes a run repeatable |
| Experiment tracking, model registry | `ducta.yaml` (`mlops_*`) | `type: ml` pipelines are tracked automatically |
| Baseline gate | `pipelines/churn.py` | the model is registered only if it beats the trivial one |

## Then look at what happened

```bash
ducta certify list                       # every run recorded here
ducta certify show   --run-id <run-id>   # what ran, on which data, with which split
ducta config validate                    # config check, no Spark
```

## Project structure

```
{self.project_name}/
├── ducta.yaml                    # project, paths, settings, per-environment overrides
├── catalog.yaml                  # every dataset once (the source has a contract)
├── pipelines/
│   ├── churn_model.yaml          # the ML pipeline: split, hyperparameters, nodes
│   └── churn.py                  # prepare_features (Spark) and train (scikit-learn)
├── .ducta/schema/                # JSON Schemas: autocompletion in VS Code/JetBrains
└── data/customers.csv            # sample source
```

## What to change first

1. Point `customers` in `catalog.yaml` at your own data, and update its `schema` contract.
2. Replace the target, the feature columns and the model in `pipelines/churn.py`.
3. Keep the split, the baseline gate and the one-time test score.

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


class HybridBasicTemplate(BaseTemplate):
    """One pipeline whose batch phase feeds its streaming phase.

    ``type: hybrid`` runs every batch node to the end, with the full batch
    engine (parallelism, retries, quality gates), and only then starts the
    queries, so a stream node can depend on a batch node. A batch *pipeline*
    cannot depend on a streaming one, because a stream never completes. The
    stream here is a ``file_stream`` over JSON files, so it runs with nothing
    installed but Spark; swapping it for Kafka is shown in the README.
    """

    TEMPLATE_NAME = "Hybrid Basic"
    TEMPLATE_DESCRIPTION = (
        "Batch dimension table feeding a stream-static join, in one `type: hybrid` pipeline"
    )
    TEMPLATE_TYPE = "hybrid_basic"
    ARCHITECTURE = "hybrid"
    SAMPLE_MODULE = "pipelines.orders"
    SAMPLE_MODULE_PATH = ("pipelines", "orders.py")
    DEFAULT_PIPELINE = "orders"

    def quick_start(self) -> List[str]:
        pipeline = self.DEFAULT_PIPELINE
        return [
            "# Run the batch phase, then the stream, to completion",
            f"ducta start -e dev -p {pipeline} --mode sync",
            "",
            "# Validate config, no Spark",
            "ducta config validate --env dev",
        ]

    def project_yaml(self) -> str:
        return self._render(
            """\
# yaml-language-server: $schema=.ducta/schema/project.json
#
# The project: its name, where data lives, engine settings, and what changes
# per environment. Batch datasets are in catalog.yaml; the stream node declares
# its own source and sink in pipelines/orders.yaml.
version: 2
project: @@PROJECT@@
description: Batch dimension table enriching an order stream

# Base directories. Reference them anywhere as ${paths.input} / ${paths.output}.
paths: {input: data, output: data}

settings:
  mode: local                  # local | distributed | databricks
  max_parallel_nodes: 2
  fail_on_error: true
  # off | record | required | signed: what a run can prove about itself.
  evidence_level: @@EVIDENCE@@
@@SPARK@@  # Imported before any stream starts, so the transform is registered by the
  # time the node that names it is built.
  streaming_transform_modules: [pipelines.orders]
  max_streaming_pipelines: 5

# Values a dataset or node gets unless it sets its own.
defaults:
  catalog:
    "silver.*": {format: parquet}

# An environment states only what differs from the base project above.
environments:
  dev:
    settings: {log_level: DEBUG}
"""
            + self._sandbox_note()
            + """
# Free-form notes. Ducta does not read this block.
metadata:
  template: hybrid_basic
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# The batch side's datasets. The stream node's source and sink are inline in
# pipelines/orders.yaml; its output is not a catalog dataset.

products:
  description: Product dimension (reference data, updated by batch)
  format: csv
  path: data/products.csv
  options: {header: true, inferSchema: true}
  checks:
    fail_fast: true
    empty_dataset: true
    schema: {expected_columns: [product_id, category, unit_price]}

silver.shop.products:
  description: Clean product dimension, the static side of the stream join
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "orders": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# `type: hybrid`: the batch node runs to the end first, then the query starts.
# If the batch phase fails or a gate blocks it, no query starts. A stream node
# says what it waits for with `after:` (its input is inline, so Ducta cannot
# infer the order from a dataset).
description: "Hybrid: build the product dimension (batch), then enrich orders (stream)"
type: hybrid
requires_dates: false

nodes:
  # -- batch phase ----------------------------------------------------------
  build_products:
    description: "Clean the product dimension and write it as Parquet"
    run: pipelines.orders:build_products
    inputs: {products_raw: products}
    outputs: [silver.shop.products]
    quality:
      empty_dataset: true
      null_rate: {columns: [product_id, unit_price], threshold: 0.0}
      duplicates: {columns: [product_id], max_duplicate_rate: 0.0}
      gate: {max_errors: 0, on_fail: skip_downstream}

  # -- streaming phase ------------------------------------------------------
  enrich_orders:
    description: "Join each order with its product and compute the revenue"
    kind: stream
    after: [build_products]
    stream:
      input:
        format: file_stream
        file_format: json
        # Required: a stream cannot infer its schema.
        schema: order_id STRING, product_id INT, quantity INT, ts TIMESTAMP
        options:
          path: ${paths.input}/orders
          # One file per micro-batch, so the demo shows several batches.
          maxFilesPerTrigger: 1
      # `params` is a plain dict and cannot carry a DataFrame, so the dimension
      # is passed as a path and read inside the transform. Keep it under a key
      # named `path`: that is what gets ${paths.output} and ${env} expanded.
      transform:
        key: enrich_orders
        module: pipelines.orders
        params:
          products: {path: "${paths.output}/${env}/silver/shop/products"}
      output:
        format: parquet
        path: ${paths.output}/${env}/gold/shop/orders_enriched
      streaming:
        checkpoint_location: ${paths.output}/${env}/_ckpt/enrich_orders
        output_mode: append
        # Processes what is there and stops, so the whole pipeline finishes and
        # can run in CI. Use `10s` to keep the query running instead.
        trigger: available_now
"""
        }

    _CATEGORIES = ("electronics", "grocery", "apparel", "home", "toys")

    def seed_files(self) -> Dict[str, str]:
        """``data/products.csv`` (one dirty row) and five order files, one event each."""
        rows = [
            f"{pid},{self._CATEGORIES[pid % len(self._CATEGORIES)]},{5 + (pid * 11) % 90}.50"
            for pid in range(1, 31)
        ]
        # A verbatim duplicate: build_products deduplicates, and its gate checks it.
        rows.append(rows[6])
        files = {"data/products.csv": "\n".join(["product_id,category,unit_price", *rows]) + "\n"}
        for n in range(1, 6):
            events = [
                '{"order_id": "o%d%d", "product_id": %d, "quantity": %d, "ts": "2026-01-01T10:%02d:00"}'
                % (n, k, 1 + (n * 7 + k * 5) % 30, 1 + (n + k) % 4, n * 10 + k)
                for k in range(1, 4)
            ]
            files[f"data/orders/orders_{n:03d}.json"] = "\n".join(events) + "\n"
        return files

    def generate_sample_code(self) -> Optional[str]:
        return '''"""
The batch node and the streaming transform of the `orders` hybrid pipeline.

``build_products`` is an ordinary batch node. ``enrich_orders`` is a streaming
transform: Ducta calls it as ``fn(df)`` or ``fn(df, params)`` with the
streaming DataFrame, and it must return one. It gets no start/end date,
because a stream has no date range.
"""
from typing import Any, Dict, Optional

from loguru import logger


def build_products(
    products_raw: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Drop repeated products so the join below matches each order exactly once."""
    cleaned = products_raw.dropDuplicates(["product_id"])
    logger.info("Products: {:,} distinct", cleaned.count())
    return cleaned


def enrich_orders(df: Any, params: Optional[Dict[str, Any]] = None) -> Any:
    """Stream-static join: attach each order's category and compute its revenue.

    The products are plain Parquet written by the batch node. Spark treats a
    static DataFrame joined with a streaming one as a stream-static join and
    reads the table as it is at the start of each micro-batch, so re-running
    ``build_products`` with corrected data is picked up by a running stream.
    """
    from pyspark.sql import functions as F

    path = ((params or {}).get("products") or {}).get("path")
    if not path:
        raise ValueError("enrich_orders needs params.products.path (see pipelines/orders.yaml)")
    products = df.sparkSession.read.parquet(path).select("product_id", "category", "unit_price")
    return (
        df.join(products, "product_id", "left")
        .withColumn("revenue", F.round(F.col("quantity") * F.col("unit_price"), 2))
        .select("order_id", "product_id", "category", "quantity", "revenue", "ts")
    )


def register_transforms(registry: Any) -> None:
    """Called by Ducta before the pipeline starts: maps the name a node uses to the function."""
    registry.register("enrich_orders", enrich_orders)
    logger.info("Registered streaming transforms: enrich_orders")
'''

    def readme(self) -> str:
        return f"""# {self.project_name}

A **hybrid** pipeline built with **Ducta**: a batch node builds a product
dimension, then a streaming query enriches a stream of orders against it, all
in one execution.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline orders --mode sync
```

`type: hybrid` runs the batch phase to the end first (with its quality gate),
and only then starts the query. If the batch phase fails or the gate blocks it,
no query starts. The query uses `trigger: available_now`: it processes the five
order files in `data/orders/` and stops, so the run finishes and fits in CI.

```
products.csv        31 rows    one repeated product
silver products     30 rows    de-duplicated, the static side of the join
gold orders         15 rows    each order with its category and revenue
```

## What is different from a batch pipeline

**1. Order between a stream node and the rest is explicit.** The stream node's
input is inline, so Ducta cannot infer the order from a dataset:
`after: [build_products]`.

**2. A transform cannot receive a DataFrame.** `params` is a plain dict, so the
dimension travels as a *path* and the transform reads it. Keep the path under a
key named `path`: that is what gets `${{paths.output}}` and `${{env}}` expanded.

**3. A batch pipeline cannot depend on a streaming one**, because a stream never
completes. Inside a `type: hybrid` pipeline, a stream can depend on batch nodes.

## Keep the query running

Replace `trigger: available_now` with `trigger: 10s` in `pipelines/orders.yaml`,
start it with `ducta stream run --pipeline orders --env dev`, and drop another
`.json` file into `data/orders/` to watch it picked up.

## Switching the source to Kafka

Replace the `input` block of `enrich_orders`:

```yaml
input:
  format: kafka
  options:
    kafka.bootstrap.servers: "localhost:9092"
    subscribe: "orders"
    startingOffsets: "latest"
```

Kafka delivers `key`/`value` as bytes, so parse the JSON in your transform
(`from_json(col("value").cast("string"), schema)`) before the join.

## Project structure

```
{self.project_name}/
├── ducta.yaml                  # project, paths, settings, per-environment overrides
├── catalog.yaml                # the batch datasets (the source has a contract)
├── pipelines/
│   ├── orders.yaml             # the hybrid pipeline: a batch node, then a stream node
│   └── orders.py               # build_products + the streaming transform
├── .ducta/schema/              # JSON Schemas: autocompletion in VS Code/JetBrains
└── data/
    ├── products.csv            # sample dimension
    └── orders/                 # the watched source directory
```

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


class TemplateGenerator:
    """Generates complete project templates with directory structure."""

    #: The project files' formats a template can be written in.
    FORMATS = (ConfigFormat.YAML, ConfigFormat.TOML, ConfigFormat.JSON)

    def __init__(self, output_path: Path, config_format: ConfigFormat = ConfigFormat.YAML):
        if config_format not in self.FORMATS:
            raise TemplateError(
                "Project configuration is YAML, TOML or JSON "
                f"(got '{config_format.value}'): ducta.<ext>, catalog.<ext>, pipelines/"
            )
        self.output_path = Path(output_path)
        self.config_format = config_format

    def generate_project(
        self,
        template_type: TemplateType,
        project_name: str,
        create_sample_code: bool = True,
        developer_sandboxes: Optional[List[str]] = None,
        evidence_level: str = "record",
    ) -> None:
        """Generate a project: ducta.yaml + catalog.yaml + pipelines/*.yaml, and code."""
        logger.info("Generating {} template for project '{}'", template_type.value, project_name)

        template = TemplateFactory.create_template(template_type, project_name, self.config_format)
        template.evidence_level = evidence_level
        template.developer_sandboxes = list(developer_sandboxes or [])
        self.template = template

        self._write_config_files(template)

        if create_sample_code:
            self._generate_sample_code(template)

        self._generate_project_files(template)
        self._write_text_file(self.output_path / "README.md", template.readme())

        logger.success("Project '{}' generated successfully at {}", project_name, self.output_path)

    def _write_config_files(self, template: BaseTemplate) -> None:
        """``ducta.*``, ``catalog.*``, ``pipelines/*.*`` and the editor schemas."""
        from ducta.setting.project_decompile import write_schemas

        ext = self.config_format.value
        schemas = ".ducta/schema"
        self._write_text_file(
            self.output_path / f"ducta.{ext}",
            self._as_format(template.project_yaml(), f"{schemas}/project.json"),
        )
        self._write_text_file(
            self.output_path / f"catalog.{ext}",
            self._as_format(template.catalog_yaml(), f"{schemas}/catalog.json"),
        )
        pipelines_dir = self.output_path / "pipelines"
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        (pipelines_dir / "__init__.py").touch()
        for name, text in template.pipeline_yamls().items():
            self._write_text_file(
                pipelines_dir / f"{name}.{ext}",
                self._as_format(text, f"../{schemas}/pipeline.json"),
            )
        write_schemas(self.output_path)

    def _as_format(self, yaml_text: str, schema: str) -> str:
        """The template's YAML text, as the generator's format.

        YAML is written as is, comments included. TOML and JSON are the same
        document converted, so the explanatory comments are not carried over
        (JSON has none; TOML's would need a second copy of every template).
        """
        if self.config_format == ConfigFormat.YAML:
            return yaml_text
        import yaml  # type: ignore

        data = yaml.safe_load(yaml_text) or {}
        if self.config_format == ConfigFormat.JSON:
            import json

            return json.dumps({"$schema": schema, **data}, indent=2, ensure_ascii=False) + "\n"
        try:
            import tomli_w  # type: ignore
        except ImportError as e:
            raise TemplateError(
                "TOML template generation requires 'tomli-w'. Install with: pip install tomli-w"
            ) from e
        return f"#:schema {schema}\n" + tomli_w.dumps(data)

    def _localize(self, text: str) -> str:
        """Point a README or docstring at ``ducta.toml`` instead of ``ducta.yaml``, and so on."""
        import re

        ext = self.config_format.value
        text = re.sub(r"\b(ducta|catalog)\.yaml\b", rf"\1.{ext}", text)
        return re.sub(r"(pipelines/[\w.]+)\.yaml\b", rf"\1.{ext}", text)

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

Each layer does real work, and the quality checks in ``pipelines/etl.yaml``
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

    Ducta has already loaded ``source_data`` per ``catalog.yaml`` (format,
    header, inferSchema), and will write the return value per
    ``catalog.yaml``. You only write the transformation.
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
2. Implement ``_run_impl()`` and return ``self._create_result(...)``. An
   exception it raises becomes a failed result, not a crashed run.
3. Add the module to ``settings.quality.extensions`` in ``ducta.yaml``:

   .. code-block:: yaml

       settings:
         quality:
           extensions:
             - pipelines.checks.custom_checks

4. Use the check in any node's ``quality`` block (or a dataset's ``checks`` in
   ``catalog.yaml``):

   .. code-block:: yaml

       my_node:
         quality:
           checks:
             positive_values: {column: amount}

"""
from ducta.check import BaseQualityCheck, CheckSeverity, register_check


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

    def _run_impl(self, df, config, adapter, context_datasets=None):
        column = getattr(config, "column", None)
        if not column:
            return self._create_result(False, "'column' is required for positive_values check")

        # The adapter runs the same SQL condition on Spark and pandas.
        non_positive = adapter.filter_where(f"{column} <= 0")
        if non_positive > 0:
            return self._create_result(
                False,
                f"Column '{column}' has {non_positive} non-positive values",
                {"column": column, "non_positive_count": non_positive},
            )
        return self._create_result(True, f"All values in '{column}' are positive")


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
#     def _run_impl(self, df, config, adapter, context_datasets=None):
#         column = getattr(config, "column", "email")
#         allowed = getattr(config, "allowed_domains", [])
#         ...
'''
        custom_file = checks_dir / "custom_checks.py"
        self._write_text_file(custom_file, custom_checks_code)

    def _generate_project_files(self, template: MedallionBasicTemplate) -> None:
        """Generate the supporting files (the README is written with the configuration)."""
        self._write_support_files(template)

    def _write_support_files(self, template: BaseTemplate) -> None:
        """requirements, .gitignore and seed data — identical for every template."""
        # requirements.txt - minimal but complete
        # `ducta[spark]` rather than ducta + a loose pyspark pin: the extra is
        # what the project actually declares as compatible, and pinning pyspark
        # separately invites a combination Ducta was never tested against.
        requirements = template.REQUIREMENTS
        requirements_file = self.output_path / "requirements.txt"
        self._write_text_file(requirements_file, requirements)

        # .gitignore
        gitignore = (
            """__pycache__/
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

# Data: what a run writes, per environment (`paths.output` is data/)
data/dev/
data/sandbox/
data/sandbox_*/
data/prod/
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
            + template.GITIGNORE_EXTRA
        )
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

        for relative, text in template.seed_files().items():
            self._write_text_file(self.output_path / relative, text)

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
        if self.config_format != ConfigFormat.YAML and file_path.suffix in (".py", ".md"):
            content = self._localize(content)
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
        create_sample_code: bool = True,
        list_templates: bool = False,
        sandbox_developers: Optional[List[str]] = None,
        evidence_level: str = "record",
        config_format: str = "yaml",
    ) -> int:
        """Handle template generation command."""
        try:
            if list_templates:
                return self._list_templates()

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
                create_sample_code,
                sandbox_developers,
                evidence_level,
                config_format,
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
            "  ducta template --template streaming_basic --project-name events --evidence-level signed"
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
        create_sample_code: bool,
        sandbox_developers: Optional[List[str]] = None,
        evidence_level: str = "record",
        config_format: str = "yaml",
    ) -> int:
        """Generate template with specified parameters."""
        try:
            template_enum = self._parse_enum_or_error(
                TemplateType, template_type, "template type", "types"
            )
            if template_enum is None:
                return ExitCode.VALIDATION_ERROR.value

            if not output_path:
                output_path = f"./{project_name}"

            output_dir = Path(output_path)

            if output_dir.exists() and any(output_dir.iterdir()):
                logger.warning("Directory {} already exists and is not empty", output_dir)
                logger.info(_TEMPLATE_CANCELLED_MSG)
                return ExitCode.VALIDATION_ERROR.value

            self.generator = TemplateGenerator(output_dir, ConfigFormat(config_format))
            self.generator.generate_project(
                template_enum,
                project_name,
                create_sample_code,
                sandbox_developers,
                evidence_level=evidence_level,
            )

            self._show_success_message(project_name, output_dir, self.generator.template)

            return ExitCode.SUCCESS.value

        except Exception as e:
            logger.error("Template generation failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _show_success_message(
        self, project_name: str, output_dir: Path, template: "BaseTemplate"
    ) -> None:
        """Show success message with next steps, tailored to *template*'s
        module path, default pipeline and run command — these differ between
        a batch template (``ducta start``) and a streaming one (``ducta
        stream run``)."""
        ext = self.generator.config_format.value if self.generator else "yaml"
        logger.success("✅ Project '{}' created successfully!", project_name)
        logger.info("📁 Location: {}", output_dir.absolute())
        logger.info("\n📋 Next steps:")
        logger.info("1️⃣  cd {}", output_dir)
        logger.info("2️⃣  pip install -r requirements.txt")
        logger.info("3️⃣  Point catalog.{} at your data", ext)
        logger.info(
            "4️⃣  Customize {} and pipelines/{}.{}",
            "/".join(template.SAMPLE_MODULE_PATH),
            template.DEFAULT_PIPELINE,
            ext,
        )
        logger.info("5️⃣  Per-environment differences go under `environments:` in ducta.{}", ext)

        logger.info("\n🚀 Quick start:")
        for line in template.quick_start():
            logger.info("   {}", line)

        logger.info("\n🗂  What was generated:")
        logger.info("   ducta.{}     project, paths, settings, per-environment overrides", ext)
        logger.info("   catalog.{}   every dataset, once (format, path, contracts)", ext)
        logger.info("   pipelines/     one file per pipeline, plus the Python it runs")
        logger.info("   .ducta/schema/ JSON Schemas: editor autocompletion and inline errors")

        logger.info("\n📖 More info: Check README.md or run 'ducta --help'")


def handle_template_command(parsed_args) -> int:
    """Handle template command execution from CLI."""
    template_cmd = TemplateCommand()

    return template_cmd.handle_template_command(
        template_type=parsed_args.template,
        project_name=parsed_args.project_name,
        output_path=parsed_args.output_path,
        create_sample_code=not parsed_args.no_sample_code,
        list_templates=parsed_args.list_templates,
        sandbox_developers=getattr(parsed_args, "sandbox_developers", None),
        evidence_level=getattr(parsed_args, "evidence_level", None) or "record",
        config_format=getattr(parsed_args, "config_format", None) or "yaml",
    )


def _medallion_readme_v2(template: "BaseTemplate") -> str:
    """README for a format-2 medallion project."""
    return f"""# {template.project_name}

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
ducta certify verify --run-id <run-id>   # integrity (+ signature, with the key)
```

## See the quality gate work

`pipelines/etl.yaml` asserts on the silver layer that `amount` has no nulls, no
negative values, and `order_id` has no duplicates, with a gate of
`max_errors: 0`. To watch it block:

1. Open `pipelines/etl.py` and comment out the `cleaned.dropna()` line in
   `transform`.
2. Re-run `ducta start --env dev --pipeline etl`.

The gate blocks, `load` is skipped, and **gold is never written**.

## Project structure

```
{template.project_name}/
├── ducta.yaml             # project, paths, settings, per-environment overrides
├── catalog.yaml           # every dataset once: format, path, how it is written,
│                          #   and the checks it must always pass (contracts)
├── pipelines/
│   ├── etl.yaml           # the pipeline: its nodes, their inputs/outputs, checks
│   ├── etl.py             # your transformations (plain functions)
│   └── checks/custom_checks.py
├── .ducta/schema/         # JSON Schemas: autocompletion in VS Code/JetBrains
└── data/
    ├── input.csv          # sample source
    └── dev/               # bronze/ silver/ gold/ written per environment
```

An environment only states what differs — for example, in `ducta.yaml`:

```yaml
environments:
  prod:
    settings: {{max_parallel_nodes: 8, evidence_level: signed}}
    paths: {{output: s3://my-lake/prod}}
```

## What to change first

1. Point `source_data` in `catalog.yaml` at your own data.
2. Rewrite the three functions in `pipelines/etl.py`.
3. Update the checks in `pipelines/etl.yaml` to assert what *your* transform
   guarantees.

## Useful commands

```bash
ducta config list-pipelines                  # what is defined here
ducta config validate                        # config check, no Spark
ducta config schema --out .                  # refresh the editor schemas
ducta server start --port 8000               # web UI (needs the `api` extra)
```

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
