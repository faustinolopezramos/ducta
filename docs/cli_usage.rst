CLI Command Reference
=====================

Ducta commands let you create projects, run pipelines, and manage configuration - all from the command line.

Most Common Commands
--------------------

**Create a new project:**

.. code-block:: bash

   ducta template --template medallion_basic --project-name my_project

**Run your pipeline:**

.. code-block:: bash

   ducta start --env dev --pipeline my_pipeline   # Basic run (--env and --pipeline are both required)
   ducta start --env production --pipeline my_pipeline   # Use production config
   ducta start --env dev --pipeline my_pipeline --node extract   # Run just one step
   ducta start --env dev --pipeline my_pipeline --validate-only  # Check config (don't run)
   ducta start --env dev --pipeline my_pipeline --sanity-only    # Run input sanity checks

**See what's configured:**

.. code-block:: bash

   ducta config list-pipelines
   ducta config pipeline-info --pipeline ETL

**MLOps and Quality (New!):**

.. code-block:: bash

   ducta quality list                       # List available checks
   ducta quality run --input data.parquet --config checks.toml
   ducta experiment list                    # List MLOps experiments
   ducta model promote my_model 1.0.0 staging   # name, version, stage are positional

**Check version:**

.. code-block:: bash

   ducta --version

The ``ducta start`` Command
---------------------------

This is the main command - it executes your pipelines.

**Syntax:**

.. code-block:: bash

   ducta start --env ENVIRONMENT --pipeline PIPELINE_NAME [OPTIONS]

**Common Options:**

- ``--env, -e ENVIRONMENT`` - Execution environment (``dev``, ``staging``, ``prod``, etc.) - **required**
- ``--pipeline, -p NAME`` - Pipeline name to execute - **required**
- ``--node, -n NAME`` - Run only this single node
- ``--mode, -m {sync,async}`` - For streaming/hybrid pipelines: ``async`` (default, return once started) or ``sync`` (block until terminating queries finish)
- ``--validate-only`` - Check config and DAG without running code
- ``--dry-run`` - Log all actions without executing the pipeline
- ``--sanity-only`` - Run sanity checks on all node inputs without executing the pipeline
- ``--reuse-upstream`` - In a ``depends_on`` chain, skip upstream pipelines that are still up to date and read their outputs from disk instead of recomputing. A pipeline is only reused when its outputs exist *and* the run dates, the configuration, the node modules and the input files are all unchanged since those outputs were written; otherwise it re-runs and says which of them changed
- ``--rerun-all`` - Force the full ``depends_on`` chain to re-run, ignoring any chain-reuse configuration
- ``--log-level LEVEL`` - Logging verbosity: ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL`` (default: ``INFO``)
- ``--verbose`` - Shortcut for ``--log-level DEBUG``
- ``--quiet`` - Shortcut for ``--log-level ERROR``
- ``--log-file PATH`` - Write logs to a specific file
- ``--start-date YYYY-MM-DD`` - Start of the date range to process
- ``--end-date YYYY-MM-DD`` - End of the date range to process
- ``--config-type TYPE`` - Preferred config format: ``yaml``, ``json``, or ``toml``
- ``--base-path PATH`` - Override the root directory for config discovery
- ``--layer-name NAME`` - Layer name for config discovery
- ``--use-case NAME`` - Use case name for config discovery
- ``--interactive`` - Interactive config selection mode
- ``--model-version VERSION`` - Model version for ML pipelines
- ``--hyperparams JSON`` - Hyperparameters as a JSON string
- ``--sweep PATH`` - Hyperparameter sweep spec (YAML/JSON file); expands list values into a cartesian product and runs one execution per combination, tagged with a common ``sweep_id``

.. note::
   Ducta no longer has a ``--layer`` or ``--all-layers`` flag. The execution layer
   (batch/streaming/hybrid/ML) is now detected automatically from ``pipelines.yaml``/``.toml``
   — there is nothing to pass on the command line for layer selection.

**Examples:**

