CLI Command Reference
=====================

Every command runs against a **project**: the nearest directory, from the
current one upwards, holding a ``ducta.yaml`` (see :doc:`configuration`). Pass
``--base-path PATH`` to work on a project elsewhere. ``ducta <command> --help``
lists every option of a command.

.. code-block:: bash

   ducta template --template medallion_basic --project-name sales   # create a project
   cd sales
   ducta check --env dev                                            # check it
   ducta start --env dev --pipeline etl \
     --start-date 2026-01-01 --end-date 2026-01-31                  # run it
   ducta certify list                                               # what ran, with evidence

``ducta`` on its own shows the project you are in, its pipelines and the commands
to run next (outside a project: how to create one). ``ducta --help`` lists the
commands by what they are for, the four you use every day first: ``list`` (the
project's pipelines), ``check`` (validate without running), ``start`` and
``stream``. ``ducta list`` and ``ducta check`` are shortcuts for
``ducta config list-pipelines`` and ``ducta config validate`` and take the same
options. ``ducta --version`` prints ``ducta X.Y.Z``.
``-e`` and ``-p`` are short for ``--env`` and ``--pipeline`` in every command.

What the terminal shows
-----------------------

A run logs every step as it happens: each node, its quality checks, the schema
of what it wrote, and an execution summary. ``-v`` / ``--verbose`` (before or
after the command) adds debug lines; ``-q`` / ``--quiet`` keeps only errors.
Everything is always in ``<project>/logs/ducta.log``, at debug level. Colour only
on a terminal; ``FORCE_COLOR=1`` keeps it in a pipe.

``DUCTA_CONSOLE=compact`` is an optional short view — a header, one line per node
(rows written, time, checks), a summary, and for a failure one block with the
line of your code that raised it and what to type next; it also writes the full
error to ``logs/last-error.txt``:

.. code-block:: text

   $ DUCTA_CONSOLE=compact ducta start -e dev -p etl
   ducta 0.2.0 · etl · dev · sales

     ✓ extract     508 rows → bronze.etl.raw_data     0.7s   2 checks passed
     ✓ transform   478 rows → silver.etl.clean_data   1.0s   4 checks passed
     ✓ load          5 rows → gold.etl.final_output   0.4s   2 checks passed

   ✓ etl finished in 4.5s · 3/3 nodes
     certificate  data/dev/.ducta/runs/1a58…/certificate.json
     inspect      ducta certify show --run-id 1a586806

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
     - Streaming and hybrid pipelines. Either way the command runs while the
       queries do — they live in its process. ``async`` (default) reports their
       status and stops them on Ctrl+C; ``sync`` waits inside the engine.
   * - ``--base-path PATH``
     - The project directory, when not running from inside it.
   * - ``--log-level LEVEL``, ``-v/--verbose``, ``-q/--quiet``, ``--log-file PATH``
     - How much the terminal shows (see above) and where the log goes.

ML pipelines add ``--model-version`` and ``--hyperparams JSON`` (shown in
``ducta start --help`` under *ML tuning*), and hyperparameter search. See
:doc:`mlops` for the experiments they produce.

.. list-table:: ML tuning options of ``ducta start``
   :widths: 30 70
   :header-rows: 1

   * - Option
     - Meaning
   * - ``--sweep FILE``
     - A YAML or JSON grid. List values are expanded into their cartesian
       product and one run is executed per combination, all tagged with a
       common ``sweep_id`` in the experiment tracker.
   * - ``--search``
     - Drives a real search strategy from the pipeline's ``hyperparams_config``
       (``algorithm: grid|random|bayesian``, honouring ``n_trials`` and
       ``objective.metric``) instead of the flat cartesian product ``--sweep``
       expands. Each trial's objective value is fed back to the strategy, so
       Bayesian search learns between trials. Each trial is a run of the whole
       pipeline with the trial's values as ``--hyperparams``; a training node that
       uses ``train_with_search`` fits exactly those values (see :doc:`mlops`), and
       a node that reads ``ml_context.hyperparams`` does the same. The objective
       metric must be one the run logs (``train_with_search`` logs it, as does a
       ``persist_model(metrics=...)`` call); a search file's ``hyperparams_config``
       is a key in the file at ``hyperparams_config_path``, which
       ``ducta config validate`` checks.
   * - ``--search-metric NAME``
     - The objective metric to optimize, overriding
       ``hyperparams_config.objective.metric``. Point it at a validation
       metric: selecting on a test metric invalidates it.
   * - ``--search-trials N``
     - The trial budget of ``--search`` (random and Bayesian), overriding
       ``n_trials``.
   * - ``--no-sweep-reuse``
     - Recompute every node on each sweep or search trial. By default the
       trial-invariant upstream nodes are materialized once and reused, since
       trials differ only in hyperparameters.
   * - ``--sweep-parallel N``
     - Run N trials concurrently, each in its own process and its own output
       directory. Mutually exclusive with upstream reuse (an isolated trial has
       nothing shared to reuse), and not applied to Bayesian search, which needs
       each trial's result before choosing the next. Use it when training
       dominates the runtime, and leave ``--no-sweep-reuse`` off (the default)
       when feature engineering does.
   * - ``--max-sweep-size N``
     - Cap on the number of combinations a ``--sweep`` or ``--search`` grid may
       expand to (default: 50). Mirrors the API's ``max_sweep_size`` setting.

.. code-block:: bash

   # One month of the daily pipeline, in production
   ducta start --env prod --pipeline daily_sales --start-date 2026-01-01 --end-date 2026-01-31

   # Just one node, with debug logging
   ducta start -e dev -p etl -n clean -v

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
     - Invalid command-line arguments — an unknown pipeline or node name, a
       malformed date.
   * - 4
     - The pipeline ran and failed: a node raised, or a quality gate blocked one.
       With ``--sweep`` or ``--search``: at least one trial failed.
   * - 5
     - The pipeline did not complete: nodes were skipped because a dataset they
       read is missing (an upstream that has not run). An optional extra that is
       not installed exits ``1`` and names the ``pip install`` to run; a package
       your code imports that is not installed fails preflight (``2``).
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
The directory must be new or empty.

``ducta template`` — create a project
-------------------------------------

.. code-block:: bash

   ducta template --template medallion_basic --project-name sales
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

   ducta check [--env ENV] [--pipeline NAME] [--output-format rich|json]   # = config validate
   ducta list [--env ENV] [--filter TEXT] [--output-format table|json|list] # = config list-pipelines
   ducta config validate [--env ENV] [--pipeline NAME] [--output-format rich|json]
   ducta config list-pipelines [--env ENV] [--filter TEXT] [--output-format table|json|list]
   ducta config pipeline-info --pipeline NAME [--env ENV]
   ducta config schema [--out DIR]
   ducta config show [--env ENV] [--pipeline NAME] [--format yaml|toml|json] [--engine | --ml]
   ducta config explain PATH [--env ENV]
   ducta config diff ENV_A ENV_B
   ducta config convert --to yaml|toml|json --out DIR

- ``validate`` checks the schema and every reference between files, then
  imports each node's function and checks its signature — without starting
  Spark. Every problem is reported with its file and line. ``--output-format json``
  prints one JSON document instead (every problem with file, line, node and fix) for
  CI and AI assistants; the exit code is the same.
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

   ducta stream plan --pipeline events [--env ENV] [--output-format table|json]
   ducta stream run --pipeline events [--env ENV] [--mode async|sync]
   ducta stream status [--env ENV] [--execution-id ID] [--output-format table|json]
   ducta stream stop --execution-id ID [--env ENV] [--timeout SECONDS]

``plan`` says what the stream would do without starting Spark: per node, what it
reads, what it writes, how often it fires and the checkpoint it will use, and
what would stop it (a transform that is not registered, a source path that does
not exist, an invalid node). It exits non-zero when there are errors.

``run`` keeps running while the queries do — they live in its process — and
stops them on Ctrl+C; a terminating trigger (``available_now``) ends it on its
own. It prints one header and a line per node (source → sink, trigger) and then, once a
node has reported, every 30 seconds and whenever a node changes state, a small table
with each node's state, rows per second and batch; a quiet source is shown as ``idle``,
a hung query as ``stalled``. When it ends it prints how long it ran and what each node
processed. ``DUCTA_STREAM_REPORT_SECONDS`` sets the interval; the checkpoints are in
``ducta stream plan``. ``status`` and ``stop`` only see streams of their own process: a stream
started by another command, or by the server, is managed in that terminal (Ctrl+C)
or through the server (``GET /api/executions/{id}/streaming``,
``POST /api/executions/{id}/cancel``).

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
   ducta experiment runs <experiment_id> --env dev [--status completed] [--limit 10]
   ducta experiment show <run_id> --env dev
   ducta experiment compare <run_id> <run_id> [<run_id> ...] --env dev
   ducta model promote churn_model 3 production --env prod
   ducta model gc --env prod --dry-run

``experiment list`` shows the experiments, ``runs`` the runs of one of them (newest
first), ``show`` one run's parameters, final metrics, tags and artifacts, and
``compare`` several runs side by side — their parameters (``param_*``) and final
metrics (``metric_*``). ``show`` and ``compare`` accept a unique prefix of a run id,
and all three take ``--output-format json`` for scripts.

The commands read the tracking directory of the pipeline. Pass ``--pipeline
schema.name`` (the name of the pipeline that ran) or ``--storage-path`` when the
project does not set ``mlops_path``; without them the default directory is
``./mlops_data``, which is rarely where a pipeline wrote. A run id that does not
exist is a validation error (exit code 3) and names the directory it searched.

Promotion to ``production`` goes through the promotion policy
(``settings.mlops.promotion_policy`` of ``--env``, or of the base project without
it); ``--force`` bypasses it and the bypass is audit-logged. A project whose policy
cannot be read refuses the promotion (exit code 2) rather than skip the check.
``model gc`` keeps what ``settings.mlops.gc`` says (``max_versions_per_model``,
``model_retention_days``), as the web app does; if the project cannot be read it
deletes nothing. See :doc:`mlops`.

``ducta init ingestion`` — database connections
-----------------------------------------------

.. code-block:: bash

   ducta init ingestion setup              # interactive: writes the connection and its .env credentials
   ducta init ingestion list
   ducta init ingestion test --source shop_db
   ducta init ingestion info --source shop_db

``test`` exits ``0`` when the connection answered, ``4`` when it failed, and ``5``
when it could not be tried: testing needs a Spark session, which the CLI does not
start, so from the terminal a connection is usually checked by the first pipeline
run that uses it. ``setup`` asks before saving a connection that failed.

``kind: ingest`` nodes read from these connections — see :doc:`configuration`.

``ducta ui`` and ``ducta server`` — web app and API
---------------------------------------------------

.. code-block:: bash

   ducta ui [--port 8000] [--host 127.0.0.1] [--source PATH_OR_GIT_URL] [--no-browser]
   ducta server start [--port 8000] [--host 127.0.0.1] [--source PATH_OR_GIT_URL]

Both serve the web app and its REST API. ``--db PATH`` moves the execution
history (default ``~/.ducta/executions.db``). See :doc:`server_api`.

``ducta skill`` — the skill for AI assistants
---------------------------------------------

.. code-block:: bash

   ducta skill install [--target agents|claude|codex|gemini|copilot] [--global] [--agents-md] [--force]
   ducta skill install --path DIR
   ducta skill export --zip ducta-skill.zip
   ducta skill path

Puts Ducta's agent skill where an AI coding assistant finds it (default: the
project's ``.agents/skills/`` and ``.claude/skills/``). See :doc:`ai_assistants`.

Next steps
----------

- :doc:`configuration` — every file and key
- :doc:`tutorials/batch_etl` — a pipeline from scratch
- :doc:`best_practices` — running Ducta in production
