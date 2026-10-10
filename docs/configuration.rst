Configuration Guide
===================

A Ducta project is three kinds of YAML file. You describe your datasets once,
your pipelines as the nodes that read and write them, and what differs between
environments — Ducta validates all of it before anything runs and reports every
mistake with its file and line.

.. code-block:: text

   my_project/
   ├── ducta.yaml            # project, paths, settings, per-environment overrides
   ├── catalog.yaml          # every dataset, once — read, written, or both
   ├── pipelines/
   │   ├── etl.yaml          # one pipeline per file: its nodes
   │   └── etl.py            # your transformations
   └── .ducta/schema/        # JSON Schemas for editor autocompletion

.. list-table::
   :widths: 24 76
   :header-rows: 1

   * - File
     - What it defines
   * - ``ducta.yaml``
     - ``version: 2``, the project name, ``paths`` (input/output base), engine
       ``settings``, and ``environments`` overrides.
   * - ``catalog.yaml``
     - Every dataset: format, location, how it is written, and the checks it
       must pass whenever a node reads it (its *contract*).
   * - ``pipelines/<name>.yaml``
     - One pipeline — the file name is the pipeline name — and its nodes.

``ducta init project --name my_project`` (or ``ducta template``) generates a
complete project; the sections below explain each file. A large project splits
its catalog by layer (``catalog/bronze.yaml``, ``catalog/silver.yaml``, …) and
keeps its quality profiles in ``quality/profiles.yaml`` — see
:ref:`catalog-folder` and :ref:`profiles-file`. Commands find the project the way git finds a repository: from the
current directory (or ``--base-path``) upwards, the first directory holding a
``ducta.yaml`` with ``version: 2``, at its root or under ``config/``.

Strict by design
----------------

Unknown keys are **errors**, never ignored. A typo does not silently change
behaviour; it stops the run with the file, the line and a suggestion:

.. code-block:: text

   Invalid project configuration (1 problem(s)):
     - pipelines/etl.yaml:10 pipelines/etl.nodes.daily.timout: unknown key 'timout' — did you mean 'timeout_seconds'?

Once every file parses, Ducta checks the references between them: every
dataset a node reads or writes is in the catalog, ``after:`` and ``depends_on``
name real nodes and pipelines, node names are unique, and each dataset resolves
to a location.

.. code-block:: text

   Invalid project configuration (2 problem(s)):
     - pipelines/etl.yaml:2 node 'clean' reads 'orders_rw', which is not in catalog.yaml (did you mean 'orders_raw'?)
     - pipelines/etl.yaml:6 node 'daily': after 'cleen' is not a node of pipeline 'etl' (did you mean 'clean'?)

Each stage reports every problem it finds, not just the first.
Free-form data you want to keep with the project goes under ``metadata:``
(allowed in ``ducta.yaml`` and on pipelines and nodes); Ducta never reads it.

ducta.yaml
----------

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "sales"
         description = "Orders to daily revenue"

         [paths]
         input = "data"
         output = "data"

         [settings]
         max_parallel_nodes = 4
         evidence_level = "record"

         [settings.run_lock]
         backend = "local"

         [environments.prod]
         "pipelines.etl.nodes.clean.quality.gate.max_errors" = 0

         [environments.prod.settings]
         max_parallel_nodes = 16
         evidence_level = "signed"

         [environments.prod.paths]
         output = "s3://lake/prod"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: sales
         description: Orders to daily revenue
         paths: {input: data, output: data}
         settings:
           max_parallel_nodes: 4
           evidence_level: record
           run_lock: {backend: local}
         environments:
           prod:
             settings: {max_parallel_nodes: 16, evidence_level: signed}
             paths: {output: s3://lake/prod}
             pipelines.etl.nodes.clean.quality.gate.max_errors: 0

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "sales",
           "description": "Orders to daily revenue",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "max_parallel_nodes": 4,
             "evidence_level": "record",
             "run_lock": {
               "backend": "local"
             }
           },
           "environments": {
             "prod": {
               "settings": {
                 "max_parallel_nodes": 16,
                 "evidence_level": "signed"
               },
               "paths": {
                 "output": "s3://lake/prod"
               },
               "pipelines.etl.nodes.clean.quality.gate.max_errors": 0
             }
           }
         }

.. list-table::
   :widths: 22 78
   :header-rows: 1

   * - Key
     - Meaning
   * - ``version``
     - Always ``2``. Required.
   * - ``project``
     - The project's name (certificates and MLOps runs carry it). Required.
   * - ``paths``
     - ``input`` and ``output``: the base directories or URIs your datasets
       live under. Required. Referenced from the catalog as ``${paths.input}``
       and ``${paths.output}``.
   * - ``settings``
     - Engine settings — see below.
   * - ``environments``
     - What changes per environment — see :ref:`environments`.
   * - ``description``, ``metadata``
     - Documentation for people; not read by Ducta.

Settings
~~~~~~~~

``settings`` accepts every engine setting except ``input_path``/``output_path``
(those are ``paths``). ``ducta config schema`` prints the complete, current
list; the ones most projects touch:

.. list-table::
   :widths: 32 68
   :header-rows: 1

   * - Setting
     - Effect (default)
   * - ``mode``
     - ``local`` (default), ``databricks`` or ``distributed``.
   * - ``max_parallel_nodes``
     - Independent nodes run in parallel, up to this many (4).
   * - ``node_timeout_seconds`` / ``execution_timeout_seconds``
     - Time limit per node (1800) and per run (3600). A node over its limit is
       cancelled — its Spark jobs are interrupted and it can no longer write.
   * - ``evidence_level``
     - ``off``, ``record`` (default: a Run Certificate per run), ``required``
       (a run without its certificate fails) or ``signed`` (HMAC-signed; needs
       ``DUCTA_CERTIFICATE_KEY``). See :doc:`tutorials/certificates`.
   * - ``run_lock``
     - Exclusive lock on each output dataset while a run writes it:
       ``{enabled: true, backend: local|storage, on_conflict: fail|wait}``.
       Use ``storage`` when runs start on different hosts.
   * - ``fingerprint_mode``
     - How much of each dataset its fingerprint covers: ``auto`` (default —
       the Delta version, the run's window, or the whole dataset when it is
       small), ``exact``, ``sample`` or ``schema``.
   * - ``in_memory_handoff``
     - Pass a node's output to its dependants in memory instead of re-reading
       it (false).
   * - ``quality``
     - Reusable check profiles and custom check modules — see
       :ref:`quality-config`.
   * - ``spark_config``
     - Spark session settings, e.g. ``{spark.sql.shuffle.partitions: 8}``.
   * - ``log_level``
     - ``DEBUG``, ``INFO`` (default), ``WARNING``, ``ERROR``.
   * - ``mlops_enabled`` / ``mlflow``
     - Experiment tracking and the model registry — see :doc:`mlops`.

catalog.yaml
------------

