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

``ducta template`` generates a complete project; the sections below explain
each file. Commands find the project the way git finds a repository: from the
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

.. code-block:: yaml

   # catalog.yaml
   orders_raw:
     description: Orders as exported by the shop
     format: csv
     path: ${paths.input}/orders.csv
     options: {header: true}
     incremental: {column: order_date}      # read + fingerprint only the run's window
     checks:                                # contract: checked wherever it is read
       checks:
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
   * - ``checks``
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

``mode`` is ``overwrite`` (default), ``append``, ``ignore``, ``error`` or
``merge``. ``merge`` is an upsert on ``keys`` for Delta outputs; a batch with
duplicate keys fails with the offending keys rather than Delta's own error, and
a first run creates the table. For a Delta overwrite of one slice only, use
``overwrite_strategy: replaceWhere`` with ``partition_col`` or
``replace_predicate``. ``write.options`` holds writer options when they differ
from the reader's ``options``.

pipelines/<name>.yaml
---------------------

One file per pipeline; the file's name is the pipeline's name.

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
     - ML pipelines — see :doc:`mlops`.
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
           trigger: {type: processing_time, interval: 5 seconds}

Each kind accepts only its own keys: an ``ingest`` node with ``run:`` is an
error. See :doc:`streaming` for stream nodes.

.. _quality-config:

Quality checks and gates
------------------------

The same block — ``checks`` plus an optional ``gate`` — appears in three places:

- a dataset's ``checks`` in the catalog: a contract checked whenever any node
  reads it;
- a node's ``input_checks``: checks on one input for that node only — they
  replace the dataset's catalog contract for that node;
- a node's ``quality``: checks on what the node writes.

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

Profiles live in ``ducta.yaml``:

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

The checks available, their parameters and custom checks are in :doc:`quality`.

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

- Mappings merge key by key; lists and scalars replace.
- A dotted key sets one value deep inside the project. Dataset names that
  contain dots resolve as you would expect (``catalog.gold.sales.daily.write.mode``).
- An override can only address ``settings``, ``paths``, ``catalog``,
  ``pipelines`` and ``metadata``, and the merged result is validated like the
  base project — an override cannot introduce an unknown key either.
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

.. code-block:: yaml

   # catalog.yaml
   events:
     format: parquet
     path: ${DATA_ROOT}/events/${env}

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

Checking a project
------------------

.. code-block:: bash

   ducta config validate                 # schema + references, every problem at once
   ducta config validate --env prod      # the project as prod sees it
   ducta config list-pipelines           # what can run
   ducta start --pipeline etl --validate-only   # plus preflight: modules, functions, paths
   ducta config schema --out .           # refresh .ducta/schema/ for editor autocompletion

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

.. _migrating:

Upgrading a project from Ducta 0.2
----------------------------------

Ducta 0.3 reads only this layout. A project still in the previous one
(``environment.yaml`` + ``config/global_config.yaml``, ``pipelines.yaml``,
``nodes.yaml``, ``input.yaml``, ``output.yaml``) stops with a message naming the
command that converts it:

.. code-block:: bash

   ducta config migrate                  # report only: what would change
   ducta config migrate --out /tmp/v2    # write the new files elsewhere to review
   ducta config migrate --write          # convert in place; old files → .ducta/format1-backup/
   ducta config migrate --check          # exit 1 while a project still needs it (CI)

``migrate`` converts every environment and compiles the result back to prove it
configures the engine identically in each one before it writes anything. Its
report lists what it changes on purpose: pipeline ``inputs``/``outputs`` (which
were never read), keys Ducta does not read (moved to ``metadata``) and
dependencies the data already implies. A project's ``config_fingerprint``
changes once, because those keys are gone.

``migrate`` runs with Ducta 0.3, so upgrade first and convert after. It handles
the ``environment.*`` layout and the single-file, directory and two-file
variants; multi-layer projects (a ``ducta.yaml`` with ``layers:``) are converted
one layer at a time, each becoming its own project.

.. list-table:: Where each old setting went
   :widths: 45 55
   :header-rows: 1

   * - Before (0.2)
     - Now
   * - ``environment.yaml`` + ``config/global_config.yaml``
     - ``ducta.yaml`` (``paths``, ``settings``)
   * - ``config/input.yaml`` + ``config/output.yaml``
     - ``catalog.yaml`` (one entry per dataset)
   * - ``config/pipelines.yaml`` + ``config/nodes.yaml``
     - ``pipelines/<name>.yaml``
   * - ``config/<env>/*.yaml``, ``global_config.environments``
     - ``environments.<env>`` in ``ducta.yaml`` (only what differs)
   * - ``module`` + ``function``
     - ``run: module:function``
   * - ``input`` / ``output`` on a node
     - ``inputs`` / ``outputs``
   * - ``dependencies`` / ``depends_on`` on a node
     - inferred from datasets; ``after:`` otherwise
   * - ``sanity_checks`` (+ ``input_index``)
     - dataset ``checks`` in the catalog, or ``input_checks`` on the node
   * - ``data_quality`` + ``quality_gate`` (``behavior``)
     - ``quality`` with ``gate`` (``on_fail``)
   * - ``filepath``, ``write_mode``, ``merge``, ``partition``
     - ``path``, ``write: {mode, merge, partition}``
   * - ``timeout`` on a node
     - ``timeout_seconds``
   * - ``${input_path}`` / ``${output_path}`` / ``${environment}``
     - ``${paths.input}`` / ``${paths.output}`` / ``${env}``

Good practice
-------------

- Name datasets ``layer.domain.table`` (``silver.sales.orders``): the name
  documents the dataset and gives it a location in every environment for free.
- Give functions named parameters and map them with ``inputs: {param: dataset}``
  — reordering inputs can then never swap two DataFrames.
- Put a contract (``checks``) on datasets other teams produce; it guards every
  node that reads them.
- Keep ``environments`` blocks short. If one grows as large as the base
  project, the environments are probably different projects.
- Run ``ducta config validate`` in CI, next to your tests.
