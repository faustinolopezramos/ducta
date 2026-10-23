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
       ``--format yaml|toml|json``, ``--layout split|single``).
   * - ``ducta template``
     - Scaffolds a new project from a professional template, with every dataset in one catalog file.
   * - ``ducta list``
     - Shows the project's pipelines (the same as ``ducta config list-pipelines``).
   * - ``ducta check``
     - Checks every file against the schema and every reference, reporting all problems (the same as ``ducta config validate``).
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
     - Checks DAG integrity and configuration without running the pipeline (it
       imports the node modules to check their functions).
   * - ``ducta quality run``
     - Runs a checks file against a data file (``--input``, ``--config``), outside
       any pipeline.
   * - ``ducta experiment list|runs|show|compare``
     - Lists experiments and their runs, shows one run, or compares runs side by side
       (``--output-format json`` for scripts).
   * - ``ducta model promote|gc``
     - Moves a registered model version to a stage, or removes old versions.
   * - ``ducta server start``
     - Launches the API and the web app (the same command as ``ducta ui``).
   * - ``ducta --version``
     - Displays the installed version.

Common Runtime Flags
--------------------

*   ``-p, --pipeline <name>``: The target pipeline to execute (required for ``ducta start``).
*   ``-e, --env <env>``: The environment to load — ``base``, ``dev``, ``sandbox``, ``prod``, or ``sandbox_<developer>`` (defaults to ``base``).
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

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/sales.toml
         [nodes.clean_sales]
         run = "myproject.nodes:clean_sales"
         outputs = [
             "core.analytics.sales_clean",
         ]
         retry = 2
         timeout_seconds = 600

         [nodes.clean_sales.inputs]
         sales = "raw_sales"

         [nodes.clean_sales.quality.checks.row_count]
         min = 1000

         [nodes.clean_sales.quality.checks.null_rate]
         columns = [
             "id",
         ]
         threshold = 0.0

         [nodes.clean_sales.quality.checks.duplicates]
         columns = [
             "id",
         ]

         [nodes.clean_sales.quality.gate]
         max_errors = 0
         on_fail = "skip_downstream"

   .. tab-item:: YAML
      :sync: yaml

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

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "nodes": {
             "clean_sales": {
               "run": "myproject.nodes:clean_sales",
               "inputs": {
                 "sales": "raw_sales"
               },
               "outputs": [
                 "core.analytics.sales_clean"
               ],
               "retry": 2,
               "timeout_seconds": 600,
               "quality": {
                 "checks": {
                   "row_count": {
                     "min": 1000
                   },
                   "null_rate": {
                     "columns": [
                       "id"
                     ],
                     "threshold": 0.0
                   },
                   "duplicates": {
                     "columns": [
                       "id"
                     ]
                   }
                 },
                 "gate": {
                   "max_errors": 0,
                   "on_fail": "skip_downstream"
                 }
               }
             }
           }
         }

Other kinds: ``kind: ingest`` (``ingest: {source, table | query, columns, where}``)
and ``kind: stream`` (``stream: {input, transform, output, streaming: {trigger, checkpoint_location}}``).

Dataset Template
----------------

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # catalog.toml
         [raw_sales]
         format = "csv"
         path = "${paths.input}/sales.csv"

         [raw_sales.options]
         header = true

         [raw_sales.incremental]
         column = "sale_date"

         [raw_sales.quality]
         empty_dataset = true

         ["core.analytics.sales_clean"]
         format = "delta"

         ["core.analytics.sales_clean".write]
         mode = "merge"

         ["core.analytics.sales_clean".write.merge]
         keys = [
             "id",
         ]

   .. tab-item:: YAML
      :sync: yaml

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

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "raw_sales": {
             "format": "csv",
             "path": "${paths.input}/sales.csv",
             "options": {
               "header": true
             },
             "incremental": {
               "column": "sale_date"
             },
             "quality": {
               "empty_dataset": true
             }
           },
           "core.analytics.sales_clean": {
             "format": "delta",
             "write": {
               "mode": "merge",
               "merge": {
                 "keys": [
                   "id"
                 ]
               }
             }
           }
         }

Environment Overrides
---------------------

Only what differs, in ``ducta.yaml``:

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

         [environments.prod]
         "catalog.raw_sales.path" = "s3://landing/sales.csv"

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
         paths: {input: data, output: data}
         settings: {max_parallel_nodes: 4}
         environments:
           prod:
             settings: {max_parallel_nodes: 16, evidence_level: signed}
             paths: {output: s3://lake/prod}
             catalog.raw_sales.path: s3://landing/sales.csv

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
             "prod": {
               "settings": {
                 "max_parallel_nodes": 16,
                 "evidence_level": "signed"
               },
               "paths": {
                 "output": "s3://lake/prod"
               },
               "catalog.raw_sales.path": "s3://landing/sales.csv"
             }
           }
         }

Then run: ``ducta start --pipeline sales --env prod``