Every dataset the project reads or writes, declared **once**. A node refers to
a dataset by its name; the catalog says where it is and how to handle it.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         [orders_raw]
         description = "Orders as exported by the shop"
         format = "csv"
         path = "${paths.input}/orders.csv"

         [orders_raw.options]
         header = true

         [orders_raw.incremental]
         column = "order_date"

         [orders_raw.quality]
         empty_dataset = true

         [orders_raw.quality.schema]
         expected_columns = [
             "order_id",
             "amount",
             "order_date",
         ]

         ["silver.sales.orders"]
         format = "delta"

         ["silver.sales.orders".write]
         mode = "merge"

         ["silver.sales.orders".write.merge]
         keys = [
             "order_id",
         ]

         ["gold.sales.daily"]
         format = "parquet"
         path = "${paths.output}/${env}/gold/daily"

         ["gold.sales.daily".write]
         mode = "overwrite"
         partition = [
             "order_date",
         ]

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         orders_raw:
           description: Orders as exported by the shop
           format: csv
           path: ${paths.input}/orders.csv
           options: {header: true}
           incremental: {column: order_date}      # read + fingerprint only the run's window
           quality:                               # contract: checked wherever it is read
             empty_dataset: true
             schema: {expected_columns: [order_id, amount, order_date]}
         silver.sales.orders:                     # no path: <output>/<env>/silver/sales/orders
           format: delta
           write:
             mode: merge
             merge: {keys: [order_id]}
         gold.sales.daily:
           format: parquet
           path: ${paths.output}/${env}/gold/daily
           write: {mode: overwrite, partition: [order_date]}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "orders_raw": {
             "description": "Orders as exported by the shop",
             "format": "csv",
             "path": "${paths.input}/orders.csv",
             "options": {
               "header": true
             },
             "incremental": {
               "column": "order_date"
             },
             "quality": {
               "empty_dataset": true,
               "schema": {
                 "expected_columns": [
                   "order_id",
                   "amount",
                   "order_date"
                 ]
               }
             }
           },
           "silver.sales.orders": {
             "format": "delta",
             "write": {
               "mode": "merge",
               "merge": {
                 "keys": [
                   "order_id"
                 ]
               }
             }
           },
           "gold.sales.daily": {
             "format": "parquet",
             "path": "${paths.output}/${env}/gold/daily",
             "write": {
               "mode": "overwrite",
               "partition": [
                 "order_date"
               ]
             }
           }
         }

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Key
     - Meaning
   * - ``format``
     - ``csv``, ``json``, ``parquet``, ``delta``, ``orc``, ``avro``, ``xml``,
       ``query`` (SQL/JDBC) or ``pickle``. Required. (Kafka and other streams
       are configured on ``kind: stream`` nodes.)
   * - ``path``
     - File, directory or URI. Optional for a three-part name — see below.
   * - ``table``
     - A metastore / Unity Catalog table instead of a path (with
       ``catalog_name``/``schema_name`` where needed).
   * - ``options``
     - Reader options, passed to Spark as-is (``header``, ``sep``,
       ``mergeSchema``…).
   * - ``schema``
     - A DDL string (``"order_id BIGINT, amount DOUBLE"``) applied when reading.
   * - ``incremental``
     - ``{column: …}``: Ducta filters the read to ``--start-date``/``--end-date``
       on that column (pushed down to the source) and fingerprints only that
       window, so a daily run over a three-year table costs one day.
   * - ``read``
     - Delta time travel: ``{version: 12}`` or ``{timestamp: "2026-01-31"}``.
   * - ``write``
     - How a node writes it — see below.
   * - ``quality``
     - The dataset's contract: checks run on every read, by any node.
       Same shape as a node's ``quality`` block (:ref:`quality-config`).

Where a dataset lives
~~~~~~~~~~~~~~~~~~~~~

A dataset without ``path`` or ``table`` whose name has three parts —
``schema.sub_folder.table`` — lives at
``<paths.output>/<env>/<schema>/<sub_folder>/<table>``. That convention keeps
environments apart without writing a single path: ``silver.sales.orders`` is
``data/dev/silver/sales/orders`` under ``--env dev`` and
``data/prod/silver/sales/orders`` under ``--env prod``. Any other dataset needs a
``path`` (or ``table``, or ``query`` for a SQL source).

Writing
~~~~~~~

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         ["silver.sales.customers"]
         format = "delta"

         ["silver.sales.customers".write]
         mode = "merge"
         partition = [
             "country",
         ]

         ["silver.sales.customers".write.merge]
         keys = [
             "customer_id",
         ]
         when_matched = "update_all"
         when_not_matched = "insert_all"
         delete_when = "src._deleted = true"
         schema_evolution = false

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         silver.sales.customers:
           format: delta
           write:
             mode: merge
             merge:
               keys: [customer_id]
               when_matched: update_all          # update_all | ignore | {update: [cols]}
               when_not_matched: insert_all      # insert_all | ignore
               delete_when: "src._deleted = true"
               schema_evolution: false
             partition: [country]

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "silver.sales.customers": {
             "format": "delta",
             "write": {
               "mode": "merge",
               "merge": {
                 "keys": [
                   "customer_id"
                 ],
                 "when_matched": "update_all",
                 "when_not_matched": "insert_all",
                 "delete_when": "src._deleted = true",
                 "schema_evolution": false
               },
               "partition": [
                 "country"
               ]
             }
           }
         }

``mode`` is ``overwrite`` (default), ``append``, ``ignore``, ``error`` or
``merge``. ``merge`` is an upsert on ``keys`` for Delta outputs; a batch with
duplicate keys fails with the offending keys rather than Delta's own error, and
a first run creates the table. For a Delta overwrite of one slice only, use
``overwrite_strategy: replaceWhere`` with ``partition_col`` or
``replace_predicate``. ``write.options`` holds writer options when they differ
from the reader's ``options``.

.. _catalog-folder:

A catalog split by layer
~~~~~~~~~~~~~~~~~~~~~~~~

Past a few dozen datasets one ``catalog.yaml`` is hard to scan. Replace it with a
``catalog/`` folder: every file in it (any depth) is a mapping of dataset names to
datasets, and together they are the catalog.

.. code-block:: text

   catalog/
   ├── sources.yaml     # raw inputs and seeds (names with no layer prefix)
   ├── bronze.yaml
   ├── silver.yaml
   └── gold.yaml

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog/silver.toml
         ["silver.sales.orders"]
         description = "Orders, deduplicated and typed"
         format = "delta"

         ["silver.sales.orders".write]
         mode = "merge"

         ["silver.sales.orders".write.merge]
         keys = [
             "order_id",
         ]

         ["silver.sales.orders".quality.null_rate]
         columns = [
             "order_id",
         ]
         threshold = 0.0

         ["silver.sales.orders".quality.duplicates]
         columns = [
             "order_id",
         ]
         max_duplicate_rate = 0.0

         ["silver.sales.orders".quality.gate]
         max_errors = 0

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog/silver.yaml
         silver.sales.orders:
           description: Orders, deduplicated and typed
           format: delta
           write:
             mode: merge
             merge: {keys: [order_id]}
           quality:
             null_rate: {columns: [order_id], threshold: 0.0}
             duplicates: {columns: [order_id], max_duplicate_rate: 0.0}
             gate: {max_errors: 0}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "silver.sales.orders": {
             "description": "Orders, deduplicated and typed",
             "format": "delta",
             "write": {
               "mode": "merge",
               "merge": {
                 "keys": [
                   "order_id"
                 ]
               }
             },
             "quality": {
               "null_rate": {
                 "columns": [
                   "order_id"
                 ],
                 "threshold": 0.0
               },
               "duplicates": {
                 "columns": [
                   "order_id"
                 ],
                 "max_duplicate_rate": 0.0
               },
               "gate": {
                 "max_errors": 0
               }
             }
           }
         }

