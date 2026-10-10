Batch ETL Tutorial
==================

Build a daily pipeline that turns a shop's order export into revenue per day
and category, across bronze, silver and gold layers — and make it safe to run
every day, re-run and backfill.

You will use:

- **incremental reads** — each run reads only its day;
- **contracts** on the source and **quality gates** on what you write;
- **MERGE** writes, so running a day twice never duplicates it;
- **Run Certificates** to prove what each run did.

Prerequisites: ``pip install "ducta[spark,delta]"`` and Java 17+ for Spark.

Step 1: The project
-------------------

.. code-block:: text

   sales/
   ├── ducta.yaml
   ├── catalog.yaml
   ├── data/orders.csv
   └── pipelines/
       ├── __init__.py
       ├── daily.yaml
       └── daily.py

``ducta.yaml`` names the project, where data lives, and what changes in
production:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "sales"
         description = "Daily revenue per category, from the shop's order export"

         [paths]
         input = "data"
         output = "data"

         [settings]
         evidence_level = "record"

         [environments.dev.settings]
         max_parallel_nodes = 1

         [environments.prod.paths]
         input = "s3://shop-exports"
         output = "s3://lake/sales"

         [environments.prod.settings]
         evidence_level = "required"

         [environments.prod.settings.run_lock]
         backend = "storage"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: sales
         description: Daily revenue per category, from the shop's order export
         paths: {input: data, output: data}
         settings:
           evidence_level: record
         environments:
           dev:
             settings: {max_parallel_nodes: 1}
           prod:
             paths: {input: s3://shop-exports, output: s3://lake/sales}
             settings: {evidence_level: required, run_lock: {backend: storage}}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "sales",
           "description": "Daily revenue per category, from the shop's order export",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "evidence_level": "record"
           },
           "environments": {
             "dev": {
               "settings": {
                 "max_parallel_nodes": 1
               }
             },
             "prod": {
               "paths": {
                 "input": "s3://shop-exports",
                 "output": "s3://lake/sales"
               },
               "settings": {
                 "evidence_level": "required",
                 "run_lock": {
                   "backend": "storage"
                 }
               }
             }
           }
         }

The sample export has two days, and the kind of mess real exports have — a
repeated order, one without an amount, one with a negative amount:

.. code-block:: text

   # data/orders.csv
   order_id,category,amount,order_date
   1,books,12.50,2026-03-01
   2,books,30.00,2026-03-01
   3,games,59.99,2026-03-01
   3,games,59.99,2026-03-01
   4,games,,2026-03-01
   5,books,-8.00,2026-03-01
   6,books,15.00,2026-03-02
   7,games,20.00,2026-03-02

Step 2: The datasets
--------------------

Every dataset is declared once in ``catalog.yaml``:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         [orders_raw]
         description = "Orders as exported by the shop, one file with every day"
         format = "csv"
         path = "${paths.input}/orders.csv"

         [orders_raw.options]
         header = true
         inferSchema = true

         [orders_raw.incremental]
         column = "order_date"

         [orders_raw.quality]
         empty_dataset = true

         [orders_raw.quality.schema]
         expected_columns = [
             "order_id",
             "category",
             "amount",
             "order_date",
         ]

         ["bronze.sales.orders"]
         format = "delta"

         ["bronze.sales.orders".write]
         mode = "merge"

         ["bronze.sales.orders".write.merge]
         keys = [
             "order_id",
         ]

         ["silver.sales.orders"]
         format = "delta"

         ["silver.sales.orders".write]
         mode = "merge"

         ["silver.sales.orders".write.merge]
         keys = [
             "order_id",
         ]

         ["gold.sales.daily_revenue"]
         format = "delta"

         ["gold.sales.daily_revenue".write]
         mode = "merge"

         ["gold.sales.daily_revenue".write.merge]
         keys = [
             "order_date",
             "category",
         ]

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         orders_raw:
           description: Orders as exported by the shop, one file with every day
           format: csv
           path: ${paths.input}/orders.csv
           options: {header: true, inferSchema: true}
           incremental: {column: order_date}
           quality:
             empty_dataset: true
             schema: {expected_columns: [order_id, category, amount, order_date]}

         bronze.sales.orders:
           format: delta
           write:
             mode: merge
             merge: {keys: [order_id]}

         silver.sales.orders:
           format: delta
           write:
             mode: merge
             merge: {keys: [order_id]}

         gold.sales.daily_revenue:
           format: delta
           write:
             mode: merge
             merge: {keys: [order_date, category]}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "orders_raw": {
             "description": "Orders as exported by the shop, one file with every day",
             "format": "csv",
             "path": "${paths.input}/orders.csv",
             "options": {
               "header": true,
               "inferSchema": true
             },
             "incremental": {
               "column": "order_date"
             },
             "quality": {
               "empty_dataset": true,
               "schema": {
                 "expected_columns": [
                   "order_id",
                   "category",
                   "amount",
                   "order_date"
                 ]
               }
             }
           },
           "bronze.sales.orders": {
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
           "gold.sales.daily_revenue": {
             "format": "delta",
             "write": {
               "mode": "merge",
               "merge": {
                 "keys": [
                   "order_date",
                   "category"
                 ]
               }
             }
           }
         }

