Streaming Engine
================

Ducta runs Spark Structured Streaming pipelines from the same project files as
batch ones: a pipeline with ``type: streaming`` whose nodes are
``kind: stream``. You declare the source, the sink, the trigger and the
checkpoint; your Python is a transform function.

- **Sources**: Kafka, Kinesis (Spark ships no Kinesis source: add a connector),
  Delta tables (appended data, or their change data feed) and file streams on
  local or cloud storage; ``rate`` and ``socket`` for trying a pipeline without
  an external system.
- **Sinks**: Delta, Parquet, JSON, CSV, Kafka, ``console`` and ``memory`` (the
  last two for debugging).
- **Checkpoints** per node, reserved atomically so two queries can never share
  one.
- **Terminating triggers** turn a streaming pipeline into a self-contained
  batch job for backfills and CI.

A stream node
-------------

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/events.toml
         type = "streaming"
         requires_dates = false

         [nodes.clean_events]
         kind = "stream"

         [nodes.clean_events.stream.input]
         format = "kafka"

         [nodes.clean_events.stream.input.options]
         "kafka.bootstrap.servers" = "broker:9092"
         subscribe = "events"

         [nodes.clean_events.stream.transform]
         key = "clean_events"
         module = "pipelines.transforms"

         [nodes.clean_events.stream.transform.params]
         min_amount = 0.0

         [nodes.clean_events.stream.output]
         format = "delta"
         path = "${paths.output}/${env}/silver/events"

         [nodes.clean_events.stream.streaming]
         checkpoint_location = "${paths.output}/${env}/_ckpt/clean_events"
         output_mode = "append"

         [nodes.clean_events.stream.streaming.trigger]
         type = "processing_time"
         interval = "10 seconds"

         [nodes.clean_events.stream.streaming.watermark]
         column = "event_time"
         delay = "10 minutes"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/events.yaml
         type: streaming
         requires_dates: false
         nodes:
           clean_events:
             kind: stream
             stream:
               input:
                 format: kafka
                 options:
                   kafka.bootstrap.servers: broker:9092
                   subscribe: events
               transform:
                 key: clean_events                 # a registered transform
                 module: pipelines.transforms      # imported so it can register itself
                 params: {min_amount: 0.0}
               output:
                 format: delta
                 path: ${paths.output}/${env}/silver/events
               streaming:
                 checkpoint_location: ${paths.output}/${env}/_ckpt/clean_events
                 output_mode: append               # append | update | complete
                 trigger: {type: processing_time, interval: 10 seconds}
                 watermark: {column: event_time, delay: 10 minutes}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "type": "streaming",
           "requires_dates": false,
           "nodes": {
             "clean_events": {
               "kind": "stream",
               "stream": {
                 "input": {
                   "format": "kafka",
                   "options": {
                     "kafka.bootstrap.servers": "broker:9092",
                     "subscribe": "events"
                   }
                 },
                 "transform": {
                   "key": "clean_events",
                   "module": "pipelines.transforms",
                   "params": {
                     "min_amount": 0.0
                   }
                 },
                 "output": {
                   "format": "delta",
                   "path": "${paths.output}/${env}/silver/events"
                 },
                 "streaming": {
                   "checkpoint_location": "${paths.output}/${env}/_ckpt/clean_events",
                   "output_mode": "append",
                   "trigger": {
                     "type": "processing_time",
                     "interval": "10 seconds"
                   },
                   "watermark": {
                     "column": "event_time",
                     "delay": "10 minutes"
                   }
                 }
               }
             }
           }
         }

