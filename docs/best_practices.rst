Best Practices
==============

Learn how to use Ducta effectively and build reliable data pipelines.

Project Organization
---------------------

**Keep your project clean and organized.** A good structure makes collaboration easier and reduces errors:

.. code-block:: text

   my_project/
   ├── config/              # Configuration files
   │   ├── global_settings.yaml
   │   ├── pipelines.yaml
   │   ├── nodes.yaml
   │   ├── inputs.yaml
   │   ├── outputs.yaml
   │   ├── dev/             # Dev overrides
   │   ├── staging/         # Staging overrides
   │   └── prod/            # Production overrides
   │
   ├── src/                 # Your Python code
   │   └── nodes/
   │       ├── __init__.py
   │       ├── extract.py
   │       ├── transform.py
   │       └── load.py
   │
   ├── tests/               # Unit tests
   │   ├── test_extract.py
   │   ├── test_transform.py
   │   └── test_load.py
   │
   ├── data/                # Local test data (add to .gitignore)
   │   ├── input/
   │   └── output/
   │
   ├── logs/                # Execution logs (add to .gitignore)
   │
   ├── .env                 # Secrets (add to .gitignore!)
   ├── .gitignore
   ├── requirements.txt
   ├── README.md
   └── Makefile             # Optional: helpful shortcuts

Writing Good Node Functions
-----------------------------

**Specifying Node Function Paths**

Each node needs **two separate keys**: ``module`` (the dotted Python module
path) and ``function`` (the bare function name inside that module). At
execution time Ducta imports ``module`` and looks up ``function`` on it — a
single dotted string is not split apart automatically, so both keys are
required:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         [extract_sales]
         module = "src.nodes.extract"
         function = "get_sales"

         [extract_customers]
         module = "src.nodes.extract"
         function = "get_customers"

   .. tab-item:: YAML

      .. code-block:: yaml

         extract_sales:
           module: "src.nodes.extract"
           function: "get_sales"
         extract_customers:
           module: "src.nodes.extract"
           function: "get_customers"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "extract_sales": { "module": "src.nodes.extract", "function": "get_sales" },
           "extract_customers": { "module": "src.nodes.extract", "function": "get_customers" }
         }

**What happens if ``module`` is omitted:** config validation only does a
syntactic check — it requires ``function`` to contain a dot (e.g.
``"src.nodes.extract.get_sales"``) if ``module`` is absent, to catch obvious
typos early. That dotted string is **not** parsed into a module+function pair
at execution time, however: the executor will raise
``"Node configuration ... must include 'module' and 'function'"`` if
``module`` is missing. Always set ``module`` explicitly.

**Best practice:** Keep ``module`` and ``function`` both explicit for every
node — this is required, not optional, and makes node wiring unambiguous in
shared projects:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         [extract_sales]
         module = "src.nodes.extract"
         function = "get_sales"

         [clean_data]
         module = "src.nodes.transform"
         function = "clean"

   .. tab-item:: YAML

      .. code-block:: yaml

         extract_sales:
           module: "src.nodes.extract"
           function: "get_sales"
         clean_data:
           module: "src.nodes.transform"
           function: "clean"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "extract_sales": { "module": "src.nodes.extract", "function": "get_sales" },
           "clean_data": { "module": "src.nodes.transform", "function": "clean" }
         }

**Simple and Clear**

Each node function should do one thing well:

.. code-block:: python

   # ✓ Good: Simple, clear purpose
   def extract_sales_data(df):
       """Load sales data from database."""
       return df.dropna()

   # ✗ Bad: Does too much
   def do_everything(df):
       """Process all data."""
       df = df.dropna()
       df = df.groupby(...).sum()
       df = df[df['amount'] > 0]
       return df

**Always Include Docstrings**

Write a one-line description of what the function does:

