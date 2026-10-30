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

The ``streaming_basic`` template: a file stream, cleaned and landed.
"""

from datetime import datetime
from typing import Dict, List, Optional

from ducta.console.templates.base import BaseTemplate


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