Two rules keep it unambiguous. A project keeps its datasets in **one place**:
``catalog.yaml`` next to a ``catalog/`` folder is an error. And a dataset is
declared **once**: the same name in two files is an error that names both files.
Errors and ``ducta config explain`` cite the real file and line
(``catalog/silver.yaml:4``). The files may be YAML, TOML or JSON, as everywhere.

When the API edits a dataset it writes it back to the file that declares it; a new
dataset goes to ``catalog/<layer>.yaml`` (``catalog/sources.yaml`` when its name has
no layer).

pipelines/<name>.yaml
---------------------

One file per pipeline; the file's name is the pipeline's name.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/etl.toml
         description = "Orders to daily totals"
         requires_dates = true

         [nodes.clean]
         run = "pipelines.etl:clean"
         outputs = [
             "silver.sales.orders",
         ]

         [nodes.clean.inputs]
         raw = "orders_raw"

         [nodes.clean.quality.checks.null_rate]
         columns = [
             "order_id",
         ]
         threshold = 0

         [nodes.clean.quality.checks.duplicates]
         columns = [
             "order_id",
         ]

         [nodes.clean.quality.gate]
         max_errors = 0
         on_fail = "skip_downstream"

         [nodes.daily]
         run = "pipelines.etl:daily"
         inputs = [
             "silver.sales.orders",
         ]
         outputs = [
             "gold.sales.daily",
         ]
         timeout_seconds = 600
         retry = 1

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/etl.yaml
         description: Orders to daily totals
         requires_dates: true
         nodes:
           clean:
             run: pipelines.etl:clean              # module:function
             inputs: {raw: orders_raw}             # parameter → dataset
             outputs: [silver.sales.orders]
             quality:
               checks:
                 null_rate: {columns: [order_id], threshold: 0}
                 duplicates: {columns: [order_id]}
               gate: {max_errors: 0, on_fail: skip_downstream}
           daily:
             run: pipelines.etl:daily
             inputs: [silver.sales.orders]         # depends on `clean`: inferred from the data
             outputs: [gold.sales.daily]
             timeout_seconds: 600
             retry: 1

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "description": "Orders to daily totals",
           "requires_dates": true,
           "nodes": {
             "clean": {
               "run": "pipelines.etl:clean",
               "inputs": {
                 "raw": "orders_raw"
               },
               "outputs": [
                 "silver.sales.orders"
               ],
               "quality": {
                 "checks": {
                   "null_rate": {
                     "columns": [
                       "order_id"
                     ],
                     "threshold": 0
                   },
                   "duplicates": {
                     "columns": [
                       "order_id"
                     ]
                   }
                 },
                 "gate": {
                   "max_errors": 0,
                   "on_fail": "skip_downstream"
                 }
               }
             },
             "daily": {
               "run": "pipelines.etl:daily",
               "inputs": [
                 "silver.sales.orders"
               ],
               "outputs": [
                 "gold.sales.daily"
               ],
               "timeout_seconds": 600,
               "retry": 1
             }
           }
         }

Pipeline keys
~~~~~~~~~~~~~

.. list-table::
   :widths: 26 74
   :header-rows: 1

   * - Key
     - Meaning
   * - ``nodes``
     - The pipeline's nodes, by name.
   * - ``type``
     - ``batch`` (default), ``ml``, ``streaming`` or ``hybrid`` — selects the
       executor.
   * - ``requires_dates``
     - ``true`` (default): runs need ``--start-date``/``--end-date``. Set
       ``false`` for pipelines that always process everything.
   * - ``depends_on``
     - Pipelines to run before this one, as a chain. With
       ``reuse_if_materialized: true`` an upstream whose outputs already exist
       for the same inputs is skipped.
   * - ``spark_config``
     - Spark settings for this pipeline only.
   * - ``model_version``, ``split``, ``hyperparams``, ``hyperparams_config``
     - ML pipelines — see :doc:`mlops`. A node may set ``split``, ``hyperparams`` and
       ``model_version`` too, overriding the pipeline's; ``ml_stage: training`` or
       ``evaluation`` binds it to apply the pipeline's split.
   * - ``description``, ``metadata``
     - Documentation; not read by Ducta.

Node keys
~~~~~~~~~

.. list-table::
   :widths: 26 74
   :header-rows: 1

   * - Key
     - Meaning
   * - ``run``
     - ``package.module:function``, imported relative to the project root.
   * - ``inputs``
     - ``{parameter: dataset}`` — each dataset is passed to the function
       argument of that name (preferred), or ``[dataset, …]`` passed
       positionally.
   * - ``outputs``
     - Where the DataFrame the function returns is written. With several
       datasets, the same result is written to each (e.g. a Delta table and a
       CSV extract).
   * - ``after``
     - Nodes to run first when no dataset connects them.
   * - ``quality``
     - Checks on the node's output and the gate that judges them.
   * - ``input_checks``
     - ``{dataset: {checks: …}}`` — checks on one input, for this node only.
   * - ``timeout_seconds``
     - This node's time limit (overrides ``node_timeout_seconds``).
   * - ``retry``
     - Retries after a failure (0–10, default 0).
   * - ``run_in_process``
     - Run the node in its own process, so a timeout can stop pure-Python
       code that never calls Spark.
   * - ``ml_stage``
     - ``feature_engineering``, ``training``, ``evaluation`` or ``serving``. A
       ``training``/``evaluation`` node must apply the pipeline's ``split``.
   * - ``split``, ``hyperparams``, ``model_version``
     - This node's own, overriding the pipeline's. A node with a ``split`` must apply
       it — see :doc:`mlops`.
   * - ``on_missing_input``
     - When an input does not exist yet: ``skip`` (default — the node and its
       dependants are skipped) or ``fail``.
   * - ``description``, ``metadata``
     - Documentation; not read by Ducta.

**Ordering comes from the data.** ``daily`` reads what ``clean`` writes, so it
runs after it; nodes with no path between them run in parallel. Node names are
unique across the project — certificates and the run ledger identify nodes by
name — and each node belongs to exactly one pipeline.

The function receives DataFrames and returns DataFrames; Ducta reads and
writes them:

.. code-block:: python

   # pipelines/etl.py
   from pyspark.sql import DataFrame, functions as F

   def clean(raw: DataFrame) -> DataFrame:
       return raw.dropDuplicates(["order_id"]).filter(F.col("amount") > 0)

   def daily(orders: DataFrame) -> DataFrame:
       return orders.groupBy("order_date").agg(F.sum("amount").alias("revenue"))