.. list-table::
   :widths: 26 74
   :header-rows: 1

   * - Key (under ``stream``)
     - Meaning
   * - ``input``
     - The source: ``format`` (``kafka``, ``kinesis``, ``delta_stream``,
       ``file_stream`` with ``file_format``, ``rate``, ``socket``), ``options``
       passed to Spark, and for file streams a ``schema``. A ``delta_stream``
       streams the table's appended data; set ``options: {readChangeFeed: true}`` to
       stream its change data feed instead (``auto_enable_cdf``, on by default,
       then turns the feed on for a table without it — Ducta never alters a table
       it only reads).
   * - ``transform``
     - The registered transform to apply: ``key``, optional ``module`` to
       import first and ``params`` passed to it. Omit it to copy the stream
       as-is (or, with ``model``, to score it).
   * - ``model``
     - A registered model to score each micro-batch with — the same block as a
       serving node's (see :doc:`mlops`). Applied by the built-in scorer, or
       handed to a transform that takes an ``ml_context`` parameter. Resolved when
       the query starts; a restart resolves it again.
   * - ``output``
     - The sink: ``format`` (``delta``, ``parquet``, ``json``, ``csv``, ``kafka``,
       ``console``, ``memory``), ``path`` and ``options``.
   * - ``streaming``
     - ``checkpoint_location``, ``output_mode``, ``trigger`` and
       ``watermark``. Omitted keys default to a ``processing_time`` trigger
       every 10 seconds and ``append``.

Triggers: ``processing_time`` (with ``interval``), ``once``,
``available_now``, ``continuous`` and ``adaptive``. A running query's interval is
fixed by Spark, so ``adaptive`` picks the interval *at start*: about 1.5 times the
average batch duration that earlier runs of the same node measured **in the same
process** (clamped between 1 second and ``streaming_adaptive_max_interval_seconds``,
60 by default), or ``streaming_adaptive_base_interval`` (5 seconds) when there is
no history yet.

``checkpoint_location`` is a **base directory**: the checkpoint of a node is
``<checkpoint_location>/<pipeline>/<node>``. Pointing it at the directory of an
existing Spark checkpoint therefore starts from scratch; point it at the parent
the old checkpoint lives under, or move the old one into that layout.

Node-level keys (``description``, ``after``, ``metadata``…) work as on any
node — except ``quality``: the streaming engine runs no checks, and preflight
warns about a ``quality`` block on a stream node. Check a stream's output with a
batch node (or pipeline) that reads it. Stream nodes that depend on each other run in order: order them
with ``after`` when one reads the other's output path.

.. important::
   **Keep data and checkpoints apart per environment.** Build ``path`` and
   ``checkpoint_location`` from ``${paths.output}`` and ``${env}`` as above.
   Two environments sharing a checkpoint share streaming state: a sandbox run
   would corrupt dev's progress.

Transforms
----------

A transform takes the streaming DataFrame and the node's ``params`` and returns
a DataFrame. It is looked up by name in a registry, so only functions you
register can run:

.. code-block:: python

   # pipelines/transforms.py
   from pyspark.sql import DataFrame, functions as F


   def clean_events(df: DataFrame, params: dict) -> DataFrame:
       return df.filter(F.col("amount") >= params.get("min_amount", 0)).withColumn(
           "ingested_at", F.current_timestamp()
       )


   def register_transforms(registry) -> None:
       registry.register("clean_events", clean_events)

Ducta calls ``register_transforms(registry)`` of every module named in the
transform's ``module``, in ``settings.streaming_transform_modules``, or passed
with ``ducta stream run --transforms-module``.

Merge, quarantine and quality
-----------------------------

A stream node can treat each micro-batch like a small batch run. Any of
``output.mode: merge``, ``quarantine`` or ``quality`` makes Ducta write the
node through ``foreachBatch``; a node with none of them keeps Spark's own sink.

.. code-block:: yaml

   orders_silver:
     kind: stream
     stream:
       input: {format: kafka, options: {kafka.bootstrap.servers: localhost:9092, subscribe: orders}}
       output:
         format: delta
         path: ${paths.output}/${env}/silver/orders
         mode: merge                         # append (default) | merge
         merge: {keys: [order_id], dedupe_order_by: updated_at}
       quarantine:
         reject_when: "order_id IS NULL OR amount < 0"
       streaming:
         checkpoint_location: ${paths.output}/${env}/_ckpt/orders_silver
         trigger: 30 seconds
     quality:
       checks: {row_count: {min: 1}}
       gate: {max_errors: 0}

Each batch goes through these steps, in order:

1. **Rows matching** ``quarantine.reject_when`` (a SQL predicate over one row)
   are set aside with ``_ducta_reason``, ``_ducta_batch_id``, ``_ducta_run_id``
   and ``_ducta_quarantined_at``.