- ``incremental: {column: order_date}`` — a run with ``--start-date`` and
  ``--end-date`` reads only those days, filtered at the source.
- ``quality`` is the source's **contract**: before any node reads it, the run's
  slice must be non-empty and have the expected columns.
- The three layers have no ``path``: their three-part names place them at
  ``data/<env>/bronze/sales/orders`` and so on, separately for each environment.
- ``write.mode: merge`` upserts on the keys: re-running a day replaces that
  day's rows instead of adding them again.

Step 3: The pipeline
--------------------

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/daily.toml
         description = "Orders to daily revenue per category"

         [nodes.land]
         description = "Bronze: the day's orders as they arrived"
         run = "pipelines.daily:land"
         outputs = [
             "bronze.sales.orders",
         ]

         [nodes.land.inputs]
         orders = "orders_raw"

         [nodes.clean]
         description = "Silver: one row per order, no missing or negative amounts"
         run = "pipelines.daily:clean"
         outputs = [
             "silver.sales.orders",
         ]

         [nodes.clean.inputs]
         orders = "bronze.sales.orders"

         [nodes.clean.quality.checks.duplicates]
         columns = [
             "order_id",
         ]

         [nodes.clean.quality.checks.null_rate]
         columns = [
             "amount",
         ]
         threshold = 0

         [nodes.clean.quality.checks.range]
         column = "amount"
         min = 0

         [nodes.clean.quality.gate]
         on_fail = "stop_all"

         [nodes.daily_revenue]
         description = "Gold: revenue and order count per day and category"
         run = "pipelines.daily:daily_revenue"
         outputs = [
             "gold.sales.daily_revenue",
         ]

         [nodes.daily_revenue.inputs]
         orders = "silver.sales.orders"

         [nodes.daily_revenue.quality.checks.row_count]
         min = 1

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/daily.yaml
         description: Orders to daily revenue per category
         nodes:
           land:
             description: "Bronze: the day's orders as they arrived"
             run: pipelines.daily:land
             inputs: {orders: orders_raw}
             outputs: [bronze.sales.orders]

           clean:
             description: "Silver: one row per order, no missing or negative amounts"
             run: pipelines.daily:clean
             inputs: {orders: bronze.sales.orders}
             outputs: [silver.sales.orders]
             quality:
               checks:
                 duplicates: {columns: [order_id]}
                 null_rate: {columns: [amount], threshold: 0}
                 range: {column: amount, min: 0}
               gate: {on_fail: stop_all}

           daily_revenue:
             description: "Gold: revenue and order count per day and category"
             run: pipelines.daily:daily_revenue
             inputs: {orders: silver.sales.orders}
             outputs: [gold.sales.daily_revenue]
             quality:
               checks:
                 row_count: {min: 1}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "description": "Orders to daily revenue per category",
           "nodes": {
             "land": {
               "description": "Bronze: the day's orders as they arrived",
               "run": "pipelines.daily:land",
               "inputs": {
                 "orders": "orders_raw"
               },
               "outputs": [
                 "bronze.sales.orders"
               ]
             },
             "clean": {
               "description": "Silver: one row per order, no missing or negative amounts",
               "run": "pipelines.daily:clean",
               "inputs": {
                 "orders": "bronze.sales.orders"
               },
               "outputs": [
                 "silver.sales.orders"
               ],
               "quality": {
                 "checks": {
                   "duplicates": {
                     "columns": [
                       "order_id"
                     ]
                   },
                   "null_rate": {
                     "columns": [
                       "amount"
                     ],
                     "threshold": 0
                   },
                   "range": {
                     "column": "amount",
                     "min": 0
                   }
                 },
                 "gate": {
                   "on_fail": "stop_all"
                 }
               }
             },
             "daily_revenue": {
               "description": "Gold: revenue and order count per day and category",
               "run": "pipelines.daily:daily_revenue",
               "inputs": {
                 "orders": "silver.sales.orders"
               },
               "outputs": [
                 "gold.sales.daily_revenue"
               ],
               "quality": {
                 "checks": {
                   "row_count": {
                     "min": 1
                   }
                 }
               }
             }
           }
         }

