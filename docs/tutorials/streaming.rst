Streaming Pipelines Tutorial (Basic to Advanced)
=================================================

This guide walks you through practical streaming pipeline examples in Ducta,
from local file ingestion to dependency-aware multi-node Kafka + Delta flows.

**Execution model in this tutorial**: CLI using ``ducta stream``

.. note::

    Commands and configuration blocks in this tutorial are aligned with the
    current streaming module behavior documented in :doc:`/streaming`.

Prerequisites
-------------

Before running the examples, make sure you have:

- Python environment with Ducta installed.
- Spark available (local mode is enough for basic examples).
- Kafka and Delta Lake connectors available for intermediate/advanced examples.
- A writable location for checkpoints.

Example package baseline:

.. code-block:: bash

    pip install pyspark>=3.2.0 loguru>=0.6.0 pyyaml>=6.0

CLI Quick Reference
-------------------

Run a streaming pipeline:

.. code-block:: bash

    ducta stream run --config config/pipelines.toml --pipeline <pipeline_name> --mode async

Check status:

.. code-block:: bash

    ducta stream status --config config/pipelines.toml --format table

Stop pipeline:

.. code-block:: bash

    ducta stream stop --config config/pipelines.toml --execution-id <execution_id>

Common Streaming Node Shape
---------------------------

Streaming nodes define their behavior in ``config/nodes.toml``:

.. code-block:: toml

    # config/nodes.toml — the key IS the node name (flat, no wrapper)
    [my_streaming_node]
    description = "Real-time transformation"

    [my_streaming_node.streaming]
    trigger = { type = "processing_time", interval = "10 seconds" }
    output_mode = "append"
    checkpoint_location = "./checkpoints/my_node"

Level 1: Basic (file_stream -> console)
----------------------------------------

Goal: validate end-to-end streaming with a local file source.

**Configuration** (``config/pipelines.toml``):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/pipelines.toml — the key IS the pipeline name (flat, no wrapper)
         [file_to_console]
         type = "streaming"
         nodes = ["local_events"]

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml
         file_to_console:
           type: streaming
           nodes:
             - local_events

   .. tab-item:: JSON

      .. code-block:: json

         {
           "file_to_console": {
             "type": "streaming",
             "nodes": ["local_events"]
           }
         }

**Node Configuration** (``config/nodes.toml``):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — the key IS the node name (flat, no wrapper)
         [local_events]
         description = "Stream from local files to console"

         [local_events.streaming]
         trigger = { type = "processing_time", interval = "5 seconds" }
         output_mode = "append"
         checkpoint_location = "./checkpoints/local_events"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         local_events:
           description: "Stream from local files to console"
           streaming:
             trigger:
               type: processing_time
               interval: "5 seconds"
             output_mode: append
             checkpoint_location: "./checkpoints/local_events"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "local_events": {
             "description": "Stream from local files to console",
             "streaming": {
               "trigger": { "type": "processing_time", "interval": "5 seconds" },
               "output_mode": "append",
               "checkpoint_location": "./checkpoints/local_events"
             }
           }
         }

**Input/Output Configuration** (``config/input.toml`` and ``output.toml``):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # input.toml
         [local_events_input]
         format = "file_stream"
         path = "./data/stream_input"

         # output.toml
         [local_events_output]
         format = "console"

   .. tab-item:: YAML

      .. code-block:: yaml

         # input.yaml
         local_events_input:
           format: file_stream
           path: "./data/stream_input"

         # output.yaml
         local_events_output:
           format: console

   .. tab-item:: JSON

      .. code-block:: json

         // config/input.json
         {
           "local_events_input": {
             "format": "file_stream",
             "path": "./data/stream_input"
           }
         }

         // config/output.json
         {
           "local_events_output": {
             "format": "console"
           }
         }

Run:

.. code-block:: bash

    mkdir -p data/stream_input checkpoints/local_events
    ducta stream run --config config/pipelines.toml --pipeline file_to_console --mode async

Inspect status:

.. code-block:: bash

    ducta stream status --config config/pipelines.toml --format table

Success criteria:

- Pipeline appears as ``running``.
- Console sink prints rows as new files arrive.
- No checkpoint conflict errors.

Level 2: Intermediate (Kafka -> Delta)
--------------------------------------

Goal: process real-time Kafka events into Delta with durable checkpointing.

**Pipeline snippet**:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/pipelines.toml — the key IS the pipeline name (flat, no wrapper)
         [kafka_to_delta]
         type = "streaming"
         nodes = ["kafka_bronze"]

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml
         kafka_to_delta:
           type: streaming
           nodes:
             - kafka_bronze

   .. tab-item:: JSON

      .. code-block:: json

         {
           "kafka_to_delta": {
             "type": "streaming",
             "nodes": ["kafka_bronze"]
           }
         }

**Node snippet**:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — the key IS the node name (flat, no wrapper)
         [kafka_bronze]
         input = { format = "kafka", options = { "kafka.bootstrap.servers" = "localhost:9092", subscribe = "events_raw" } }
         function = { key = "enrich_events", params = { source = "kafka", quality_tier = "bronze" } }
         output = { format = "delta", path = "./data/delta/bronze/events" }
         streaming = { trigger = { type = "processing_time", interval = "10 seconds" }, checkpoint_location = "./checkpoints/kafka_bronze" }

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         kafka_bronze:
           input:
             format: kafka
             options:
               kafka.bootstrap.servers: localhost:9092
               subscribe: events_raw
           function:
             key: enrich_events
             params:
               source: kafka
               quality_tier: bronze
           output:
             format: delta
             path: ./data/delta/bronze/events
           streaming:
             trigger:
               type: processing_time
               interval: "10 seconds"
             checkpoint_location: ./checkpoints/kafka_bronze

   .. tab-item:: JSON

      .. code-block:: json

         {
           "kafka_bronze": {
             "input": {
               "format": "kafka",
               "options": { "kafka.bootstrap.servers": "localhost:9092", "subscribe": "events_raw" }
             },
             "function": {
               "key": "enrich_events",
               "params": { "source": "kafka", "quality_tier": "bronze" }
             },
             "output": {
               "format": "delta",
               "path": "./data/delta/bronze/events"
             },
             "streaming": {
               "trigger": { "type": "processing_time", "interval": "10 seconds" },
               "checkpoint_location": "./checkpoints/kafka_bronze"
             }
           }
         }

Optional transformation function:

.. code-block:: python

    # Signature with params is supported
    def enrich_events(df, params):
      from pyspark.sql.functions import lit, current_timestamp
      return (
         df.withColumn("ingest_source", lit(params.get("source", "unknown")))
         .withColumn("quality_tier", lit(params.get("quality_tier", "bronze")))
         .withColumn("processed_at", current_timestamp())
      )

.. note::

    Backward-compatible transformations with ``fn(df)`` are also supported.
    If ``params`` are provided but the function only accepts ``df``, params are ignored.

Run:

.. code-block:: bash

    mkdir -p data/delta/bronze/events checkpoints/kafka_to_delta_intermediate
    ducta stream run --config config/pipelines.toml --pipeline kafka_to_delta_intermediate --mode async

Check detailed status:

.. code-block:: bash

    ducta stream status --config config/pipelines.toml --format json

Success criteria:

- Kafka node starts without validation errors.
- Delta files are produced under the configured path.
- Query remains active and reports progress.

Level 3: Advanced (DAG + depends_on + health visibility)
--------------------------------------------------------

Goal: run a dependency-aware DAG with bronze/silver/audit branches.

**Pipeline snippet**:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/pipelines.toml — the key IS the pipeline name (flat, no wrapper)
         [streaming_advanced]
         type = "streaming"
         nodes = ["bronze_ingest", "silver_enriched", "audit_console"]

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml
         streaming_advanced:
           type: streaming
           nodes:
             - bronze_ingest
             - silver_enriched
             - audit_console

   .. tab-item:: JSON

      .. code-block:: json

         {
           "streaming_advanced": {
             "type": "streaming",
             "nodes": ["bronze_ingest", "silver_enriched", "audit_console"]
           }
         }

