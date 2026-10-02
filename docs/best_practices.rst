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

.. code-block:: yaml

   # catalog.yaml
   orders_raw:
     format: csv
     path: ${paths.input}/orders.csv
     options: {header: true}
     quality:
       empty_dataset: true
       schema: {expected_columns: [order_id, amount, order_date]}

**Make large inputs incremental.** ``incremental: {column: …}`` reads — and
fingerprints — only the run's ``--start-date``/``--end-date`` window, so a daily
run costs a day of data, not the whole table.

**Make re-runs safe.** Writing the same window twice must not duplicate it:
use ``write.mode: merge`` with ``keys`` for Delta tables, or
``overwrite_strategy: replaceWhere`` to replace exactly the window a run
produces. Plain ``append`` duplicates on every retry.

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