.. code-block:: bash

   # Run the main ETL pipeline in development
   ducta start --env dev --pipeline etl

   # Test just the extraction step
   ducta start --env dev --pipeline etl --node extract

   # Validate config and DAG without running
   ducta start --env dev --pipeline etl --validate-only

   # Dry run: log what would happen without executing
   ducta start --env dev --pipeline etl --dry-run

   # Run with debug logging
   ducta start --env dev --pipeline etl --log-level DEBUG

   # Run for a specific date range
   ducta start --env prod --pipeline daily_etl \
     --start-date 2024-01-01 --end-date 2024-01-31

   # Run and write logs to file
   ducta start --env prod --pipeline daily_etl --log-file ./logs/daily_etl.log

The ``ducta template`` Command
-------------------------------

Generate a new project with example configuration and code:

.. code-block:: bash

   ducta template --template medallion_basic --project-name analytics

Creates a project with:

- Example configuration files (TOML by default)
- Sample Python functions
- Ready-to-run pipeline

**Available templates** (``ducta template --list-templates``):

- ``medallion_basic`` - Batch ETL with Bronze/Silver/Gold layers
- ``ml_ready`` - Medallion + integrated experiment tracking and model registry
- ``streaming_core`` - Real-time file-stream → Parquet pipeline
- ``hybrid`` - A batch stage that feeds a streaming stage

**Template options:**

- ``--template NAME`` - Template to use (e.g., ``medallion_basic``)
- ``--project-name NAME`` - Name for the generated project
- ``--output-path PATH`` - Where to create the project (default: current directory)
- ``--format TYPE`` - Config format for generated files: ``toml`` (default), ``yaml``, or ``json``
- ``--list-templates`` - Show all available templates
- ``--no-sample-code`` - Generate project structure without sample code
- ``--sandbox-developers NAME [NAME ...]`` - Create per-developer sandbox environments

**Examples:**

.. code-block:: bash

   # List all available templates
   ducta template --list-templates

   # Generate project with TOML config (default)
   ducta template --template medallion_basic --project-name my_etl

   # Generate project with YAML config
   ducta template --template medallion_basic --project-name my_etl --format yaml

   # Generate project with developer sandboxes
   ducta template --template medallion_basic --project-name my_etl \
     --sandbox-developers alice bob charlie

The ``ducta config`` Command
----------------------------

View your loaded configuration and discover pipelines:

.. code-block:: bash

   ducta config list-pipelines             # Show all pipelines
   ducta config list-configs               # Show discovered config files
   ducta config pipeline-info --pipeline ETL # Show details of one pipeline
   ducta config validate                   # Preflight-validate config (no Spark)
   ducta config clear-cache                # Clear discovery cache

**Options for ``list-pipelines``:**

- ``--env ENVIRONMENT`` - Filter by environment
- ``--filter PATTERN`` - Substring filter for pipeline names
- ``--format {table,json,list}`` - Output format (default: table)

**``config validate``** imports every node function, checks its signature, and
resolves all input/output keys *without* starting Spark — so it reports every
configuration error up front. Validate one pipeline with ``--pipeline NAME`` or
all of them by default.

Streaming (Real-time pipelines)
-------------------------------

Manage continuous data stream pipelines with the ``stream`` subcommand:

.. code-block:: bash

   # Start a streaming pipeline
   ducta stream run --config config/pipelines.toml --pipeline my_stream

**Options for ``stream run``:**

- ``--config, -c PATH`` - Path to the streaming configuration file - **required**
- ``--pipeline, -p NAME`` - Name of the pipeline to execute - **required**
- ``--mode, -m {sync,async}`` - Execution mode (default: async)
- ``--model-version VERSION`` - Optional model version for ML streaming
- ``--hyperparams JSON`` - Hyperparameters as a JSON string
- ``--transforms-module MODULE [MODULE ...]`` - Python module(s) to import before starting the pipeline; each must expose a ``register_transforms(registry)`` function

**Status and Stop:**

.. code-block:: bash

   # Check status of active streams
   ducta stream status --config config/pipelines.toml --format table

   # Stop a specific execution
   ducta stream stop --config config/pipelines.toml --execution-id <ID> --timeout 60

