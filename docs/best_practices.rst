Best Practices
==============

How to lay out a Ducta project, write nodes that are easy to test, and run
pipelines in production safely. Every configuration key mentioned here is
described in :doc:`configuration`.

Project layout
--------------

.. code-block:: text

   sales/
   ├── ducta.yaml              # settings and per-environment differences
   ├── catalog.yaml            # every dataset, once
   ├── pipelines/
   │   ├── __init__.py
   │   ├── daily.yaml          # one file per pipeline
   │   ├── daily.py            # its transformations
   │   └── quality_checks.py   # custom checks, if any
   ├── tests/
   │   └── test_daily.py
   ├── .env                    # machine-local credentials — never committed
   └── .gitignore              # .env, data/, logs/

- Past a few dozen datasets, split the catalog by layer (``catalog/bronze.yaml``,
  ``catalog/silver.yaml``, …) and move reusable quality profiles to
  ``quality/profiles.yaml``; ``ducta init project`` writes that layout. The naming
  conventions are in :ref:`configuration <catalog-folder>` (*Conventions*).
- Keep a pipeline's YAML and its Python side by side: ``run: pipelines.daily:clean``
  points at ``pipelines/daily.py``.
- Commit ``.ducta/schema/`` so every editor completes and checks the YAML.
- Keep data out of the repository: ``data/`` locally, cloud paths in the
  ``prod`` overrides.

Datasets
--------

**Name datasets ``layer.domain.table``** — ``silver.sales.orders``. The name
says what the dataset is and, without a ``path``, where it lives in each
environment (``<paths.output>/<env>/silver/sales/orders``), so environments can
never overwrite each other's data.

**Declare every dataset once.** Readers and writers share one catalog entry:
changing a format or a location is one edit, and the reader can never disagree
with the writer.

**Put contracts on data you do not control.** ``quality`` on a catalog entry runs
before every node that reads it:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         [orders_raw]
         format = "csv"
         path = "${paths.input}/orders.csv"

         [orders_raw.options]
         header = true

         [orders_raw.quality]
         empty_dataset = true

         [orders_raw.quality.schema]
         expected_columns = [
             "order_id",
             "amount",
             "order_date",
         ]

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # catalog.yaml
         orders_raw:
           format: csv
           path: ${paths.input}/orders.csv
           options: {header: true}
           quality:
             empty_dataset: true
             schema: {expected_columns: [order_id, amount, order_date]}

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "orders_raw": {
             "format": "csv",
             "path": "${paths.input}/orders.csv",
             "options": {
               "header": true
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
           }
         }

**Make large inputs incremental.** ``incremental: {column: …}`` on a dataset — or
on an ``ingest`` node, where the database does the filtering — reads only the
run's ``--start-date``/``--end-date`` window, so a daily run costs a day of data,
not the whole table. ``--end-date`` is the *last day to process*: a date covers that
whole day, on a date column and on a timestamp one (an end with a time of day,
``2026-01-02T10:30:00``, is that instant, inclusive).

**Make re-runs safe.** Writing the same window twice must not duplicate it, and
writing one window must not erase the others. How an overwrite behaves is the
author's choice, and each one has a different effect on a partitioned dataset:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - ``write`` setting
     - What a run for one window does
   * - ``mode: overwrite`` (default)
     - Replaces the **whole** dataset. Right for a table recomputed in full; wrong for
       a daily load, where it leaves only the last day. ``ducta config validate`` warns
       when a node reads a window and overwrites a partitioned output this way.
   * - ``partition_overwrite: dynamic``
     - Parquet, CSV, JSON and ORC: replaces only the partitions the run wrote and keeps
       the rest. Needs ``partition`` and ``mode: overwrite``. A partition the run wrote
       no row for is not touched.
   * - ``overwrite_strategy: replaceWhere``
     - Delta: replaces exactly the run's window on ``partition_col``.
   * - ``mode: merge`` with ``keys``
     - Delta: an upsert; the window can be re-run any number of times.
   * - ``mode: append``
     - Adds rows. It duplicates on every retry.

Partitioning by year, year and month, month or day
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``write.partition`` names columns that already exist; Ducta does not derive them. Add
``year``/``month`` in the node (``withColumn``) or, for an ``ingest`` node with no Python,
in its ``query`` (``SELECT …, YEAR(order_date) AS year, MONTH(order_date) AS month``).
A window is any range: a daily job runs one day, a monthly one passes the first and last
day of the month, and a backfill is the same command over past windows (run it from the
scheduler; with a re-runnable write the result does not depend on how many times).