.. code-block:: python

   def clean_customer_data(df):
       """Remove duplicate customers and invalid emails."""
       df = df.drop_duplicates(subset=['customer_id'])
       df = df[df['email'].str.contains('@')]
       return df

**Handle Errors Gracefully**

Don't let silent failures happen:

.. code-block:: python

   # ✗ Bad: Ignores errors
   def transform_data(df):
       try:
           return df['amount'].apply(float)
       except:
           pass  # Oops, lost data

   # ✓ Good: Handles errors properly
   def transform_data(df):
       """Convert amounts to numbers."""
       try:
           return df['amount'].astype(float)
       except ValueError as e:
           raise ValueError(f"Could not convert amounts: {e}")

**Validate Your Input**

Don't assume data is correct:

.. code-block:: python

   # ✓ Good: Validates data
   def process_sales(df):
       """Process sales data."""
       if df is None or df.empty:
           raise ValueError("No data provided")

       required_cols = ['id', 'amount', 'date']
       missing = [c for c in required_cols if c not in df.columns]
       if missing:
           raise ValueError(f"Missing columns: {missing}")

       return df[df['amount'] > 0]

Configuration Best Practices
------------------------------

**Use Environment Variables, Never Hardcode Secrets**

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # ✓ Always do this
         [database]
         password = "${DB_PASSWORD}"

   .. tab-item:: YAML

      .. code-block:: yaml

         # ✓ Always do this
         database:
           password: ${DB_PASSWORD}

   .. tab-item:: JSON

      .. code-block:: json

         {
           "database": {
             "password": "${DB_PASSWORD}"
           }
         }

Then set the variable:

.. code-block:: bash

   export DB_PASSWORD="my_secret_password"
   ducta start --env prod --pipeline my_pipeline

Or use a ``.env`` file:

.. code-block:: bash

   # .env (add to .gitignore)
   DB_PASSWORD=my_secret_password
   API_KEY=abc123

**Use Relative Paths or Cloud Storage**

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # ✓ Use relative paths
         input_path = "data/input"

         # ✓ Or use cloud storage
         s3_path = "s3://my-bucket/data/input"

   .. tab-item:: YAML

      .. code-block:: yaml

         # ✓ Use relative paths
         input_path: data/input

         # ✓ Or use cloud storage
         s3_path: s3://my-bucket/data/input

   .. tab-item:: JSON

      .. code-block:: json

         {
           "input_path": "data/input",
           "s3_path": "s3://my-bucket/data/input"
         }

**Name Nodes Clearly**

Use short, descriptive names:

.. code-block:: toml

   # ✗ Unclear
   [n1]
   module = "src.nodes.a"
   function = "run"

   [n2]
   module = "src.nodes.b"
   function = "run"

   # ✓ Clear
   [extract_customers]
   module = "src.nodes.extract"
   function = "get_customers"

   [clean_emails]
   module = "src.nodes.clean"
   function = "normalize_emails"

**Organize Pipelines by Layer**

Follow medallion architecture:

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         [bronze_load_raw_sales]
         nodes = ["ingest_sales"]

         [silver_clean_sales]
         nodes = ["deduplicate", "validate"]

         [gold_sales_metrics]
         nodes = ["aggregate", "calculate_kpis"]

   .. tab-item:: YAML

      .. code-block:: yaml

         bronze_load_raw_sales:
           nodes: [ingest_sales]
         silver_clean_sales:
           nodes: [deduplicate, validate]
         gold_sales_metrics:
           nodes: [aggregate, calculate_kpis]

   .. tab-item:: JSON

      .. code-block:: json

         {
           "bronze_load_raw_sales": { "nodes": ["ingest_sales"] },
           "silver_clean_sales": { "nodes": ["deduplicate", "validate"] },
           "gold_sales_metrics": { "nodes": ["aggregate", "calculate_kpis"] }
         }

Deployment Checklist
---------------------

Before running in production, verify:

✅ **Configuration**

