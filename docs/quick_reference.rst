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
     - Executes the project. Requires ``--env <env>`` and ``--pipeline <name>``.
   * - ``ducta template``
     - Scaffolds a new project from a professional template.
   * - ``ducta config list-pipelines``
     - Shows all available pipelines in your current directory.
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

A standard Ducta project follows this structure:

.. code-block:: text

   .
   ├── environment.toml            # Maps each environment to its config files
   ├── config/                     # YAML/TOML/JSON configuration
   │   ├── pipelines.toml          # Workflows: nodes and their order
   │   ├── nodes.toml              # Step definitions
   │   ├── global_settings.toml    # Project-wide settings
   │   ├── input.toml              # Input sources catalog
   │   ├── output.toml             # Output destinations catalog
   │   ├── dev/                    # Per-environment overrides
   │   └── prod/
   ├── pipelines/                  # Pure Python source (node functions)
   ├── .env                        # Local variables & secrets
   └── requirements.txt            # Dependencies

Node Configuration Template
---------------------------

Define your nodes in your configuration file:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — top-level key IS the node name (flat, no wrapper)
         [transform_data]
         module = "pipelines.transform"           # module holding the function
         function = "clean"                       # function name
         input = ["bronze.raw"]
         output = ["silver.clean"]
         timeout = 3600                           # seconds
         description = "Removes nulls from df"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml — top-level key IS the node name (flat, no wrapper)
         transform_data:
           module: pipelines.transform
           function: clean
           input: [bronze.raw]
           output: [silver.clean]
           timeout: 3600
           description: "Removes nulls from df"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "transform_data": {
             "module": "pipelines.transform",
             "function": "clean",
             "input": ["bronze.raw"],
             "output": ["silver.clean"],
             "timeout": 3600,
             "description": "Removes nulls from df"
           }
         }

Pipeline Configuration Template
-------------------------------

Define your workflows in ``config/pipelines.toml`` (YAML and JSON also supported):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/pipelines.toml — top-level key IS the pipeline name (flat, no wrapper)
         [daily_etl]
         description = "Main data ingestion path"
         type = "batch"
         nodes = ["extract", "transform", "load"]

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml — top-level key IS the pipeline name (flat, no wrapper)
         daily_etl:
           description: "Main data ingestion path"
           type: batch
           nodes:
             - extract
             - transform
             - load

   .. tab-item:: JSON

      .. code-block:: json

         {
           "daily_etl": {
             "description": "Main data ingestion path",
             "type": "batch",
             "nodes": ["extract", "transform", "load"]
           }
         }

Environment Overrides
---------------------

To override a setting for production, create an override file (e.g., ``config/prod/global_settings.yaml``):

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         [database]
         host = "prod-db.internal"
         port = 5432

   .. tab-item:: YAML

      .. code-block:: yaml

         database:
           host: "prod-db.internal"
           port: 5432

   .. tab-item:: JSON

      .. code-block:: json

         {
           "database": {
             "host": "prod-db.internal",
             "port": 5432
           }
         }

Then run: ``ducta start --pipeline etl --env prod``