**Node snippets**:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — the key IS the node name (flat, no wrapper)
         [bronze_ingest]
         input = { format = "kafka", options = { "kafka.bootstrap.servers" = "localhost:9092", subscribe = "events_raw" } }
         output = { format = "delta", path = "./data/delta/bronze/events" }
         streaming = { trigger = { type = "processing_time", interval = "10 seconds" }, checkpoint_location = "./checkpoints/bronze" }

         [silver_enriched]
         depends_on = ["bronze_ingest"]
         input = { format = "delta_stream", path = "./data/delta/bronze/events", options = { readChangeFeed = "true" } }
         output = { format = "delta", path = "./data/delta/silver/events" }
         streaming = { trigger = { type = "processing_time", interval = "15 seconds" }, checkpoint_location = "./checkpoints/silver" }

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         bronze_ingest:
           input:
             format: kafka
             options:
               kafka.bootstrap.servers: localhost:9092
               subscribe: events_raw
           output:
             format: delta
             path: ./data/delta/bronze/events
           streaming:
             trigger:
               type: processing_time
               interval: "10 seconds"
             checkpoint_location: ./checkpoints/bronze

         silver_enriched:
           depends_on: [bronze_ingest]
           input:
             format: delta_stream
             path: ./data/delta/bronze/events
             options:
               readChangeFeed: "true"
           output:
             format: delta
             path: ./data/delta/silver/events
           streaming:
             trigger:
               type: processing_time
               interval: "15 seconds"
             checkpoint_location: ./checkpoints/silver

   .. tab-item:: JSON

      .. code-block:: json

         {
           "bronze_ingest": {
             "input": {
               "format": "kafka",
               "options": { "kafka.bootstrap.servers": "localhost:9092", "subscribe": "events_raw" }
             },
             "output": { "format": "delta", "path": "./data/delta/bronze/events" },
             "streaming": {
               "trigger": { "type": "processing_time", "interval": "10 seconds" },
               "checkpoint_location": "./checkpoints/bronze"
             }
           },
           "silver_enriched": {
             "depends_on": ["bronze_ingest"],
             "input": {
               "format": "delta_stream",
               "path": "./data/delta/bronze/events",
               "options": { "readChangeFeed": "true" }
             },
             "output": { "format": "delta", "path": "./data/delta/silver/events" },
             "streaming": {
               "trigger": { "type": "processing_time", "interval": "15 seconds" },
               "checkpoint_location": "./checkpoints/silver"
             }
           }
         }

Run:

.. code-block:: bash

    mkdir -p data/delta/bronze/events data/delta/silver/events checkpoints/advanced
    ducta stream run --config config/pipelines.toml --pipeline streaming_advanced --mode async

Inspect runtime state:

.. code-block:: bash

    ducta stream status --config config/pipelines.toml --format json

What to expect:

- Nodes are started according to dependency order (topological order).
- If an upstream node fails, dependent nodes may be marked as skipped.
- Pipeline can move to ``partial_failure`` while independent branches continue.
- Health details are included in status output.

Operational Playbook
--------------------

1. Start in ``async`` mode for long-running pipelines.
2. Always use unique ``checkpoint_location`` per node.
3. Use ``--format json`` in status for machine-readable diagnostics.
4. Stop gracefully:

.. code-block:: bash

    ducta stream stop --config config/pipelines.toml --execution-id <execution_id> --timeout 60

Troubleshooting Checklist
-------------------------

- ``StreamingValidationError`` on Kafka input:
   Ensure exactly one of ``subscribe``, ``subscribePattern``, or ``assign`` is set.
- ``StreamingValidationError`` on dependencies:
   Verify all ``depends_on`` nodes exist and there are no cycles.
- Checkpoint conflict errors:
   Ensure every node has its own checkpoint directory.
- File stream path warning:
   Prefer ``input.options.path`` over root-level ``input.path``.

Next Steps
----------

- Add watermarking and window aggregations per node.
- Add domain-specific transformation functions and register them at startup.
- Extend the advanced DAG with quality gates and alerting sinks.
- Review :doc:`/streaming` for full API, validation, and error model details.