.. code-block:: bash

   # Validate config before running
   ducta start --env prod --pipeline my_pipeline --validate-only

✅ **Test the Pipeline Locally First**

.. code-block:: bash

   # Run on dev with small data
   ducta start --env dev --pipeline my_pipeline

✅ **Check for Secrets**

.. code-block:: bash

   # Make sure no passwords in code
   grep -r "password" config/
   grep -r "api_key" src/

   # Should return nothing!

✅ **Add Logging**

.. code-block:: bash

   # Run with debug logging
   ducta start --env prod --pipeline my_pipeline --log-level DEBUG

✅ **Set Up Monitoring**

Plan for what to do if something fails:

.. code-block:: bash

   # Save logs for debugging
   ducta start --env prod --pipeline my_pipeline 2>&1 | tee logs/pipeline.log

✅ **Document Your Pipeline**

Add a README explaining:
   - What the pipeline does
   - When it runs
   - What data it needs
   - What it produces

.. code-block:: markdown

   # Sales ETL Pipeline

   ## Purpose
   Daily sales data transformation

   ## Schedule
   Runs at 9 AM every weekday

   ## Inputs
   - Raw sales database
   - Customer master data

   ## Outputs
   - Processed sales data in S3

   ## Troubleshooting
   If the pipeline fails:
   1. Check database connection
   2. Verify S3 permissions
   3. See logs/ directory

Error Handling Strategy
-----------------------

**Plan for Failures**

Data pipelines fail. Plan for it:

.. code-block:: toml

   [critical_transform]
   module = "src.nodes.transform"
   function = "run"
   timeout = 600
   retry = 3  # Number of retry attempts (0-10)

   [non_critical]
   module = "src.nodes.aggregate"
   function = "run"
   timeout = 300
   retry = 0

**Log Everything**

.. code-block:: python

   import logging

   logger = logging.getLogger(__name__)

   def extract_data():
       """Extract with logging."""
       logger.info("Starting extraction...")

       df = read_data()
       logger.info(f"Extracted {len(df)} records")

       return df

**Monitor Results**

Check that output looks right:

.. code-block:: python

   def load_data(df):
       """Load with validation."""
       if df.empty:
           raise ValueError("No data to load")

       # Log some statistics
       logger.info(f"Saving {len(df)} records")
       logger.info(f"Columns: {', '.join(df.columns)}")

       df.to_parquet('output.parquet')

Testing Strategy
-----------------

**Write Unit Tests**

Test each node function:

.. code-block:: python

   # test_extract.py
   import pandas as pd
   from src.nodes.extract import extract_data

   def test_extract_data():
       """Test extraction."""
       df = extract_data()

       assert not df.empty
       assert 'id' in df.columns
       assert len(df) > 0

   def test_handles_missing_file():
       """Test error handling."""
       with pytest.raises(FileNotFoundError):
           extract_data(path="nonexistent.csv")

**Run Tests Before Deploying**

.. code-block:: bash

   # Run all tests
   pytest tests/

   # Run with coverage
   pytest --cov=src tests/

Feature Store Best Practices
----------------------------

1. **Point-in-Time Correctness**: When creating features for machine learning, always include a timestamp column (e.g., ``event_timestamp``). This allows Ducta to perform temporal joins, preventing data leakage by ensuring that only features available at the record's event time are used for training.

2. **Decouple Computation from Storage**: Register your feature groups using the ``write_features`` method rather than writing files directly to storage. This allows you to switch between storage backends (Delta, SQL, Parquet) via configuration without changing your Python code.

3. **Tiered Serving**: Use an online store for low-latency serving and Parquet/Delta for offline training. Ducta's ``FeatureStoreConfig(sync_to_online=True, ...)`` keeps both stores in sync (configured where the feature store is constructed, not via a global TOML key).

**Test with Real Data (Locally)**

.. code-block:: bash

   # Test with actual data structure
   ducta start --env dev --pipeline my_pipeline