Node kinds
~~~~~~~~~~

``kind: transform`` is the default and runs your function. Two other kinds need
no code:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/landing.toml
         requires_dates = false

         [nodes.land_orders]
         kind = "ingest"
         outputs = [
             "bronze.shop.orders",
         ]

         [nodes.land_orders.ingest]
         source = "shop_db"
         table = "public.orders"
         columns = [
             "order_id",
             "amount",
             "order_date",
         ]
         where = "order_date >= '2026-01-01'"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/landing.yaml
         requires_dates: false
         nodes:
           land_orders:
             kind: ingest                          # copy from a database connection
             ingest:
               source: shop_db                     # a connection from `ducta init ingestion`
               table: public.orders
               columns: [order_id, amount, order_date]
               where: "order_date >= '2026-01-01'"
             outputs: [bronze.shop.orders]

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "requires_dates": false,
           "nodes": {
             "land_orders": {
               "kind": "ingest",
               "ingest": {
                 "source": "shop_db",
                 "table": "public.orders",
                 "columns": [
                   "order_id",
                   "amount",
                   "order_date"
                 ],
                 "where": "order_date >= '2026-01-01'"
               },
               "outputs": [
                 "bronze.shop.orders"
               ]
             }
           }
         }

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
         format = "file_stream"
         file_format = "json"
         schema = "event_id STRING, amount DOUBLE, ts TIMESTAMP"

         [nodes.clean_events.stream.input.options]
         path = "${paths.input}/events"

         [nodes.clean_events.stream.transform]
         key = "clean_events"
         module = "pipelines.transforms"

         [nodes.clean_events.stream.transform.params]
         min_amount = 0.0

         [nodes.clean_events.stream.output]
         format = "parquet"
         path = "${paths.output}/${env}/silver/events"

         [nodes.clean_events.stream.streaming]
         checkpoint_location = "${paths.output}/${env}/_ckpt/clean_events"
         output_mode = "append"
         trigger = "5s"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/events.yaml
         type: streaming
         requires_dates: false
         nodes:
           clean_events:
             kind: stream                          # Structured Streaming
             stream:
               input:
                 format: file_stream
                 file_format: json
                 options: {path: "${paths.input}/events"}
                 schema: event_id STRING, amount DOUBLE, ts TIMESTAMP
               transform:                          # a registered transform, with parameters
                 key: clean_events
                 module: pipelines.transforms
                 params: {min_amount: 0.0}
               output:
                 format: parquet
                 path: ${paths.output}/${env}/silver/events
               streaming:
                 checkpoint_location: ${paths.output}/${env}/_ckpt/clean_events
                 output_mode: append
                 trigger: 5s                       # or '5 minutes', available_now, once

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
                   "format": "file_stream",
                   "file_format": "json",
                   "options": {
                     "path": "${paths.input}/events"
                   },
                   "schema": "event_id STRING, amount DOUBLE, ts TIMESTAMP"
                 },
                 "transform": {
                   "key": "clean_events",
                   "module": "pipelines.transforms",
                   "params": {
                     "min_amount": 0.0
                   }
                 },
                 "output": {
                   "format": "parquet",
                   "path": "${paths.output}/${env}/silver/events"
                 },
                 "streaming": {
                   "checkpoint_location": "${paths.output}/${env}/_ckpt/clean_events",
                   "output_mode": "append",
                   "trigger": "5s"
                 }
               }
             }
           }
         }

Each kind accepts only its own keys: an ``ingest`` node with ``run:`` is an
error. A stream node is closed too: how it runs (``checkpoint_location``,
``trigger``, ``output_mode``, ``query_name``, ``watermark``) goes in its
``streaming:`` block, and the same key placed beside ``input`` or inside
``output`` is an error that says so — the engine never read it there.
``checkpoint_location`` and ``query_name`` have defaults; every node needs its
own checkpoint. See :doc:`streaming` for stream nodes.

.. _defaults-templates:

Say it once: defaults and pipeline templates
--------------------------------------------

A value shared by many datasets or nodes is written once.

**Defaults.** ``defaults`` in ``ducta.yaml`` (and, for nodes, in a pipeline file)
gives datasets and nodes the values they do not set themselves. Precedence, lowest
first: project ``defaults`` < pipeline ``defaults`` < the dataset or node itself <
the active environment's overrides.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "sales"

         [paths]
         input = "data"
         output = "data"

         [defaults.catalog."bronze.*"]
         format = "parquet"

         [defaults.catalog."silver.*"]
         format = "parquet"

         [defaults.catalog."gold.*"]
         format = "csv"

         [defaults.node]
         retry = 2

         [defaults.stream.streaming]
         trigger = "10s"
         output_mode = "append"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: sales
         paths: {input: data, output: data}
         defaults:
           catalog:                           # {glob: dataset keys}, applied in order
             "bronze.*": {format: parquet}
             "silver.*": {format: parquet}
             "gold.*": {format: csv}
           node:                              # retry, timeout_seconds, on_missing_input, fail_fast
             retry: 2
           stream:                            # the `stream:` block of every stream node
             streaming: {trigger: 10s, output_mode: append}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "sales",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "defaults": {
             "catalog": {
               "bronze.*": {
                 "format": "parquet"
               },
               "silver.*": {
                 "format": "parquet"
               },
               "gold.*": {
                 "format": "csv"
               }
             },
             "node": {
               "retry": 2
             },
             "stream": {
               "streaming": {
                 "trigger": "10s",
                 "output_mode": "append"
               }
             }
           }
         }

A ``quality`` default applies only to nodes that declare a ``quality`` block, so a
default gate does not turn every node into one with checks to run.
``ducta config explain`` shows which values came from defaults.

**Templates.** A pipeline file can build on a template: a pipeline written once,
with ``${params.name}`` placeholders, kept under ``templates/``. The template's
keys sit *under* the file's own — mappings merge, lists and scalars replace — and
a placeholder that is the whole value keeps its type. A placeholder also works
inside a **key**, which is how one template serves several pipelines: node names
are unique across the project, so each copy has to name its nodes differently.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/ml.risk.toml
         extends = "templates/ml_xgboost"
         description = "Early academic-risk warning"

         [params]
         target = "At_Risk"
         method = "stratified"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/ml.risk.yaml
         extends: templates/ml_xgboost
         params: {target: At_Risk, method: stratified}
         description: Early academic-risk warning   # replaces the template's description

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "extends": "templates/ml_xgboost",
           "params": {
             "target": "At_Risk",
             "method": "stratified"
           },
           "description": "Early academic-risk warning"
         }

.. code-block:: yaml

   # templates/ml_xgboost.yaml
   params:
     target: null                         # null: required. A value: its default.
     method: random
   type: ml
   requires_dates: false
   split: {method: "${params.method}", stratify_col: "${params.target}", seed: 42}
   nodes:
     train_${params.target}:              # a placeholder in a key names the node per copy
       description: "Train a model for ${params.target}"
       run: pipelines.ml:train
       ml_stage: training
       inputs: {features: silver.ml.features}
       outputs: [gold.ml.metrics]

