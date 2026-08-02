Streaming Engine
================

Ducta's Streaming Module provides a high-level abstraction for building real-time data pipelines. Powered by Apache Spark Structured Streaming, it allows you to process infinite data streams with the same simplicity as batch pipelines.

Core Principles
---------------

*   **Declarative Streaming**: Define sources and sinks in TOML/YAML, logic in Python.
*   **Checkpoint Management**: Automatic state tracking for fault-tolerant executions.
*   **Native Connectors**: Built-in support for Kafka, Cloud Folders, and Delta Tables.
*   **Operational Visibility**: Integrated health checks and query monitoring.

Configuration
-------------

Trigger, output mode, watermark, and checkpoint location are configured **per streaming node**, under the node's ``streaming`` key (not in a global ``[streaming]`` table). Concurrency across pipelines is controlled by the ``max_concurrent_pipelines`` argument passed to ``StreamingPipelineManager`` in Python.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — top-level key IS the node name (flat, no wrapper)
         [my_stream_node.streaming]
         output_mode = "append"
         checkpoint_location = "/checkpoints/my_stream_node"

         [my_stream_node.streaming.trigger]
         type = "processing_time"            # processing_time, once, continuous, available_now
         interval = "10 seconds"

         [my_stream_node.streaming.watermark]
         column = "event_time"
         delay = "10 seconds"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         my_stream_node:
           streaming:
             output_mode: append
             checkpoint_location: /checkpoints/my_stream_node
             trigger:
               type: processing_time
               interval: "10 seconds"
             watermark:
               column: event_time
               delay: "10 seconds"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "my_stream_node": {
             "streaming": {
               "output_mode": "append",
               "checkpoint_location": "/checkpoints/my_stream_node",
               "trigger": {
                 "type": "processing_time",
                 "interval": "10 seconds"
               },
               "watermark": {
                 "column": "event_time",
                 "delay": "10 seconds"
               }
             }
           }
         }

Any key omitted in the node config falls back to Ducta's defaults (``processing_time`` trigger with a 10 second interval, ``append`` output mode). Concurrency limit and per-query health-check stall timeout are not read from configuration files; set ``max_concurrent_pipelines`` when constructing ``StreamingPipelineManager`` and pass ``timeout_seconds`` where health monitoring is configured in your own orchestration code.

.. important::
   **Isolate data and checkpoints per environment.** A streaming node's ``path``
   (its inline ``input``/``output`` location) and ``checkpoint_location`` support
   ``${input_path}``, ``${output_path}``, and ``${environment}`` interpolation,
   same as the input/output catalog's ``filepath``::

      [my_stream_node.output]
      path = "${output_path}/${environment}/bronze/my_stream_node"

      [my_stream_node.streaming]
      checkpoint_location = "${output_path}/${environment}/checkpoints/my_stream_node"

   Without this, every ``--env`` (``dev``, ``sandbox``, ``prod``, ...) reads and
   writes the **same** physical path and shares the **same** checkpoint —
   a sandbox validation run would corrupt a dev run's streaming state. See
   :ref:`project-layouts` and *Environments & Overrides* in
   :doc:`configuration` for the full per-environment model.

Terminating runs (backfills and testing)
-----------------------------------------

With a terminating trigger (``once`` or ``available_now``) the queries process
whatever data is currently available and then stop on their own. Combined with
``--mode sync`` the CLI blocks until they finish and then exits, which makes a
streaming pipeline behave like a self-contained batch job — ideal for backfills,
local runs, and CI:

.. code-block:: bash

   ducta stream run --config config/global_settings.yaml -p ingest_stream --mode sync

The ``streaming_core`` starter template (``ducta template --template streaming_core``)
is exactly this: a file-stream source with an ``available_now`` trigger that runs
to completion out of the box, with a commented pointer for switching to Kafka.

Managing Pipelines Programmatically
-----------------------------------

The ``StreamingPipelineManager`` is the primary orchestrator for real-time workflows.

.. code-block:: python

   from ducta.stream import StreamingPipelineManager

   # 1. Initialize manager
   manager = StreamingPipelineManager(context)

   # 2. Register your business logic
   def my_transform(df, params):
       return df.withColumn("processed", lit(True))

   manager.query_manager.transformation_registry.register("enrich", my_transform)

   # 3. Start a pipeline defined in config
   exec_id = manager.start_pipeline("realtime_ingestion", pipeline_cfg)

   # 4. Monitor health
   status = manager.get_pipeline_status(exec_id)
   print(f"Health Score: {status['health_score']}")

Native Connectors
-----------------

Ducta supports high-performance streaming for:

- **Kafka**: Full support for SSL/SASL and offset management.
- **Delta Lake (CDF)**: Stream changes from Delta tables using Change Data Feed.
- **Kinesis**: AWS-native streaming integration.
- **File Streams**: Monitor cloud directories (S3/ADLS) for new files.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/input.toml — top-level key IS the dataset name (flat, no wrapper)
         [kafka_source]
         format = "kafka"
         streaming = true
         options = { "kafka.bootstrap.servers" = "localhost:9092", "subscribe" = "events" }

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/input.yaml
         kafka_source:
           format: kafka
           streaming: true
           options:
             kafka.bootstrap.servers: "localhost:9092"
             subscribe: events

   .. tab-item:: JSON

      .. code-block:: json

         {
           "kafka_source": {
             "format": "kafka",
             "streaming": true,
             "options": {
               "kafka.bootstrap.servers": "localhost:9092",
               "subscribe": "events"
             }
           }
         }

Transformation Registry
-----------------------

To ensure security and thread-safety, Ducta uses an isolated ``TransformationRegistry``. You must register your Python functions before they can be referenced in the configuration.

.. code-block:: python

   # Reference in config/nodes.toml (flat — the key IS the node name):
   # [my_stream_node]
   # function = { key = "my_registered_func", params = { "mode" = "strict" } }

   manager.query_manager.transformation_registry.register("my_registered_func", my_func)

Fault Tolerance
---------------

Ducta implements **Atomic Checkpoint Reservation**. If two queries attempt to share the same checkpoint location, the second one is rejected to prevent state corruption.

- **Exactly-once**: Guaranteed when using idempotent sinks like Delta Lake.
- **Automatic Retries**: Resilience against transient Delta Lake startup errors (e.g., waiting for schema initialization).

Next Steps
----------

- :doc:`tutorials/streaming` - Build your first real-time pipeline.
- :doc:`quality` - Add data quality gates to your streaming outputs.
