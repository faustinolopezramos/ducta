Quick Reference
===============

A high-level cheat sheet for Ducta developers.

Core CLI Commands
-----------------

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Command
     - Description
   * - ``ducta start``
     - Runs a pipeline: ``--pipeline <name>``, plus ``--env <env>`` (default ``base``).
   * - ``ducta init project --name NAME``
     - Creates a project in the recommended layout (``--type batch|ml|streaming|hybrid``,
       ``--format yaml|toml|json``).
   * - ``ducta template``
     - Scaffolds a new project from a professional template (one catalog file unless ``--layout split``).
   * - ``ducta config list-pipelines``
     - Shows all available pipelines in your current directory.
   * - ``ducta config validate``
     - Checks every file against the schema and every reference, reporting all problems.
   * - ``ducta config schema [--out DIR]``
     - Prints (or writes) the JSON Schemas used for editor autocompletion.
   * - ``ducta config show [--env ENV] [--pipeline NAME] [--format F]``
     - The project as it resolves for an environment (templates, defaults, overrides).
   * - ``ducta config explain PATH [--env ENV]``
     - Where one value comes from, with the file and line of each step.
   * - ``ducta config diff ENV_A ENV_B``
     - Every value that differs between two environments.
   * - ``ducta config convert --to F --out DIR``
     - The configuration files rewritten as yaml, toml or json.
   * - ``ducta start --validate-only``
     - Checks DAG integrity and configuration without running code.
   * - ``ducta quality run``
     - Runs data quality checks on a specific file or dataset.
   * - ``ducta server start``
     - Launches the Ducta API server.
   * - ``ducta --version``
     - Displays the current version and installation path.

Common Runtime Flags
--------------------

*   ``-p, --pipeline <name>``: The target pipeline to execute (required for ``ducta start``).
*   ``-e, --env <env>``: The environment to load — ``base``, ``dev``, ``sandbox``, ``prod``, or ``sandbox_<developer>`` (required for ``ducta start``; defaults to ``base`` for ``config`` subcommands).
*   ``-n, --node <name>``: Execute a single specific node.
*   ``--validate-only``: Dry run mode — validates config and DAG without executing.
*   ``--dry-run``: Log all actions without executing the pipeline.
*   ``--verbose``: Increase logging detail (equivalent to ``--log-level DEBUG``).
*   ``--quiet``: Reduce output (equivalent to ``--log-level ERROR``).

Project Layout
--------------

.. code-block:: text

   my_project/
   ├── ducta.yaml             # version: 2, project, paths, settings, environments
   ├── catalog.yaml           # every dataset once
   ├── pipelines/
   │   ├── etl.yaml           # one pipeline per file, with its nodes
   │   └── etl.py             # your functions
   └── .ducta/schema/         # JSON Schemas (editor autocompletion)

Node Template
-------------

.. code-block:: yaml

   # pipelines/sales.yaml
   nodes:
     clean_sales:
       run: myproject.nodes:clean_sales      # module:function
       inputs: {sales: raw_sales}            # parameter → dataset
       outputs: [core.analytics.sales_clean]
       retry: 2
       timeout_seconds: 600
       quality:
         checks:
           row_count: {min: 1000}
           null_rate: {columns: [id], threshold: 0.0}
           duplicates: {columns: [id]}
         gate: {max_errors: 0, on_fail: skip_downstream}

Other kinds: ``kind: ingest`` (``ingest: {source, table | query, columns, where}``)
and ``kind: stream`` (``stream: {transform, input, output, checkpoint_location, trigger}``).

Dataset Template
----------------

.. code-block:: yaml

   # catalog.yaml
   raw_sales:
     format: csv
     path: ${paths.input}/sales.csv
     options: {header: true}
     incremental: {column: sale_date}
     quality: {empty_dataset: true}
   core.analytics.sales_clean:
     format: delta
     write:
       mode: merge
       merge: {keys: [id]}

Environment Overrides
---------------------

Only what differs, in ``ducta.yaml``:

.. code-block:: yaml

   # ducta.yaml
   version: 2
   project: sales
   paths: {input: data, output: data}
   settings: {max_parallel_nodes: 4}
   environments:
     prod:
       settings: {max_parallel_nodes: 16, evidence_level: signed}
       paths: {output: s3://lake/prod}
       catalog.raw_sales.path: s3://landing/sales.csv

Then run: ``ducta start --pipeline sales --env prod``