Common Mistakes to Avoid
------------------------

❌ **Mistake: Assuming data is clean**

.. code-block:: python

   # ✗ Don't assume
   def bad_transform(df):
       return df['amount'].apply(float)  # Crashes if invalid values

   # ✓ Validate first
   def good_transform(df):
       df = df[df['amount'].notna()]
       return df['amount'].astype(float)

❌ **Mistake: Hardcoding values**

.. code-block:: python

   # ✗ Don't hardcode
   def bad_extract():
       return pd.read_csv("/home/john/data.csv")

   # ✓ Use configuration
   def good_extract(input_data):
       return pd.read_csv(input_data['path'])

❌ **Mistake: Ignoring errors**

.. code-block:: python

   # ✗ Don't ignore
   try:
       process_data()
   except:
       pass

   # ✓ Handle properly
   try:
       process_data()
   except ValueError as e:
       logger.error(f"Processing failed: {e}")
       raise

❌ **Mistake: Large data in memory**

.. code-block:: python

   # ✗ Don't load everything
   df = pd.read_csv("huge_file.csv")  # Crashes on large files

   # ✓ Process in chunks
   for chunk in pd.read_csv("huge_file.csv", chunksize=10000):
       process_chunk(chunk)

Performance Tips
-----------------

**Use Parquet for Large Files**

.. code-block:: toml

   # ✗ CSV is slow
   format = "csv"

   # ✓ Parquet is fast
   format = "parquet"

**Partition Your Data**

.. code-block:: toml

   # config/outputs.toml
   [results]
   filepath = "data/output/results"
   format = "parquet"
   partition_columns = ["date"]  # Stores by date folder

**Run Nodes in Parallel**

.. code-block:: toml

   # config/global_settings.toml
   # Ducta automatically runs independent nodes in parallel
   # Configure how many:
   max_parallel_nodes = 8  # Default is 4 (range 1-128)

**Use Date Ranges Wisely**

.. code-block:: bash

   # Process only what changed
   ducta start --env prod --pipeline daily_etl \
     --start-date 2024-01-15 \
     --end-date 2024-01-15

Operationalizing Pipelines
----------------------------

**Schedule with Cron (Linux/Mac)**

.. code-block:: bash

   # Run at 9 AM every weekday
   0 9 * * 1-5 cd /home/user/project && ducta start --env prod --pipeline daily_etl

**Schedule with Windows Task Scheduler**

Create a batch file:

.. code-block:: batch

   REM run_pipeline.bat
   cd C:\Users\user\project
   ducta start --env prod --pipeline daily_etl

Then schedule it in Task Scheduler.

**Monitor Execution**

Save logs and monitor them:

.. code-block:: bash

   # Run with logging
   ducta start --env prod --pipeline my_pipeline \
     >> logs/execution.log 2>&1

   # Check for errors
   grep ERROR logs/execution.log

**Set Alerts**

Get notified if pipeline fails:

.. code-block:: bash

   # Example with email
   ducta start --env prod --pipeline my_pipeline || \
     mail -s "Pipeline failed" admin@company.com

Security Best Practices
------------------------

**Never Commit Secrets**

.. code-block:: bash

   # .gitignore
   .env
   logs/
   data/
   *.log

**Use Principle of Least Privilege**

Give users/services only the permissions they need:

.. code-block:: bash

   # Don't give admin access
   # Only give read/write to specific paths and tables

**Validate All Inputs**

.. code-block:: python

   # Validate file paths
   import os
   path = user_input
   if not os.path.exists(path):
       raise ValueError(f"File not found: {path}")

**Rotate Credentials Regularly**

Change passwords and API keys monthly.

Conclusion
----------

Remember:

✅ Keep things simple
✅ Test everything
✅ Handle errors gracefully
✅ Never hardcode secrets
✅ Document your work
✅ Monitor in production
✅ Learn from failures

Next Steps
----------