Anything else the file writes is merged over the template: a
``nodes: {train_At_Risk: {retry: 3}}`` in ``ml.risk.yaml`` adds ``retry`` to the
template's ``train_At_Risk`` node and keeps the rest.
A template is not a pipeline: it is not discovered, it cannot extend another
template, and a parameter it does not declare is an error. There is no
conditional and no loop; if a template needs one, it is two templates. TOML has
no null, so a required parameter is written ``"<required>"`` there.

Two things to know about placeholders in keys. Only a plain value (text or a number)
can be part of a name — a list or a mapping is an error that says so — and two keys
that become the same name are an error, never a silent overwrite. And in YAML, write
such a template in block style: ``{raw: ${params.t}_raw}`` is not valid inside a
flow mapping (``{...}``) unless quoted, whereas ``raw: ${params.t}_raw`` on its own
line is fine.

.. _quality-config:

Quality checks and gates
------------------------

The same block — ``checks`` plus an optional ``gate`` — appears in three places:

- a dataset's ``quality`` in the catalog: a contract checked whenever any node
  reads it;
- a node's ``input_checks``: checks on one input for that node only — they
  replace the dataset's catalog contract for that node;
- a node's ``quality``: checks on what the node writes.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/etl.toml
         [nodes.clean]
         run = "pipelines.etl:clean"
         outputs = [
             "silver.sales.orders",
         ]

         [nodes.clean.inputs]
         raw = "orders_raw"

         [nodes.clean.input_checks.orders_raw.checks.row_count]
         min = 1

         [nodes.clean.quality]
         profile = "strict"

         [nodes.clean.quality.checks]
         empty_dataset = true
         duplicates = false

         [nodes.clean.quality.checks.null_rate]
         columns = [
             "order_id",
         ]
         threshold = 0

         [nodes.clean.quality.gate]
         max_errors = 0
         on_fail = "stop_all"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/etl.yaml
         nodes:
           clean:
             run: pipelines.etl:clean
             inputs: {raw: orders_raw}
             outputs: [silver.sales.orders]
             input_checks:
               orders_raw:
                 checks:
                   row_count: {min: 1}
             quality:
               profile: strict                     # checks from settings.quality.profiles
               checks:
                 null_rate: {columns: [order_id], threshold: 0}
                 empty_dataset: true               # `name: true` enables a check with its defaults
                 duplicates: false                 # `false` disables one the profile enables
               gate:
                 max_errors: 0
                 on_fail: stop_all                 # skip_downstream (default) | stop_all | warn_only

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "nodes": {
             "clean": {
               "run": "pipelines.etl:clean",
               "inputs": {
                 "raw": "orders_raw"
               },
               "outputs": [
                 "silver.sales.orders"
               ],
               "input_checks": {
                 "orders_raw": {
                   "checks": {
                     "row_count": {
                       "min": 1
                     }
                   }
                 }
               },
               "quality": {
                 "profile": "strict",
                 "checks": {
                   "null_rate": {
                     "columns": [
                       "order_id"
                     ],
                     "threshold": 0
                   },
                   "empty_dataset": true,
                   "duplicates": false
                 },
                 "gate": {
                   "max_errors": 0,
                   "on_fail": "stop_all"
                 }
               }
             }
           }
         }

Profiles live in ``ducta.yaml``:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "sales"

         [paths]
         input = "data"
         output = "data"

         [settings.quality.profiles.strict.checks.empty_dataset]
         enabled = true

         [settings.quality.profiles.strict.checks.duplicates]
         columns = [
             "id",
         ]

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: sales
         paths: {input: data, output: data}
         settings:
           quality:
             profiles:
               strict:
                 checks:
                   empty_dataset: {enabled: true}
                   duplicates: {columns: [id]}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "sales",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "quality": {
               "profiles": {
                 "strict": {
                   "checks": {
                     "empty_dataset": {
                       "enabled": true
                     },
                     "duplicates": {
                       "columns": [
                         "id"
                       ]
                     }
                   }
                 }
               }
             }
           }
         }

Checks can also be listed directly, next to the gate, without the ``checks:``
level; any key that is not ``gate``, ``enabled``, ``fail_fast``, ``profile``,
``dataset_name`` or ``output`` is read as the name of a check:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/etl.toml
         [nodes.clean]
         run = "pipelines.etl:clean"
         outputs = [
             "silver.sales.orders",
         ]

         [nodes.clean.inputs]
         raw = "orders_raw"

         [nodes.clean.quality.null_rate]
         columns = [
             "order_id",
         ]
         threshold = 0

         [nodes.clean.quality.row_count]
         min = 400

         [nodes.clean.quality.gate]
         max_errors = 0

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/etl.yaml
         nodes:
           clean:
             run: pipelines.etl:clean
             inputs: {raw: orders_raw}
             outputs: [silver.sales.orders]
             quality:
               null_rate: {columns: [order_id], threshold: 0}
               row_count: {min: 400}
               gate: {max_errors: 0}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "nodes": {
             "clean": {
               "run": "pipelines.etl:clean",
               "inputs": {
                 "raw": "orders_raw"
               },
               "outputs": [
                 "silver.sales.orders"
               ],
               "quality": {
                 "null_rate": {
                   "columns": [
                     "order_id"
                   ],
                   "threshold": 0
                 },
                 "row_count": {
                   "min": 400
                 },
                 "gate": {
                   "max_errors": 0
                 }
               }
             }
           }
         }

**Parameters are checked when the project is loaded**, with the file and line:
an unknown parameter (``colums``), a value of the wrong type or outside its range
(``threshold: 5`` where a share between 0 and 1 is expected), and a near miss of a
built-in check's name (``null_rte``). The same table feeds the editor schema, so
``row_count: {min: ...}`` completes. A custom check declares its parameters with a
``CONFIG_SCHEMA`` on its class to get the same treatment; one that declares
nothing is accepted as before.

The checks available, their parameters and custom checks are in :doc:`quality`.

.. _profiles-file:

Profiles in their own file
~~~~~~~~~~~~~~~~~~~~~~~~~~

Quality profiles (named, reusable sets of checks) can live in
``quality/profiles.yaml`` instead of ``settings.quality.profiles``, which keeps
``ducta.yaml`` short:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # quality/profiles.toml
         [customers_dimension.checks.null_rate]
         columns = [
             "customer_id",
             "country",
         ]
         threshold = 0.0

         [customers_dimension.checks.duplicates]
         columns = [
             "customer_id",
         ]
         max_duplicate_rate = 0.0

         [strict.checks.empty_dataset]
         enabled = true

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # quality/profiles.yaml
         customers_dimension:
           checks:
             null_rate: {columns: [customer_id, country], threshold: 0.0}
             duplicates: {columns: [customer_id], max_duplicate_rate: 0.0}
         strict:
           checks:
             empty_dataset: {enabled: true}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "customers_dimension": {
             "checks": {
               "null_rate": {
                 "columns": [
                   "customer_id",
                   "country"
                 ],
                 "threshold": 0.0
               },
               "duplicates": {
                 "columns": [
                   "customer_id"
                 ],
                 "max_duplicate_rate": 0.0
               }
             }
           },
           "strict": {
             "checks": {
               "empty_dataset": {
                 "enabled": true
               }
             }
           }
         }

