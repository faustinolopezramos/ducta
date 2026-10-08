Streaming Engine
================

Ducta runs Spark Structured Streaming pipelines from the same project files as
batch ones: a pipeline with ``type: streaming`` whose nodes are
``kind: stream``. You declare the source, the sink, the trigger and the
checkpoint; your Python is a transform function.

- **Sources**: Kafka, Kinesis, Delta (change data feed) and file streams on
  local or cloud storage.
- **Checkpoints** per node, reserved atomically so two queries can never share
  one.
- **Terminating triggers** turn a streaming pipeline into a self-contained
  batch job for backfills and CI.

A stream node
-------------

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

.. list-table::
   :widths: 26 74
   :header-rows: 1

   * - Key (under ``stream``)
     - Meaning
   * - ``input``
     - The source: ``format`` (``kafka``, ``kinesis``, ``delta_stream``,
       ``file_stream`` with ``file_format``), ``options`` passed to Spark, and
       for file streams a ``schema``.
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
     - The sink: ``format``, ``path`` and ``options``.
   * - ``streaming``
     - ``checkpoint_location``, ``output_mode``, ``trigger`` and
       ``watermark``. Omitted keys default to a ``processing_time`` trigger
       every 10 seconds and ``append``.

Triggers: ``processing_time`` (with ``interval``), ``once``,
``available_now`` and ``continuous``.

Node-level keys (``description``, ``after``, ``quality``, ``metadata``…) work
as on any node. Stream nodes that depend on each other run in order: order them
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

Running
-------

.. code-block:: bash

   ducta stream run --pipeline events --env dev              # start and return (async)
   ducta stream run --pipeline events --env dev --mode sync  # wait for the queries
   ducta stream status
   ducta stream stop --execution-id <ID>

``ducta start --pipeline events`` runs a streaming pipeline too, and a
``hybrid`` pipeline mixes batch and stream nodes.

Terminating runs (backfills and CI)
-----------------------------------

With a terminating trigger (``once`` or ``available_now``) the queries process
whatever is available and stop. Combined with ``--mode sync`` the command
returns when they finish — a streaming pipeline behaves like a batch job, which
suits backfills, local runs and CI. Switch the trigger for one environment only:

.. code-block:: yaml

   # ducta.yaml
   version: 2
   project: events
   paths: {input: data, output: data}
   environments:
     sandbox:
       pipelines.events.nodes.clean_events.stream.streaming.trigger:
         type: available_now

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
pipelines one manager runs at once.

Next steps
----------

- :doc:`tutorials/streaming` — build a streaming pipeline step by step
- :doc:`quality` — checks and gates on stream outputs