* :doc:`tutorials/batch_etl` - Build a complete example
* :doc:`configuration` - Deep dive into configuration

Optimize Spark Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   # config/global_settings.toml
   [spark_config]
   "spark.sql.adaptive.enabled" = true
   "spark.sql.adaptive.coalescePartitions.enabled" = true

   # Optimize shuffle
   "spark.sql.shuffle.partitions" = 200
   "spark.sql.autoBroadcastJoinThreshold" = 10485760  # 10MB

   # Memory tuning
   "spark.memory.fraction" = 0.8
   "spark.memory.storageFraction" = 0.3

Partition Data Effectively
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   # config/outputs.toml
   [results]
   partition_columns = ["year", "month", "day"]
   # Creates: /data/year=2024/month=01/day=15/

   # ✅ Good: 1000-10000 partitions
   # ❌ Bad: Too many (>50000) or too few (<10)

Development
-----------

Use Version Control
~~~~~~~~~~~~~~~~~~~

Track all code and configuration:

.. code-block:: bash

   git add config/ pipelines/ notebooks/
   git commit -m "Update pipeline configuration"
   git push

Separate Environments
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   ├── config/
   │   ├── base/     # Shared configuration
   │   ├── dev/      # Development overrides
   │   ├── staging/  # Staging overrides
   │   └── prod/     # Production overrides

Always Test in Dev First
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # 1. Test in dev
   ducta start --env dev --pipeline new_pipeline --validate-only
   ducta start --env dev --pipeline new_pipeline

   # 2. Test in staging
   ducta start --env staging --pipeline new_pipeline

   # 3. Deploy to production
   ducta start --env prod --pipeline new_pipeline

Write Unit Tests
~~~~~~~~~~~~~~~~

``ContextLoader.load_from_paths`` takes a dict of explicit config file paths
(not an environment name alone), and ``PipelineExecutor.run_pipeline``
returns ``None`` on success / raises on failure — there is no
``result.success`` or ``result.nodes_executed``. Assert behavior either by
expecting no exception, or by inspecting the actual output your nodes wrote:

.. code-block:: python

   import pytest
   from ducta import PipelineExecutor, ContextLoader

   CONFIG_PATHS = {
       "global_settings_path": "config/global_settings.yaml",
       "pipelines_config_path": "config/pipelines.yaml",
       "nodes_config_path": "config/nodes.yaml",
       "input_config_path": "config/inputs.yaml",
       "output_config_path": "config/outputs.yaml",
   }

   @pytest.fixture
   def test_executor():
       context = ContextLoader().load_from_paths(CONFIG_PATHS, env="test")
       return PipelineExecutor(context)

   def test_bronze_ingestion(test_executor):
       # Raises on failure; reaching this line means the pipeline succeeded
       test_executor.run_pipeline(
           "bronze_ingestion", start_date="2024-01-01", end_date="2024-01-01"
       )

   def test_data_quality(test_executor):
       with pytest.raises(Exception):
           # e.g. a node with data_quality.fail_fast = true on bad input data
           test_executor.run_pipeline(
               "quality_checks", start_date="2024-01-01", end_date="2024-01-01"
           )

Use Linting and Formatting
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Install pre-commit hooks
   pip install pre-commit
   pre-commit install

   # Format code
   black src/
   isort src/

   # Lint code
   flake8 src/
   pylint src/

Production
----------

Enable Monitoring
~~~~~~~~~~~~~~~~~

Ducta does not ship a built-in monitoring/alerting config block. Set the log
level through ``global_settings`` and wire metrics/log shipping with your own
infrastructure (the ``monitoring`` extra installs ``prometheus-client``, but
you instrument it yourself):

.. code-block:: toml

   # config/global_settings.toml
   log_level = "WARNING"

.. code-block:: bash

   # Ship logs to a file/syslog with standard shell redirection or your
   # process manager (systemd, supervisord, etc.) — not a Ducta feature
   ducta start --env prod --pipeline my_pipeline --log-file /var/log/ducta/pipeline.log