The file is merged into ``settings.quality.profiles`` before environments apply,
so an environment can still override one value
(``settings.quality.profiles.strict.checks...``). A profile defined in both places is
an error — there is no silent winner. Nodes and datasets use them exactly as before,
with ``profile: customers_dimension``.

.. _environments:

Environments
------------

Ducta knows five environments: ``base`` (the project as written; the default
when ``--env`` is omitted), ``dev``, ``sandbox`` (and ``sandbox_<developer>``),
``staging`` and ``prod``. ``--env`` also accepts ``production``,
``development``, ``test``/``testing``, and any other name you choose (``qa``).

``environments.<env>`` in ``ducta.yaml`` holds **only what differs**, and is
deep-merged over the whole project — settings, paths, catalog entries and
pipelines:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "sales"

         [paths]
         input = "data"
         output = "data"

         [settings]
         max_parallel_nodes = 4

         [environments.dev.settings]
         max_parallel_nodes = 1
         log_level = "DEBUG"

         [environments.prod]
         "catalog.gold.sales.daily.write.mode" = "append"
         "pipelines.etl.nodes.clean.quality.gate.on_fail" = "stop_all"

         [environments.prod.paths]
         input = "s3://lake/raw"
         output = "s3://lake/curated"

         [environments.prod.settings]
         max_parallel_nodes = 16
         evidence_level = "signed"

         [environments.prod.settings.run_lock]
         backend = "storage"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: sales
         paths: {input: data, output: data}
         settings: {max_parallel_nodes: 4}
         environments:
           dev:
             settings: {max_parallel_nodes: 1, log_level: DEBUG}
           prod:
             paths: {input: s3://lake/raw, output: s3://lake/curated}
             settings: {max_parallel_nodes: 16, evidence_level: signed, run_lock: {backend: storage}}
             catalog.gold.sales.daily.write.mode: append
             pipelines.etl.nodes.clean.quality.gate.on_fail: stop_all

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "sales",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "max_parallel_nodes": 4
           },
           "environments": {
             "dev": {
               "settings": {
                 "max_parallel_nodes": 1,
                 "log_level": "DEBUG"
               }
             },
             "prod": {
               "paths": {
                 "input": "s3://lake/raw",
                 "output": "s3://lake/curated"
               },
               "settings": {
                 "max_parallel_nodes": 16,
                 "evidence_level": "signed",
                 "run_lock": {
                   "backend": "storage"
                 }
               },
               "catalog.gold.sales.daily.write.mode": "append",
               "pipelines.etl.nodes.clean.quality.gate.on_fail": "stop_all"
             }
           }
         }

- Mappings merge key by key; lists and scalars replace.
- A dotted key sets one value deep inside the project. Dataset names that
  contain dots resolve as you would expect (``catalog.gold.sales.daily.write.mode``).
- An override can only address ``settings``, ``paths``, ``catalog``,
  ``pipelines`` and ``metadata``, and the merged result is validated like the
  base project — an override cannot introduce an unknown key either.
- A dotted key must name something that exists. ``pipelines.etl.nodes.clena.retry``
  is an error at the line in ``ducta.yaml`` — *there is no node 'clena' in pipeline
  'etl' — did you mean 'clean'?* — and a typo in the last segment
  (``…nodes.clean.retyr``) is reported at ``ducta.yaml`` too, not at the pipeline
  file whose key it addressed. (A nested mapping can still add a whole new dataset or
  node to one environment.)
- ``sandbox_alice`` uses its own block if there is one, otherwise ``sandbox``'s.
  There is no other inheritance: ``staging`` does not pick up ``prod``'s block —
  repeat the keys, or share them with a YAML anchor.
- An environment without a block runs the base project (logged at INFO).

``ducta config validate --env prod`` validates one environment;
``ducta config validate`` validates the base project.

Variables and secrets
---------------------

Inside the catalog and settings:

- ``${paths.input}`` and ``${paths.output}`` — the environment's ``paths``;
- ``${env}`` — the active environment (``dev``, ``prod``…);
- ``${NAME}`` — the environment variable ``NAME`` of the process running Ducta,
  for values that differ per machine (``${DATA_ROOT}``, ``${WAREHOUSE_HOST}``).
  An unset variable is left as written.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         [events]
         format = "parquet"
         path = "${DATA_ROOT}/events/${env}"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         events:
           format: parquet
           path: ${DATA_ROOT}/events/${env}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "events": {
             "format": "parquet",
             "path": "${DATA_ROOT}/events/${env}"
           }
         }

**Credentials never go in configuration.** ``${NAME}`` refuses variable names
that look like secrets — containing ``PASSWORD``, ``SECRET``, ``TOKEN``,
``KEY``, ``CREDENTIAL`` — because configuration values end up in logs and next
to Run Certificates. Instead:

- database connections for ``kind: ingest`` nodes read ``<SOURCE>_USER`` and
  ``<SOURCE>_PASSWORD`` from the environment or a ``.env`` file
  (``ducta init ingestion setup`` writes them);
- cloud storage uses the platform's own credentials (instance profiles,
  Databricks secrets, ``AWS_*`` variables);
- the certificate signing key is ``DUCTA_CERTIFICATE_KEY``.

Keep ``.env`` out of version control.

File formats
------------

A project's files can be YAML, TOML or JSON: ``ducta.yaml``, ``ducta.toml`` or
``ducta.json``, and the same for ``catalog`` and each file under ``pipelines/``
(and ``templates/``). The format is only syntax; a project means the same thing
in all three, and files of different formats can live side by side — one pipeline
in YAML and another in TOML. A project keeps one file per role: ``ducta.yaml``
and ``ducta.toml`` together are an error, not a choice.

.. list-table::
   :widths: 14 43 43
   :header-rows: 1

   * - Format
     - Good for
     - Mind
   * - YAML
     - Pipelines: nested nodes and checks read best, and comments carry the
       explanations (the templates are YAML for this reason).
     - Words such as ``no`` or ``1e3`` are read as a boolean or a number; quote them.
   * - TOML
     - ``ducta.toml``: flat settings and environments that rarely change.
     - Deep trees turn into long ``[a.b.c.d]`` headers. No null: a ``null`` key is
       left out.
   * - JSON
     - Files written by tools, which round-trip exactly.
     - No comments. A top-level ``"$schema"`` key names the editor schema and is
       ignored.

Errors name the file and the line in every format. TOML locates every key written
as ``key = value`` under its table; a value inside an inline table or a
multi-line array is located at the line of the key that holds it.