2. **The node's quality checks** run on the remaining rows. When the gate
   blocks, the **whole batch** goes to quarantine instead of the sink, and the
   stream carries on. That holds for any blocking ``gate.on_fail``
   (``skip_downstream``, ``stop_all``); with ``warn_only`` the batch is written
   and the failure logged. Input contracts (``sanity_checks``) do not run on
   stream nodes.
3. **What passed** is appended or merged into the sink.

``merge`` takes the catalog's merge block (``keys``, ``when_matched``,
``when_not_matched``, ``delete_when``, ``schema_evolution``) and needs a Delta sink.
``dedupe_order_by`` keeps one row per key, the latest by that column; without it,
a batch that repeats a key fails the query.

Quarantined rows go to ``quarantine.path``, by default
``<output_path>/<environment>/quarantine/<pipeline>/<node>``, in the sink's format.
The micro-batch path writes ``delta``, ``parquet``, ``json`` and ``csv`` sinks.

**Writes are idempotent per batch.** Spark runs a batch again, with the same id,
when the query failed before committing it. A Delta append tagged with the query's
id and the batch id is skipped the second time, and a merge is an upsert. A
parquet, JSON or CSV batch is written to ``<sink>/_ducta_staging/`` and moved into
the sink under a name carrying the query and the batch; a marker in
``<sink>/_ducta_batches/`` records it, so a batch already published is skipped and
one interrupted half-way is redone whole — the guarantee Spark's own file sink gives,
kept when quality or quarantine is added. Spark's readers skip both ``_`` folders.
(On Spark Connect there is no JVM to move files with: a warning says a re-run batch
may be written twice.)

A passing batch's quality report is kept one time in
``settings.streaming_quality_report_every`` (default 100); every failing batch's
report is kept. The baseline is saved from the first batch that passes, and a local
JSON history gets every batch (a parquet/Delta history keeps the reports' pace: each
append is a Spark job). Checks that cannot run at all — a misspelled ``severity``, a
broken gate, an unknown profile — stop the query instead of letting the batch through
unchecked.

Running
-------

.. code-block:: bash

   ducta stream plan --pipeline events --env dev    # what it would do; starts nothing
   ducta stream run --pipeline events --env dev     # runs until the queries end, or Ctrl+C

The queries run inside the command's process, so the command keeps running while
they do: Ctrl+C stops them gracefully, and with a terminating trigger (below) it
ends on its own. ``--mode sync`` waits inside the engine instead of reporting
status. ``ducta start --pipeline events`` behaves the same way, and a ``hybrid``
pipeline mixes batch and stream nodes.

A streaming run waits as long as its queries run: ``execution_timeout_seconds``
bounds batch work, not a stream. The pipeline's ``status`` is ``running`` while
every node is up, ``partial_failure`` when a node failed to start, was skipped
behind a failed one, or reported no progress for longer than three trigger
intervals (at least 5 minutes), ``failed`` when no node started, and ``completed``
only when every node started and every query ended cleanly. The command exits
non-zero when a node did not start or a query failed.

In the web app a streaming pipeline has **Start stream** / **Stop stream** instead of
Run / Stop. While it runs, the top bar says how many queries are up and how many rows
per second they process, each stream node on the canvas shows its query (a dot and its
throughput; ``idle`` for a quiet source, ``stalled`` for a query that reports nothing,
``failed`` with its error), and the logs panel shows one row per node: how it is, said
in words, and its rate and trend. Click a row for what it reads and writes, its trigger
and its checkpoint. A failed or hung node has a **Restart** button on its row (for a
healthy one it is inside the detail) that restarts that query from its checkpoint
(``POST /api/executions/{id}/streaming/{stream_execution_id}/nodes/{node}/restart``,
needs ``execution.write``).

To keep a stream running without a terminal, start it from the server (``ducta
ui``, or ``POST .../pipelines/{name}/execute``): ``GET
/api/executions/{id}/streaming`` shows its queries and ``POST
/api/executions/{id}/cancel`` stops it. ``ducta stream status`` and ``ducta
stream stop`` only see streams of their own process — a stream started by
another command or by the server is not visible to them.