There is no ordering to declare: ``clean`` reads what ``land`` writes, and
``daily_revenue`` reads what ``clean`` writes. The ``clean`` gate stops the
whole run if silver would contain a duplicate, a missing or a negative amount.

The code is three plain functions — no Ducta imports:

.. code-block:: python

   # pipelines/daily.py
   from pyspark.sql import DataFrame, functions as F


   def land(orders: DataFrame) -> DataFrame:
       """Keep the source as it arrived, stamped with when it was landed."""
       return orders.dropDuplicates(["order_id"]).withColumn("landed_at", F.current_timestamp())


   def clean(orders: DataFrame) -> DataFrame:
       """Drop orders without an amount or with a negative one."""
       return orders.filter(F.col("amount").isNotNull() & (F.col("amount") >= 0))


   def daily_revenue(orders: DataFrame) -> DataFrame:
       return orders.groupBy("order_date", "category").agg(
           F.round(F.sum("amount"), 2).alias("revenue"),
           F.count("*").alias("orders"),
       )

Step 4: Check it, then run it
-----------------------------

.. code-block:: bash

   cd sales
   ducta config validate --env dev
   ducta config validate --env prod     # the production overrides are valid too

   ducta start --env dev --pipeline daily --start-date 2026-03-01 --end-date 2026-03-01
   ducta start --env dev --pipeline daily --start-date 2026-03-02 --end-date 2026-03-02

Each run reads one day. After both, ``data/dev/`` holds seven orders in bronze
(the repeated one landed once), five in silver (the missing and the negative
amount dropped), and four rows in gold:

.. code-block:: text

   order_date  category  revenue  orders
   2026-03-01  books        42.5       2
   2026-03-01  games       59.99       1
   2026-03-02  books        15.0       1
   2026-03-02  games        20.0       1

Run 2026-03-01 again: the counts do not change. That is what makes retries and
backfills safe — a backfill is the same command over past days.

Step 5: When the data is wrong
------------------------------

Break ``clean`` on purpose — make it ``return orders`` — and run the first day
again. The contract on the source passes, but the ``clean`` gate finds the
missing and negative amounts, the run stops before gold, and ``ducta start``
exits with code ``4``. The terminal shows which checks failed; restore the
function and the next run succeeds.

Step 6: The evidence
--------------------

Every run leaves a certificate under ``data/dev/.ducta/runs/``: the
configuration it ran with, fingerprints of what it read and wrote, and each
gate's outcome.

.. code-block:: bash

   ducta certify list --env dev
   ducta certify verify --run-id <id> --env dev     # a unique prefix is enough
   ducta certify diff <id-a> <id-b>                 # what changed between two runs

See :doc:`certificates`.

Step 7: From Python
-------------------

The same run, from a script or a notebook started in the project directory:

.. code-block:: python

   import ducta

   context = ducta.load_project(env="dev")
   result = ducta.PipelineExecutor(context).run_pipeline(
       "daily", start_date="2026-03-02", end_date="2026-03-02"
   )
   print(result.status, result.run_id, result.certificate_path)

``run_pipeline`` returns a ``PipelineRunResult`` (``status``, ``ok``,
``run_id``, per-node outcomes, the certificate path) and raises when the
pipeline fails.

Step 8: Schedule it
-------------------

Any scheduler that runs a command works. Run yesterday, every morning:

.. code-block:: bash

   ducta start --env prod --pipeline daily \
     --start-date "$(date -d yesterday +%F)" --end-date "$(date -d yesterday +%F)"

Treat exit code ``7`` as "another run is writing these tables — retry later",
and any other non-zero code as a failure. For Airflow, see
:doc:`airflow_integration`.

Next steps
----------

- :doc:`../quality` — every check, gates and profiles
- :doc:`../configuration` — every key of every file
- :doc:`../best_practices` — running pipelines in production