The same project in the three formats
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The pipeline below is one file, ``pipelines/etl``, written three ways. Every tab
is the same pipeline: ``ducta config show --engine`` prints the same documents
for all of them, and each one passes ``ducta config validate`` and runs. The TOML
and JSON tabs are what ``ducta config convert`` writes from the YAML one.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml
         :caption: pipelines/etl.toml

         #:schema ../.ducta/schema/pipeline.json
         description = "Orders: land, clean, aggregate"
         type = "batch"
         requires_dates = false

         [nodes.extract]
         run = "pipelines.etl:extract"
         outputs = [
             "bronze.etl.raw_data",
         ]

         [nodes.extract.inputs]
         source_data = "source_data"

         [nodes.transform]
         run = "pipelines.etl:transform"
         outputs = [
             "silver.etl.clean_data",
         ]

         [nodes.transform.inputs]
         raw_data = "bronze.etl.raw_data"

         [nodes.transform.quality.null_rate]
         columns = [
             "amount",
         ]
         threshold = 0.0

         [nodes.transform.quality.range]
         column = "amount"
         min = 0

         [nodes.transform.quality.gate]
         max_errors = 0
         on_fail = "skip_downstream"

         [nodes.load]
         run = "pipelines.etl:load"
         outputs = [
             "gold.etl.final_output",
         ]

         [nodes.load.inputs]
         clean_data = "silver.etl.clean_data"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml
         :caption: pipelines/etl.yaml

         description: "Orders: land, clean, aggregate"
         type: batch
         requires_dates: false

         nodes:
           extract:
             run: pipelines.etl:extract
             inputs: {source_data: source_data}
             outputs: [bronze.etl.raw_data]

           transform:
             run: pipelines.etl:transform
             inputs: {raw_data: bronze.etl.raw_data}
             outputs: [silver.etl.clean_data]
             quality:
               null_rate: {columns: [amount], threshold: 0.0}
               range: {column: amount, min: 0}
               gate: {max_errors: 0, on_fail: skip_downstream}

           load:
             run: pipelines.etl:load
             inputs: {clean_data: silver.etl.clean_data}
             outputs: [gold.etl.final_output]

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json
         :caption: pipelines/etl.json

         {
           "$schema": "../.ducta/schema/pipeline.json",
           "description": "Orders: land, clean, aggregate",
           "type": "batch",
           "requires_dates": false,
           "nodes": {
             "extract": {
               "run": "pipelines.etl:extract",
               "inputs": {
                 "source_data": "source_data"
               },
               "outputs": [
                 "bronze.etl.raw_data"
               ]
             },
             "transform": {
               "run": "pipelines.etl:transform",
               "inputs": {
                 "raw_data": "bronze.etl.raw_data"
               },
               "outputs": [
                 "silver.etl.clean_data"
               ],
               "quality": {
                 "null_rate": {
                   "columns": [
                     "amount"
                   ],
                   "threshold": 0.0
                 },
                 "range": {
                   "column": "amount",
                   "min": 0
                 },
                 "gate": {
                   "max_errors": 0,
                   "on_fail": "skip_downstream"
                 }
               }
             },
             "load": {
               "run": "pipelines.etl:load",
               "inputs": {
                 "clean_data": "silver.etl.clean_data"
               },
               "outputs": [
                 "gold.etl.final_output"
               ]
             }
           }
         }


The project file follows the same rule:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml
         :caption: ducta.toml

         #:schema .ducta/schema/project.json
         version = 2
         project = "orders"

         [paths]
         input = "data"
         output = "data"

         [settings]
         mode = "local"
         max_parallel_nodes = 4

         [defaults.catalog."bronze.*"]
         format = "parquet"

         [defaults.catalog."silver.*"]
         format = "parquet"

         [defaults.catalog."gold.*"]
         format = "csv"

         [environments.dev.settings]
         max_parallel_nodes = 1
         log_level = "DEBUG"

         [environments.prod.settings]
         max_parallel_nodes = 8

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml
         :caption: ducta.yaml

         version: 2
         project: orders
         paths: {input: data, output: data}

         settings:
           mode: local
           max_parallel_nodes: 4

         defaults:
           catalog:
             "bronze.*": {format: parquet}
             "silver.*": {format: parquet}
             "gold.*": {format: csv}

         environments:
           dev:
             settings: {max_parallel_nodes: 1, log_level: DEBUG}
           prod:
             settings: {max_parallel_nodes: 8}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json
         :caption: ducta.json

         {
           "$schema": ".ducta/schema/project.json",
           "version": 2,
           "project": "orders",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "mode": "local",
             "max_parallel_nodes": 4
           },
           "defaults": {
             "catalog": {
               "bronze.*": {
                 "format": "parquet"
               },
               "silver.*": {
                 "format": "parquet"
               },
               "gold.*": {
                 "format": "csv"
               }
             }
           },
           "environments": {
             "dev": {
               "settings": {
                 "max_parallel_nodes": 1,
                 "log_level": "DEBUG"
               }
             },
             "prod": {
               "settings": {
                 "max_parallel_nodes": 8
               }
             }
           }
         }


What changes from one to the next is only syntax:

* **Comments** exist in YAML and TOML (``#``), not in JSON. ``ducta template
  --format toml|json`` and ``ducta config convert`` write no comments, so a
  project that is explained in its comments is best kept in YAML.
* **Editor schema.** YAML names it in a ``# yaml-language-server: $schema=``
  comment, TOML in a ``#:schema`` comment, JSON in a top-level ``"$schema"`` key.
  All three point at the files ``ducta config schema --out .`` writes under
  ``.ducta/schema/``.
* **Dotted names are quoted keys in TOML**: ``[defaults.catalog."bronze.*"]``,
  where YAML writes ``"bronze.*": {...}``.
* **Inline mappings** (``inputs: {raw_data: bronze.etl.raw_data}``) are a table
  in TOML (``[nodes.transform.inputs]``) and a nested object in JSON.

Pick the format per file, not per project: ``ducta.yaml`` can sit next to
``pipelines/etl.toml`` and ``pipelines/report.json``. To move a whole project
from one to another:

.. code-block:: bash

   ducta config convert --to toml --out ../orders-toml   # writes ducta.toml, catalog.toml, pipelines/*.toml
   cp -r pipelines/*.py ../orders-toml/pipelines/        # your Python and data are not copied
   cd ../orders-toml && ducta config validate

``ducta template --format toml|json`` writes a template in that format, and
``ducta config convert`` rewrites an existing project (see below). Converted
files carry no comments.

Checking a project
------------------

.. code-block:: bash

   ducta config validate                 # schema, references, cycles, input names — every problem at once
   ducta config validate --env prod      # the project as prod sees it
   ducta config list-pipelines           # what can run
   ducta start --pipeline etl --validate-only   # plus preflight: modules, functions, paths
   ducta config schema --out .           # refresh .ducta/schema/ for editor autocompletion

What it catches before anything runs, with the file and line: unknown keys and
near-miss names; references to datasets, nodes and pipelines that do not exist;
**dependency cycles** (through ``after``, through the data nodes read and write, and
between pipelines); a dotted environment override that names a node, pipeline or
dataset that is not there; and, in ``ducta config validate`` and ``ducta start
--validate-only``, an ``inputs`` key that is **not a parameter of the node's
function** — ``inputs: {raw_dat: …}`` for ``def clean(raw_data, …)`` — which would
otherwise fail only when the node runs, after the nodes before it had already
written their output.

To see what a project resolves to, and why:

.. code-block:: bash

   ducta config show --env prod                  # the project after templates, defaults, overrides
   ducta config show --pipeline etl --format toml  # one pipeline and its datasets, as TOML
   ducta config show --engine --format json      # the five documents the engine reads
   ducta config explain settings.max_parallel_nodes --env prod
   ducta config diff dev prod                    # every value that differs
   ducta config convert --to toml --out ../proj-toml

``explain`` follows one value through the file, the template it extends,
``defaults`` and the environment, with the file and line of each step:

.. code-block:: text

   settings.max_parallel_nodes = 8
     file                         4   ducta.yaml:15
     environments.prod            8   ducta.yaml:32

The JSON Schemas under ``.ducta/schema/`` give editors completion and inline
errors. With the VS Code YAML extension:

.. code-block:: json

   {
     "yaml.schemas": {
       ".ducta/schema/project.json": "ducta.yaml",
       ".ducta/schema/catalog.json": "catalog.yaml",
       ".ducta/schema/pipeline.json": "pipelines/*.yaml"
     }
   }

Conventions
-----------

A project reads the same to everyone when the names follow one pattern.

.. list-table::
   :widths: 22 38 40
   :header-rows: 1

   * - What
     - Convention
     - Example
   * - Dataset
     - ``layer.domain.table``; layers ``seed``, ``bronze``, ``silver``, ``gold``,
       ``ml``. The name places it on disk when it has no ``path``.
     - ``silver.sales.orders``
   * - Pipeline
     - ``layer.domain`` — the file name is the pipeline name.
     - ``pipelines/silver.sales.yaml``
   * - Node
     - ``verb_object`` in snake_case; a layer prefix only where the name would
       be ambiguous across pipelines.
     - ``clean_orders``, ``train_churn``
   * - ``inputs`` keys
     - The parameter name of the function the node runs, so the contract reads
       without opening the code.
     - ``inputs: {orders_raw: bronze.sales.orders}``
   * - Environments
     - ``dev``, ``sandbox``, ``staging``, ``prod``; ``sandbox_<developer>`` for
       personal ones.
     - ``environments: {prod: …}``

**One format per project.** Files of different formats can live side by side, but a
team that mixes three syntaxes pays for it in every review. Use YAML throughout (it
keeps comments), or TOML for a small project whose settings are flat; keep JSON for
files tools write (``ducta config show --format json``, the editor schemas).
``ducta config convert`` moves a whole project from one to another.

A project grows into this layout:

.. code-block:: text

   my_project/
   ├── ducta.yaml                 # project, paths, settings, environments (aim for < 40 lines)
   ├── catalog/                   # or one catalog.yaml while it is short
   │   ├── sources.yaml
   │   ├── bronze.yaml
   │   ├── silver.yaml
   │   └── gold.yaml
   ├── quality/
   │   └── profiles.yaml          # reusable quality profiles
   ├── pipelines/
   │   ├── bronze.sales.yaml      # <layer>.<domain>.yaml
   │   ├── silver.sales.yaml
   │   └── ml.churn_train.yaml
   ├── templates/                 # pipelines written once, used with extends/params
   ├── hyperparams/               # model hyperparameters, apart from the code
   ├── src/my_project/            # the functions nodes run
   └── .ducta/                    # generated: schemas, runs (keep out of git)

``ducta init project`` writes this layout. Data engineers mostly edit
``pipelines/`` and ``catalog/``; data scientists edit the ML pipeline's ``split``,
``hyperparams`` and ``model_version`` without touching Python:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/ml.churn_train.toml
         description = "Churn model — features, training, evaluation"
         type = "ml"
         requires_dates = false
         model_version = "2026.10"

         [hyperparams]
         n_estimators = 200
         max_depth = 8

         [split]
         method = "stratified"
         stratify_col = "churned"
         test_size = 0.2
         val_size = 0.2
         seed = 42

         [nodes.build_features]
         run = "churn.features:build_features"
         ml_stage = "feature_engineering"
         outputs = [
             "ml.churn.features",
         ]

         [nodes.build_features.inputs]
         orders = "silver.sales.orders"

         [nodes.train_model]
         run = "churn.model:train_model"
         ml_stage = "training"
         outputs = [
             "ml.churn.metrics",
         ]
         after = [
             "build_features",
         ]

         [nodes.train_model.inputs]
         features = "ml.churn.features"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/ml.churn_train.yaml
         description: Churn model — features, training, evaluation
         type: ml
         requires_dates: false
         model_version: "2026.10"
         hyperparams: {n_estimators: 200, max_depth: 8}
         split: {method: stratified, stratify_col: churned, test_size: 0.2, val_size: 0.2, seed: 42}
         nodes:
           build_features:
             run: churn.features:build_features
             ml_stage: feature_engineering
             inputs: {orders: silver.sales.orders}
             outputs: [ml.churn.features]
           train_model:
             run: churn.model:train_model
             ml_stage: training
             inputs: {features: ml.churn.features}
             outputs: [ml.churn.metrics]
             after: [build_features]

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "description": "Churn model — features, training, evaluation",
           "type": "ml",
           "requires_dates": false,
           "model_version": "2026.10",
           "hyperparams": {
             "n_estimators": 200,
             "max_depth": 8
           },
           "split": {
             "method": "stratified",
             "stratify_col": "churned",
             "test_size": 0.2,
             "val_size": 0.2,
             "seed": 42
           },
           "nodes": {
             "build_features": {
               "run": "churn.features:build_features",
               "ml_stage": "feature_engineering",
               "inputs": {
                 "orders": "silver.sales.orders"
               },
               "outputs": [
                 "ml.churn.features"
               ]
             },
             "train_model": {
               "run": "churn.model:train_model",
               "ml_stage": "training",
               "inputs": {
                 "features": "ml.churn.features"
               },
               "outputs": [
                 "ml.churn.metrics"
               ],
               "after": [
                 "build_features"
               ]
             }
           }
         }

A pipeline repeated for several sources is written once as a template and each
copy states only its parameters (see *Say it once* above):

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/bronze.customers.toml
         extends = "templates/ingest_csv"

         [params]
         table = "customers"
         source = "data/raw/customers.csv"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/bronze.customers.yaml
         extends: templates/ingest_csv
         params: {table: customers, source: data/raw/customers.csv}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "extends": "templates/ingest_csv",
           "params": {
             "table": "customers",
             "source": "data/raw/customers.csv"
           }
         }

Good practice
-------------

- Name datasets ``layer.domain.table`` (``silver.sales.orders``): the name
  documents the dataset and gives it a location in every environment for free.
- Give functions named parameters and map them with ``inputs: {param: dataset}``
  — reordering inputs can then never swap two DataFrames.
- Put a contract (``quality``) on datasets other teams produce; it guards every
  node that reads them.
- Keep ``environments`` blocks short. If one grows as large as the base
  project, the environments are probably different projects.
- Run ``ducta config validate`` in CI, next to your tests.