Set Up Alerts
~~~~~~~~~~~~~

There is no built-in alerting system. Check the process exit code and notify
externally, the same pattern shown earlier in this guide:

.. code-block:: bash

   ducta start --env prod --pipeline my_pipeline || \
     mail -s "Pipeline failed" admin@company.com

Configure Retry Policies
~~~~~~~~~~~~~~~~~~~~~~~~~

Retries are configured per node with a simple integer count (0-10); Ducta
applies exponential backoff internally:

.. code-block:: toml

   # config/nodes.toml
   [extract]
   module = "src.nodes.extract"
   function = "run"
   retry = 3

   [transform]
   module = "src.nodes.transform"
   function = "run"
   retry = 3

   [load]
   module = "src.nodes.load"
   function = "run"
   retry = 3

Set Resource Limits
~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   # config/global_settings.toml
   max_parallel_nodes = 16        # 1-128, default 4
   execution_timeout_seconds = 7200  # 60-86400, default 3600

Logging
-------

Structured Logging
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import logging
   import json

   logger = logging.getLogger(__name__)

   # Structured log entry
   logger.info(json.dumps({
       "event": "pipeline_started",
       "pipeline": "sales_etl",
       "environment": "production",
       "start_date": "2024-01-01",
       "end_date": "2024-01-31"
   }))

Log Levels
~~~~~~~~~~

Use appropriate log levels:

.. code-block:: python

   # DEBUG: Detailed diagnostic information
   logger.debug(f"Processing record: {record_id}")

   # INFO: General informational messages
   logger.info(f"Pipeline started: {pipeline_name}")

   # WARNING: Warning messages
   logger.warning(f"Skipping invalid record: {record_id}")

   # ERROR: Error messages
   logger.error(f"Failed to load data: {error}")

   # CRITICAL: Critical errors
   logger.critical(f"Database connection lost")

Include Context
~~~~~~~~~~~~~~~

``run_pipeline`` does not return a results object with execution metrics —
batch/ML pipelines return ``None`` on success and raise on failure. Log
context from inside your own node functions instead:

.. code-block:: python

   import time

   def load_data(df):
       """Load with contextual logging."""
       start = time.time()
       df.to_parquet("output.parquet")
       logger.info(
           f"Node completed: load_data",
           extra={
               "records_processed": len(df),
               "execution_time": time.time() - start,
           }
       )

Error Handling
--------------

Graceful Degradation
~~~~~~~~~~~~~~~~~~~~

``PipelineExecutor.run_pipeline`` returns ``None`` for batch/ML pipelines on
success and raises an exception on failure — there is no ``result.success``
flag to check. Catch the exception instead:

.. code-block:: python

   from ducta import PipelineExecutor, ContextLoader

   context = ContextLoader().load_from_paths(config_paths, env="prod")
   executor = PipelineExecutor(context)

   try:
       executor.run_pipeline("pipeline", start_date="2024-01-01", end_date="2024-01-01")
   except Exception as primary_error:
       logger.warning(f"Primary pipeline failed: {primary_error}, trying backup")
       try:
           executor.run_pipeline("backup_pipeline", start_date="2024-01-01", end_date="2024-01-01")
       except Exception as backup_error:
           logger.error(f"Both pipelines failed: {backup_error}")
           # Notify ops team
           send_alert("Pipeline failure", str(backup_error))

Detailed Error Messages
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import traceback

   try:
       executor.run_pipeline("pipeline", start_date="2024-01-01", end_date="2024-01-01")
   except Exception as e:
       logger.error(
           f"Pipeline failed: {e}\n"
           f"Traceback: {traceback.format_exc()}"
       )
       raise

Recovery Mechanisms
~~~~~~~~~~~~~~~~~~~

