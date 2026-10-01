Streaming Pipelines Tutorial
============================

Build a streaming pipeline that lands raw events (bronze) and cleans them
(silver), run it continuously, run it as a finite backfill, then point it at
Kafka and Delta. The reference for every key is :doc:`/streaming`.

Prerequisites: ``pip install "ducta[spark]"`` and Java 17+. Kafka and Delta are
only needed for step 5.

Step 1: Generate the project
----------------------------

.. code-block:: bash

   ducta template --template streaming_basic --project-name events
   cd events

.. code-block:: text

   events/
   ├── ducta.yaml
   ├── catalog.yaml                  # empty: stream nodes declare their own I/O
   ├── pipelines/
   │   ├── events_stream.yaml        # two stream nodes: bronze, then silver
   │   └── transforms.py             # the transform silver applies
   └── data/events/                  # five seed events, two without an amount

Step 2: Read the pipeline
-------------------------

.. code-block:: yaml

   # pipelines/events_stream.yaml
   description: Ingest a file stream, clean it, and land it as Parquet
   type: streaming
   requires_dates: false
   nodes:
     ingest_events:
       description: "Bronze: land the raw event stream exactly as it arrives"
       kind: stream
       stream:
         input:
           format: file_stream
           file_format: json
           options: {path: "${paths.input}/events", maxFilesPerTrigger: 1}
           schema: event_id STRING, category STRING, amount DOUBLE, ts TIMESTAMP
         output:
           format: parquet
           path: ${paths.output}/${env}/bronze/events
         streaming:
           checkpoint_location: ${paths.output}/${env}/_ckpt/ingest_events
           output_mode: append
           trigger: {type: processing_time, interval: 5 seconds}

     clean_events:
       description: "Silver: drop incomplete events and stamp an ingest time"
       kind: stream
       after: [ingest_events]
       stream:
         input:
           format: file_stream
           file_format: parquet
           options: {path: "${paths.output}/${env}/bronze/events"}
           schema: event_id STRING, category STRING, amount DOUBLE, ts TIMESTAMP
         transform:
           key: clean_events
           module: pipelines.transforms
           params: {min_amount: 0.0}
         output:
           format: parquet
           path: ${paths.output}/${env}/silver/events
         streaming:
           checkpoint_location: ${paths.output}/${env}/_ckpt/clean_events
           output_mode: append
           trigger: {type: processing_time, interval: 5 seconds}

- Each node reads a stream, optionally transforms it, and writes a stream.
- ``after`` orders the nodes: stream inputs and outputs are paths, not catalog
  datasets, so Ducta cannot infer the order from the data.
- Every node has its own checkpoint, under the environment's directory — the
  checkpoint is what lets a restarted query continue where it stopped.

The transform is a function registered under a key:

.. code-block:: python

   # pipelines/transforms.py
   from pyspark.sql import functions as F


   def clean_events(df, params=None):
       min_amount = float((params or {}).get("min_amount", 0.0))
       return (
           df.filter(F.col("amount").isNotNull())
           .filter(F.col("amount") >= F.lit(min_amount))
           .withColumn("ingested_at", F.current_timestamp())
       )


   def register_transforms(registry):
       registry.register("clean_events", clean_events)

Step 3: Run it continuously
---------------------------

.. code-block:: bash

   ducta config validate --env dev
   ducta stream run --pipeline events_stream --env dev

The command starts both queries and returns. They keep running: copy another
``.json`` event into ``data/events/`` and it appears in
``data/dev/bronze/events`` and, if it has an amount, in
``data/dev/silver/events``.

.. code-block:: bash

   ducta stream status --env dev                         # queries, rates, health
   ducta stream stop --env dev --execution-id <id>

Step 4: Run it as a finite job
------------------------------

For a backfill, a test or CI, you want a run that processes what exists and
ends. Give the nodes a terminating trigger in one environment only:

.. code-block:: yaml

   # ducta.yaml
   version: 2
   project: events
   paths: {input: data, output: data}
   environments:
     sandbox:
       pipelines.events_stream.nodes.ingest_events.stream.streaming.trigger: {type: available_now}
       pipelines.events_stream.nodes.clean_events.stream.streaming.trigger: {type: available_now}

.. code-block:: bash

   ducta stream run --pipeline events_stream --env sandbox --mode sync

``--mode sync`` waits for the queries, and a node waits for the node it reads
from to finish before it starts. The command returns when both are done:
``data/sandbox/bronze/events`` holds the five seed events, and
``data/sandbox/silver/events`` the three that have an amount.

Step 5: Kafka in, Delta out
---------------------------

Production streams usually come from Kafka and land in Delta. Only the node's
``input``, ``output`` and transform change:

.. code-block:: yaml

   # pipelines/orders_stream.yaml
   type: streaming
   requires_dates: false
   nodes:
     orders_to_bronze:
       kind: stream
       stream:
         input:
           format: kafka
           options:
             kafka.bootstrap.servers: broker:9092
             subscribe: orders
             startingOffsets: latest
         transform: {key: parse_orders, module: pipelines.transforms}
         output:
           format: delta
           path: ${paths.output}/${env}/bronze/orders
         streaming:
           checkpoint_location: ${paths.output}/${env}/_ckpt/orders_to_bronze
           trigger: {type: processing_time, interval: 30 seconds}
           watermark: {column: event_time, delay: 10 minutes}

Kafka delivers ``key`` and ``value`` as bytes, so the transform parses them:

.. code-block:: python

   # pipelines/transforms.py (added)
   from pyspark.sql import functions as F

   ORDER = "order_id STRING, amount DOUBLE, event_time TIMESTAMP"


   def parse_orders(df, params=None):
       return (
           df.select(F.from_json(F.col("value").cast("string"), ORDER).alias("o"))
           .select("o.*")
       )


   def register_transforms(registry):
       registry.register("clean_events", clean_events)
       registry.register("parse_orders", parse_orders)

Operating streams
-----------------

- **Restarting** a pipeline resumes each query from its checkpoint. Deleting a
  node's checkpoint replays its source from the beginning.
- **Changing a query's logic** (a new transform, a new output) usually needs a
  new checkpoint location; Spark refuses incompatible changes to a checkpoint.
- **Two queries never share a checkpoint**: Ducta rejects the second one
  instead of letting both corrupt it.
- ``stream status`` reports input and processing rates per query; a query that
  stops making progress shows up there first.

Next steps
----------

- :doc:`/streaming` — every key of a stream node, and the Python API
- :doc:`/quality` — checks on what your pipelines write