Terminating runs (backfills and CI)
-----------------------------------

With a terminating trigger (``once`` or ``available_now``) the queries process
whatever is available and stop, and the command returns when they finish — a
streaming pipeline behaves like a batch job, which
suits backfills, local runs and CI. Switch the trigger for one environment only:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "events"

         [paths]
         input = "data"
         output = "data"

         [environments.sandbox."pipelines.events.nodes.clean_events.stream.streaming.trigger"]
         type = "available_now"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: events
         paths: {input: data, output: data}
         environments:
           sandbox:
             pipelines.events.nodes.clean_events.stream.streaming.trigger:
               type: available_now

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "events",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "environments": {
             "sandbox": {
               "pipelines.events.nodes.clean_events.stream.streaming.trigger": {
                 "type": "available_now"
               }
             }
           }
         }

The ``streaming_basic`` template (``ducta template --template streaming_basic``)
reads a file stream, applies a registered transform and writes Parquet, with
per-node checkpoints; it runs out of the box on local files.

Fault tolerance
---------------

- **Checkpoint reservation**: a query whose checkpoint another query already
  uses is rejected, instead of both corrupting it.
- **Exactly-once** end to end with idempotent sinks such as Delta Lake.
- **Retries** of transient Delta start-up errors (e.g. schema not yet
  initialised).
- **A node that ends can start again**: a query that failed or finished frees its
  checkpoint, so ``restart_node`` (and the next run) can start it again.
- **A failed terminating upstream stops its dependants**: nodes ordered ``after`` a
  ``once``/``available_now`` node that died are skipped, not started on its
  partial output.
- **Stopping during start-up leaves nothing running**: a query that finishes
  starting after its pipeline was stopped is stopped, not left running unseen.
- **A journal outlives the process**: every run writes
  ``<output_path>/<environment>/.ducta/streams/<pipeline>/<run_id>/``. That holds
  ``run.json`` (status, and each node's outcome at the end) and ``batches.jsonl``
  (one line per batch with data; rotated at 20 MB, the totals of dropped lines kept
  in ``carried.json`` so a long run's certificate counts every batch). The newest 50
  finished runs per pipeline are kept. A run whose process died reads as
  ``interrupted``. The ``adaptive`` trigger starts from the batch durations the
  previous run journaled.
- **Every run is certified**: an asynchronous run gets its run id when it starts
  and its Run Certificate when it ends. A stream node's entry carries its batches
  and its rows read, written and quarantined.
- **Live alerts**: ``alerts:`` rules can name ``stream_failed``,
  ``stream_stalled`` and ``stream_quarantine``. They are sent while the stream
  runs: a failure or stall once until it recovers, and quarantine at once, then at
  most every ``streaming_quarantine_alert_interval_seconds``. Health is checked
  every ``streaming_health_interval_seconds``, not only when someone asks for it.

From Python
-----------

``StreamingPipelineManager`` is the engine behind the CLI, for embedding in
your own service:

.. code-block:: python

   from ducta.console.execution import load_context
   from ducta.stream import StreamingPipelineManager

   context = load_context("path/to/project", env="dev")
   manager = StreamingPipelineManager(context)
   manager.query_manager.transformation_registry.register("clean_events", clean_events)

   exec_id = manager.start_pipeline("events", context.pipelines_config["events"])
   status = manager.get_pipeline_status(exec_id)
   metrics = manager.get_pipeline_metrics(exec_id)  # rates and a health_score

``max_concurrent_pipelines`` (constructor argument) caps how many streaming
pipelines one manager runs at once. Status snapshots do not include the
pipeline definition (it holds connector credentials);
``manager.running_pipeline_configs()`` returns the definitions of the live ones.

``manager.clear_pipeline_checkpoints("events")`` deletes the checkpoints of a pipeline
that is not running — the project default and every node's own
``checkpoint_location`` — and lists those on cloud storage under ``manual`` for
you to delete.

Next steps
----------

- :doc:`tutorials/streaming` — build a streaming pipeline step by step
- :doc:`quality` — checks and gates, on the batch nodes that read a stream's output
