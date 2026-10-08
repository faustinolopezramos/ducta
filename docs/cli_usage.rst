CLI Command Reference
=====================

Every command runs against a **project**: the nearest directory, from the
current one upwards, holding a ``ducta.yaml`` (see :doc:`configuration`). Pass
``--base-path PATH`` to work on a project elsewhere. ``ducta <command> --help``
lists every option of a command.

.. code-block:: bash

   ducta template --template medallion_basic --project-name sales   # create a project
   cd sales
   ducta config validate --env dev                                  # check it
   ducta start --env dev --pipeline etl \
     --start-date 2026-01-01 --end-date 2026-01-31                  # run it
   ducta certify list                                               # what ran, with evidence

``ducta start`` — run a pipeline
--------------------------------

.. code-block:: bash

   ducta start --pipeline NAME [--env ENV] [OPTIONS]

.. list-table::
   :widths: 34 66
   :header-rows: 1

   * - Option
     - Meaning
   * - ``--pipeline, -p NAME``
     - The pipeline to run (its file name under ``pipelines/``). Required.
   * - ``--env, -e ENV``
     - Environment: ``base`` (default), ``dev``, ``sandbox``,
       ``sandbox_<developer>``, ``staging``, ``prod`` or a name of your own.
   * - ``--start-date`` / ``--end-date``
     - The window to process (``YYYY-MM-DD``). Required by pipelines with
       ``requires_dates: true``; incremental datasets read only this window.
   * - ``--node, -n NAME``
     - Run one node only.
   * - ``--validate-only``
     - Validate the configuration and run preflight (modules import, functions
       exist, paths resolve) without running anything.
   * - ``--sanity-only``
     - Run the input checks of every node without running the nodes.
   * - ``--dry-run``
     - Log what would run, without running it.
   * - ``--reuse-upstream``
     - In a ``depends_on`` chain, skip upstream pipelines whose outputs are
       still valid: same dates, configuration, code and input data as when they
       were written. Otherwise the upstream re-runs and the log says what
       changed.
   * - ``--rerun-all``
     - Re-run the whole chain, ignoring reuse settings.
   * - ``--mode, -m {async,sync}``
     - Streaming and hybrid pipelines: return once started (``async``, default)
       or wait for the queries to finish (``sync``).
   * - ``--base-path PATH``
     - The project directory, when not running from inside it.
   * - ``--log-level LEVEL``, ``--verbose``, ``--quiet``, ``--log-file PATH``
     - Logging.

ML pipelines add ``--model-version``, ``--hyperparams JSON``, and
hyperparameter search: ``--sweep FILE`` (the cartesian product of a grid),
``--search`` (grid, random or Bayesian search driven by the pipeline's
``hyperparams_config``), ``--search-metric``, ``--search-trials``,
``--sweep-parallel N``, ``--max-sweep-size N`` and ``--no-sweep-reuse``. See
:doc:`mlops`.

.. code-block:: bash

   # One month of the daily pipeline, in production
   ducta start --env prod --pipeline daily_sales --start-date 2026-01-01 --end-date 2026-01-31

   # Just one node, with debug logging
   ducta start --env dev --pipeline etl --node clean --verbose

   # Everything that can be checked without running
   ducta start --env prod --pipeline etl --validate-only

Exit codes
~~~~~~~~~~

Orchestrators can act on the exit code of ``ducta start``:

.. list-table::
   :widths: 10 90
   :header-rows: 1

   * - Code
     - Meaning
   * - 0
     - Success.
   * - 1
     - Unexpected error.
   * - 2
     - The project cannot run as configured: no project found, invalid
       configuration, or a failed preflight.
   * - 3
     - Invalid command-line arguments — an unknown pipeline name, a malformed
       date.
   * - 4
     - The pipeline ran and failed.
   * - 5
     - A missing dependency (e.g. an optional extra is not installed).
   * - 6
     - A security check refused a path or module.
   * - 7
     - **Locked**: another run is writing one of this pipeline's outputs.
       Nothing ran; retry later (see ``settings.run_lock``).

``ducta init project`` — create a project
-----------------------------------------

.. code-block:: bash

   ducta init project --name sales                          # batch ETL, ./sales
   ducta init project --name churn --type ml --format toml --path ~/work/churn

Writes a project in the recommended layout: ``ducta.<ext>``, ``catalog/<layer>.<ext>``,
``quality/profiles.<ext>``, ``pipelines/``, the Python the nodes run, and the editor
schemas in ``.ducta/schema/``. ``--type`` is ``batch`` (default), ``ml``,
``streaming`` or ``hybrid``; ``--format`` is ``yaml`` (default, keeps the comments),
``toml`` or ``json``; ``--layout single`` keeps every dataset in one ``catalog.<ext>``.
The directory must be new or empty. It is ``ducta template`` with this layout as the
default, so everything below applies to it too.

``ducta template`` — create a project
-------------------------------------

.. code-block:: bash

   ducta template --template medallion_basic --project-name sales
   ducta template --template medallion_basic --project-name sales --layout split
   ducta template --list-templates

.. list-table::
   :widths: 24 76
   :header-rows: 1

   * - Template
     - What you get
   * - ``medallion_basic``
     - A batch pipeline across bronze/silver/gold with quality gates, sample
       data and code. Runs as generated.
   * - ``streaming_basic``
     - Structured Streaming from a file source through registered transforms,
       with per-node checkpoints.
   * - ``ml_basic``
     - A churn model: Spark features, scikit-learn training, the split and
       hyperparameters declared in the pipeline file, a seeded run, and a
       baseline gate before the model is registered. Needs ``ducta[spark,mlops]``.
   * - ``ml_scoring``
     - Train and promote a model, then score new data with it: a ``serving`` node
       with no code, prediction checks against the validation scores, and the
       model version in the run certificate. Run ``train``, then ``score``. Needs
       ``ducta[spark,mlops]``.
   * - ``hybrid_basic``
     - One ``type: hybrid`` pipeline: a batch node builds a dimension table, then
       a streaming query enriches orders against it (stream-static join). Runs
       to completion with ``ducta start --pipeline orders --mode sync``.