There is no generic pipeline-level checkpointing parameter. For
**streaming** pipelines, set ``checkpoint_location`` on the node's streaming
config so the query can resume from its last committed offset on restart:

.. code-block:: yaml

   # config/nodes.yaml
   stream_ingest:
     streaming:
       checkpoint_location: "/tmp/checkpoints/stream_ingest"

For batch pipelines, make nodes idempotent (e.g. ``write_mode: overwrite``
partitioned by date) so a re-run for the same ``--start-date``/``--end-date``
safely replaces partial output.

Data Quality
------------

Ducta's quality framework is configured per-node (``sanity_checks`` for
pre-execution structural checks, ``data_quality`` for post-execution
statistical checks) — there is no standalone ``DataQualityChecker`` class or
``[[validation.schema]]``/``data_contract`` TOML block. See
:doc:`quality` for the full reference.

Validate Schemas (Sanity Phase)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pre-execution structural checks on node inputs; with ``fail_fast = true`` the
node function is never called if a check fails:

.. code-block:: toml

   # config/nodes.toml
   [load_data.sanity_checks]
   enabled = true
   fail_fast = true
   checks.schema = { expected_columns = ["customer_id", "amount"] }
   checks.empty_dataset = {}

Check Data Quality (Validation Phase)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Post-execution statistical checks on node outputs:

.. code-block:: toml

   # config/nodes.toml
   [transform_data.data_quality]
   enabled = true
   checks.null_rate = { columns = ["customer_id", "amount"], threshold = 0.01 }
   checks.duplicates = { columns = ["transaction_id"] }
   checks.range = { column = "amount", min = 0, max = 1000000 }

Quality Gates
~~~~~~~~~~~~~

Use weighted check scoring to automatically block a pipeline when data
quality drops below a threshold — see :doc:`quality` for the
``QualityGateEvaluator`` configuration and the full list of 16 built-in
checks (schema, null rate, duplicates, drift detection, schema drift, and
more).

Documentation
-------------

Document Pipelines
~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   # config/pipelines.toml
   [customer_360]
   description = """
   Creates a 360-degree view of customers by combining:
   - Transaction data from sales system
   - Profile data from CRM
   - Interaction data from support tickets
   """
   nodes = ["merge_sales", "merge_crm", "merge_support"]

   # Ownership/SLA/schedule are not interpreted by Ducta (no built-in
   # scheduler or alerting). Track them in your own governance doc/ticket
   # system, and trigger runs with an external scheduler such as cron
   # or Airflow (see "Operationalizing Pipelines" above).

Document Nodes
~~~~~~~~~~~~~~

.. code-block:: python

   def transform_sales_data(df):
       """
       Transform raw sales data for analysis.

       Args:
           df: Raw sales DataFrame with columns:
               - transaction_id (str)
               - customer_id (str)
               - amount (decimal)
               - date (date)

       Returns:
           Transformed DataFrame with additional columns:
               - year (int)
               - month (int)
               - quarter (int)

       Raises:
           ValueError: If required columns are missing
       """
       # Implementation
       pass

Maintain Changelog
~~~~~~~~~~~~~~~~~~

.. code-block:: text

   ## [1.2.0] - 2024-01-15

   ### Added
   - New customer_360 pipeline
   - Data quality checks for bronze layer

   ### Changed
   - Improved performance of silver transformation
   - Updated Spark configuration for production

   ### Fixed
   - Fixed null handling in gold aggregation

Checklist
---------

Before Production Deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- [ ] All tests passing
- [ ] Configuration validated
- [ ] Documentation updated
- [ ] Monitoring configured
- [ ] Alerts set up
- [ ] Resource limits defined
- [ ] Retry policies configured
- [ ] Data quality checks in place
- [ ] Security review completed
- [ ] Performance tested
- [ ] Backup strategy defined
- [ ] Rollback plan documented

Next Steps
----------

* :doc:`getting_started`
* :doc:`installation`
* :doc:`configuration`