Data Quality (``ducta quality``)
--------------------------------

Run and manage data quality checks independently or as part of a pipeline.

.. code-block:: bash

   # List all available check types
   ducta quality list

   # Run checks on a data file
   ducta quality run --input data.parquet --config quality_config.toml

   # View quality reports for a dataset (--workspace defaults to current directory)
   ducta quality report --dataset sales_data --workspace .

   # View quality trends (time-series)
   ducta quality trend --dataset sales_data --workspace .

   # Show composite quality score for a specific run
   ducta quality score --run-id <RUN_ID> --workspace .

   # Validate a node's quality config without executing the pipeline
   ducta quality validate-config --node extract --config config/nodes.toml

MLOps (``ducta experiment`` & ``ducta model``)
----------------------------------------------

Track experiments and manage your model registry.

.. code-block:: bash

   # List recent experiments
   ducta experiment list

   # Promote a model to staging/production
   ducta model promote xgboost_v1 1.2.0 production

   # Clean up old model versions (Garbage Collection)
   ducta model gc --dry-run

Visual Interface & Server
-------------------------

Launch the Ducta dashboard to visualize your pipelines and execution history.

.. code-block:: bash

   # Launch the full UI (FastAPI backend + React frontend)
   ducta ui --port 8000

   # Start the local server only
   ducta server start

**UI Options** (``ducta ui``):

- ``--port PORT`` - Port to run on (default: 8000)
- ``--host HOST`` - Host to bind to (default: 127.0.0.1)
- ``--no-browser`` - Don't open the browser automatically
- ``--source PATH_OR_URL`` - Workspace source path or Git URL to load automatically
- ``--db PATH`` - Custom path for the SQLite execution history database (default: ``~/.ducta/executions.db``)
- ``--enable-terminal`` - Enable the embedded web terminal (PTY). **Security note:** grants arbitrary shell execution to authenticated users; off by default.

**Server Options** (``ducta server start``):

- ``--port PORT`` - Port to run on (default: 8000)
- ``--host HOST`` - Host to bind to (default: 127.0.0.1)
- ``--no-browser`` - Don't open the browser automatically
- ``--source PATH_OR_URL`` - Workspace source path or Git URL to load automatically
- ``--db PATH`` - Custom path for the SQLite execution history database (default: ``~/.ducta/executions.db``)

Database Connections (``ducta init ingestion``)
-----------------------------------------------

Configure and test database connections used by ingestion pipelines.

.. code-block:: bash

   # Interactive wizard to set up a new connection
   ducta init ingestion setup

   # List configured connections
   ducta init ingestion list

   # Test connectivity for a named connection
   ducta init ingestion test --source my_postgres

   # Show a connection's details
   ducta init ingestion info --source my_postgres

Run Certificates (``ducta certify``)
------------------------------------

Every terminating run writes a self-hashed **Run Certificate** to
``.ducta/runs/<env>/<run_id>/certificate.json``, recording inputs, outputs, config,
and quality-gate outcomes. Use ``certify`` to inspect and verify them.

.. code-block:: bash

   # List all run certificates
   ducta certify list

   # Print one certificate as JSON (run id or a unique prefix)
   ducta certify show --run-id <RUN_ID>

   # Verify a certificate has not been tampered with
   ducta certify verify --run-id <RUN_ID>

   # Verify AND re-run the pipeline to prove every output reproduces
   ducta certify verify --run-id <RUN_ID> --reproduce \
     --start-date 2024-01-01 --end-date 2024-01-31

Help & Documentation
--------------------

**Get help for any command:**

.. code-block:: bash

   ducta --help              # Show all commands
   ducta start --help        # Help for 'start' command
   ducta stream --help       # Help for 'stream' command
   ducta template --help     # Help for 'template' command
   ducta config --help       # Help for 'config' command

**Check your Ducta version:**

.. code-block:: bash

   ducta --version

Next Steps
----------

- See :doc:`configuration` for detailed configuration options
- Learn about :doc:`best_practices` for production use
- Follow a tutorial: :doc:`tutorials/batch_etl` or :doc:`tutorials/streaming`