Options: ``--project-name`` (required), ``--output-path DIR`` (default: a new
directory named after the project), ``--no-sample-code``,
``--sandbox-developers alice bob`` (a ``sandbox_<name>`` environment each),
``--evidence-level {off,record,required,signed}`` and
``--format {yaml,toml,json}`` (default ``yaml``, which keeps the explanatory
comments).

``ducta config`` — inspect and check a project
----------------------------------------------

.. code-block:: bash

   ducta config validate [--env ENV] [--pipeline NAME]
   ducta config list-pipelines [--env ENV] [--filter TEXT] [--format table|json|list]
   ducta config pipeline-info --pipeline NAME [--env ENV]
   ducta config schema [--out DIR]
   ducta config show [--env ENV] [--pipeline NAME] [--format yaml|toml|json] [--engine | --ml]
   ducta config explain PATH [--env ENV]
   ducta config diff ENV_A ENV_B
   ducta config convert --to yaml|toml|json --out DIR

- ``validate`` checks the schema and every reference between files, then
  imports each node's function and checks its signature — without starting
  Spark. Every problem is reported with its file and line.
- ``schema`` prints the JSON Schema of ``ducta.yaml``, ``catalog.yaml`` and
  pipeline files; ``--out .`` refreshes ``.ducta/schema/`` for editor
  completion.
- ``show`` prints the project as it resolves for an environment — templates,
  defaults and overrides applied — in any of the three formats; ``--engine``
  prints the five documents the engine reads; ``--ml`` prints what each ML node will
  be given (its split and where it was declared, whether it must apply it, its merged
  hyperparameters and model version — see :doc:`mlops`).
- ``explain`` says where one value comes from (file, template, defaults or
  environment), with the file and line of each step.
- ``diff`` lists every value that differs between two environments.
- ``convert`` rewrites the configuration files in another format, in a new
  directory; comments are not carried over.

``ducta stream`` — streaming pipelines
--------------------------------------

.. code-block:: bash

   ducta stream run --pipeline events [--env ENV] [--mode async|sync]
   ducta stream status [--execution-id ID] [--format table|json]
   ducta stream stop --execution-id ID [--timeout SECONDS]

Run from inside the project, or point ``--config`` at its ``ducta.yaml``.
``--transforms-module MODULE`` imports modules that register transforms before
the pipeline starts (``settings.streaming_transform_modules`` does the same from
configuration). See :doc:`streaming`.

``ducta certify`` — Run Certificates
------------------------------------

Every run writes a self-hashed certificate — configuration fingerprint, input
and output fingerprints, quality outcomes — to
``<paths.output>/<env>/.ducta/runs/<run_id>/certificate.json``.

.. code-block:: bash

   ducta certify list [--env ENV]
   ducta certify show --run-id ID [--json]           # a unique prefix of the id is enough
   ducta certify verify --run-id ID                  # tamper check (and signature, if signed)
   ducta certify verify --run-id ID --reproduce \
     --start-date 2026-01-01 --end-date 2026-01-31   # re-run and compare every output
   ducta certify diff RUN_A RUN_B                    # what changed between two runs

See :doc:`tutorials/certificates`.

``ducta quality`` and ``ducta profile`` — data quality
------------------------------------------------------

.. code-block:: bash

   ducta quality list                                # every registered check
   ducta quality validate-config --node clean --env prod
   ducta quality run --input data.parquet --config checks.yaml
   ducta quality report --dataset silver.sales.orders --env dev [--all | --run-id ID]
   ducta quality trend --dataset silver.sales.orders --env dev [--last 20]
   ducta quality score --run-id ID --env dev
   ducta profile --input data.parquet [--strictness strict|balanced|lax] [--output checks.yaml]

- ``validate-config`` checks a node's checks and profiles as an environment
  configures them, without reading data.
- ``run`` applies a checks file to a data file, outside any project.
- ``profile`` reads a dataset and proposes the checks it already satisfies — a
  starting point for a contract.

See :doc:`quality`.

``ducta experiment`` and ``ducta model`` — MLOps
------------------------------------------------

.. code-block:: bash

   ducta experiment list --env dev [--pipeline NAME] [--limit 20]
   ducta model promote churn_model 1.2.0 production --env prod
   ducta model gc --env prod --dry-run

Promotion goes through the promotion policy; ``--force`` bypasses it and the
bypass is audit-logged. See :doc:`mlops`.

``ducta init ingestion`` — database connections
-----------------------------------------------

.. code-block:: bash

   ducta init ingestion setup              # interactive: writes the connection and its .env credentials
   ducta init ingestion list
   ducta init ingestion test --source shop_db
   ducta init ingestion info --source shop_db

``kind: ingest`` nodes read from these connections — see :doc:`configuration`.

``ducta ui`` and ``ducta server`` — web app and API
---------------------------------------------------

.. code-block:: bash

   ducta ui [--port 8000] [--host 127.0.0.1] [--source PATH_OR_GIT_URL] [--no-browser]
   ducta server start [--port 8000] [--host 127.0.0.1] [--source PATH_OR_GIT_URL]

Both serve the web app and its REST API. ``--db PATH`` moves the execution
history (default ``~/.ducta/executions.db``). See :doc:`server_api`.

Next steps
----------

- :doc:`configuration` — every file and key
- :doc:`tutorials/batch_etl` — a pipeline from scratch
- :doc:`best_practices` — running Ducta in production