Choose the grain by volume, not by habit. A partition per day pays off from roughly a
gigabyte a day; with less, a month — or no partition — avoids thousands of tiny files. The
demos hold a few hundred rows, so they are not partitioned.

.. code-block:: yaml

   # catalog.yaml
   raw.sales.events:
     format: csv
     path: ${paths.input}/events.csv
     incremental: {column: event_date}        # read only the run's window
   bronze.sales.events:
     format: parquet
     write:
       mode: overwrite
       partition: [event_date]
       partition_overwrite: dynamic           # a run replaces its own days, keeps the others
   silver.sales.events:
     format: delta
     write:
       mode: merge
       merge: {keys: [event_id]}
       partition: [event_month]               # coarser than the load: fewer, larger files

.. code-block:: yaml

   # pipelines/orders_daily.yaml
   requires_dates: true
   nodes:
     land_orders:
       kind: ingest
       ingest:
         source: shop_db
         table: public.orders
         incremental: {column: updated_at}    # the database returns only the window
       outputs: [bronze.shop.orders]

Layers are names, not a feature: Ducta imposes no architecture. ``defaults.catalog`` sets
a layer's format and write policy once, by pattern. A common choice:

.. list-table::
   :header-rows: 1
   :widths: 22 42 36

   * - Layer
     - Format and write
     - Partition
   * - Raw / bronze
     - Parquet or Delta; replace the window (``dynamic``/``replaceWhere``) or append
     - The load date, or the event date
   * - Silver / curated
     - Delta; ``merge`` on the business key
     - Month, to avoid small files
   * - Gold / marts
     - Overwrite in full: the tables are small
     - None, or month
   * - Model results
     - ``append`` with the run id and model version, or the last run only
     - The run date

Nodes
-----

**Write plain functions.** A node receives DataFrames and returns one; Ducta
reads and writes the data. No Ducta imports are needed, which keeps the code
testable and portable:

.. code-block:: python

   # pipelines/daily.py
   from pyspark.sql import DataFrame, functions as F


   def clean(orders: DataFrame) -> DataFrame:
       """Drop duplicate and non-positive orders."""
       return orders.dropDuplicates(["order_id"]).filter(F.col("amount") > 0)

**Map inputs by name.** ``inputs: {orders: orders_raw}`` passes the dataset to
the parameter ``orders``. Reordering the inputs can then never swap two
DataFrames silently, as positional lists can.

**One job per node.** Small nodes give smaller failures, reusable outputs, and
checks placed exactly where a guarantee is made.

**Fail loudly.** Raise with a message that says what was wrong; never swallow
an exception to "keep going" — a failed node is recorded, retried if
configured, and reported; a silently wrong output is not.

Quality
-------

- Put **contracts** on inputs, **quality** checks on outputs, and a **gate** on
  every node whose output others depend on.
- Choose ``on_fail`` on purpose: ``skip_downstream`` (default) protects
  dependants while the rest of the pipeline runs; ``stop_all`` for outputs that
  must never be partial.
- Reuse check sets with **profiles** in ``settings.quality.profiles``.
- Start a contract from the data itself: ``ducta profile --input sample.parquet``
  proposes the checks it already satisfies.

See :doc:`quality`.

Environments
------------

Keep ``environments`` blocks to what really differs — paths, parallelism,
strictness:

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
         evidence_level = "record"

         [environments.dev.settings]
         max_parallel_nodes = 1
         log_level = "DEBUG"

         [environments.prod.paths]
         input = "s3://lake/raw"
         output = "s3://lake/curated"

         [environments.prod.settings]
         max_parallel_nodes = 16
         evidence_level = "signed"

         [environments.prod.settings.run_lock]
         backend = "storage"
         on_conflict = "fail"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: sales
         paths: {input: data, output: data}
         settings: {max_parallel_nodes: 4, evidence_level: record}
         environments:
           dev:
             settings: {max_parallel_nodes: 1, log_level: DEBUG}
           prod:
             paths: {input: s3://lake/raw, output: s3://lake/curated}
             settings:
               max_parallel_nodes: 16
               evidence_level: signed
               run_lock: {backend: storage, on_conflict: fail}

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
             "max_parallel_nodes": 4,
             "evidence_level": "record"
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
                   "backend": "storage",
                   "on_conflict": "fail"
                 }
               }
             }
           }
         }

- ``sandbox_<name>`` gives each developer their own data and checkpoints,
  falling back to ``sandbox``'s settings.
- ``staging`` does not inherit from ``prod``: if staging must mirror production,
  repeat the keys or share them with a YAML anchor.
- Validate every environment in CI: ``ducta config validate --env prod``.

Testing
-------

Nodes are plain functions, so test them with a local Spark session and small
DataFrames:

.. code-block:: python

   # tests/test_daily.py
   import pytest
   from pyspark.sql import SparkSession

   from pipelines.daily import clean


   @pytest.fixture(scope="session")
   def spark():
       return SparkSession.builder.master("local[1]").getOrCreate()


   def test_clean_drops_duplicates_and_refunds(spark):
       orders = spark.createDataFrame(
           [(1, 10.0), (1, 10.0), (2, -5.0)], ["order_id", "amount"]
       )
       assert [r.order_id for r in clean(orders).collect()] == [1]

Then, in CI, check the configuration and the wiring without running anything:

.. code-block:: bash

   ducta config validate --env dev
   ducta config validate --env prod
   ducta start --env dev --pipeline daily --validate-only

Running in production
---------------------

**Let the orchestrator read the exit code.** ``ducta start`` exits ``0`` on
success, ``2`` for configuration problems, ``4`` when the pipeline fails and
``7`` when another run holds the lock on an output — nothing ran, retry later.
See :doc:`cli_usage`.

**Keep the run lock on.** ``settings.run_lock`` (on by default, ``local``
backend) stops two runs — an overlapping retry, two people — from writing the
same output at once. With runs starting on more than one host, use
``backend: storage`` so the lock lives next to the data.

**Set time limits.** ``node_timeout_seconds`` and ``execution_timeout_seconds``
(or ``timeout_seconds`` on a node) cancel the node's Spark jobs and stop it
writing. Pure-Python work that never calls Spark can only be stopped in its own
process: set ``run_in_process: true`` on such nodes.

**Retry what is transient.** ``retry: 2`` on nodes that talk to flaky systems
(a database, an API); not on nodes whose failure means bad data.

**Keep the evidence.** With ``evidence_level: required`` a run without its
certificate fails; ``signed`` adds an HMAC signature (``DUCTA_CERTIFICATE_KEY``).
``ducta certify verify --run-id …`` proves later what ran, on which data and
configuration, and with what quality outcome.

**Process windows, not everything.** Schedule daily runs with
``--start-date``/``--end-date`` of the day; backfill by running the same
command over past windows — with idempotent writes the result is the same
however many times a window runs.

.. code-block:: bash

   # A daily job in any scheduler
   ducta start --env prod --pipeline daily \
     --start-date "$(date -d yesterday +%F)" --end-date "$(date -d yesterday +%F)"

See :doc:`tutorials/airflow_integration` for Airflow.

Security
--------

- **Credentials never go in YAML.** ``${VAR}`` refuses names containing
  ``PASSWORD``, ``SECRET``, ``TOKEN`` or ``KEY``; database connections read
  ``<SOURCE>_USER``/``<SOURCE>_PASSWORD`` from the environment or ``.env``,
  cloud storage uses the platform's credentials.
- Keep ``settings.strict_module_import`` on (the default) so only your
  project's modules can be named in ``run:``.
- Exposing the web app beyond ``localhost``: work through the
  :ref:`secure startup checklist <secure-startup-checklist>`.

Checklist before the first production run
-----------------------------------------

- ☐ ``ducta config validate --env prod`` passes in CI.
- ☐ Unit tests cover every node function.
- ☐ Inputs you do not own have contracts; shared outputs have gates.
- ☐ Large inputs are ``incremental``; outputs re-runnable (``merge`` /
  ``replaceWhere``).
- ☐ ``run_lock`` backend fits where runs start; time limits are set.
- ☐ ``evidence_level`` is ``required`` or ``signed`` in prod.
- ☐ No credentials in the repository; ``.env`` is ignored.
- ☐ The scheduler alerts on non-zero exit codes and retries on ``7``.

Next steps
----------

- :doc:`tutorials/batch_etl` — a complete pipeline
- :doc:`quality` — checks, gates and contracts
- :doc:`tutorials/certificates` — what a Run Certificate proves
