Batch ETL Tutorial
==================

This tutorial teaches you to build a complete batch ETL pipeline using the Medallion architecture.

What You'll Build
-----------------

A production-ready ETL pipeline that:

- Ingests raw sales data (Bronze layer)
- Cleans and validates data (Silver layer)
- Calculates business metrics (Gold layer)
- Can be scheduled to run daily via an external orchestrator (e.g. Airflow or cron)

Prerequisites
-------------

- Ducta installed: ``pip install ducta[spark]``
- Sample data (provided)
- 30 minutes

Step 1: Project Setup
----------------------

Create a new project using the recommended medallion template:

.. code-block:: bash

   ducta template --template medallion_basic --project-name sales_etl
   cd sales_etl

This creates the following structure:

.. code-block:: text

   sales_etl/
   ├── environment.toml       # Maps environments to config files
   ├── config/                # Shared (base) configuration
   │   ├── global_settings.toml
   │   ├── pipelines.toml
   │   ├── nodes.toml
   │   ├── input.toml
   │   ├── output.toml
   │   └── dev/               # Environment-specific overrides
   ├── pipelines/             # Python logic
   │   └── etl.py
   ├── data/
   └── requirements.txt

Step 2: Configure Data Sources
-------------------------------

Define where your raw data is coming from in ``config/input.toml``. Ducta supports multiple formats.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/input.toml
         [source_data]
         format = "csv"
         filepath = "data/raw/sales/*.csv"
         options = { header = true, inferSchema = true, dateFormat = "yyyy-MM-dd" }

         [[source_data.schema]]
         name = "transaction_id"
         type = "string"

         [[source_data.schema]]
         name = "date"
         type = "date"

         [[source_data.schema]]
         name = "amount"
         type = "decimal(10,2)"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/input.yaml
         source_data:
           format: csv
           filepath: "data/raw/sales/*.csv"
           options:
             header: true
             inferSchema: true
             dateFormat: "yyyy-MM-dd"
           schema:
             - name: transaction_id
               type: string
             - name: date
               type: date
             - name: amount
               type: "decimal(10,2)"

   .. tab-item:: JSON

      .. code-block:: json

         {
           "source_data": {
             "format": "csv",
             "filepath": "data/raw/sales/*.csv",
             "options": {
               "header": true,
               "inferSchema": true,
               "dateFormat": "yyyy-MM-dd"
             },
             "schema": [
               { "name": "transaction_id", "type": "string" },
               { "name": "date", "type": "date" },
               { "name": "amount", "type": "decimal(10,2)" }
             ]
           }
         }

Step 3: Configure Output
-------------------------

Define your output targets in ``config/output.toml``. We'll use the Medallion architecture (Bronze → Silver → Gold).

.. note::

   Output partitioning is passed through the format-specific ``options`` dict
   (e.g. Spark's ``partitionBy``), not a dedicated ``partition_by`` key.
   Merge logic for upserts should be implemented in your transformation
   code (e.g. a Delta ``MERGE`` statement), not declared as a config key —
   Ducta's output schema does not have a ``merge_condition`` field.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/output.toml

         # Bronze layer - raw data as-is
         [raw_data]
         format = "parquet"
         filepath = "data/bronze/sales"
         write_mode = "append"
         options = { partitionBy = ["year", "month", "day"] }

         # Silver layer - cleaned data
         [silver_sales]
         format = "delta"
         filepath = "data/silver/sales"
         write_mode = "append"

         # Gold layer - business metrics
         [final_output]
         format = "delta"
         filepath = "data/gold/daily_sales"
         write_mode = "overwrite"

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/output.yaml

         # Bronze layer
         raw_data:
           format: parquet
           filepath: data/bronze/sales
           write_mode: append
           options:
             partitionBy: [year, month, day]

         # Silver layer
         silver_sales:
           format: delta
           filepath: data/silver/sales
           write_mode: append

         # Gold layer
         final_output:
           format: delta
           filepath: data/gold/daily_sales
           write_mode: overwrite

   .. tab-item:: JSON

      .. code-block:: json

         {
           "raw_data": {
             "format": "parquet",
             "filepath": "data/bronze/sales",
             "write_mode": "append",
             "options": { "partitionBy": ["year", "month", "day"] }
           },
           "silver_sales": {
             "format": "delta",
             "filepath": "data/silver/sales",
             "write_mode": "append"
           },
           "final_output": {
             "format": "delta",
             "filepath": "data/gold/daily_sales",
             "write_mode": "overwrite"
           }
         }

Step 4: Define Pipeline Nodes
------------------------------

Define your process nodes in ``config/nodes.toml``. Each node maps a name to a Python function:

.. tab-set::

   .. tab-item:: TOML (Recommended)

      .. code-block:: toml

         # config/nodes.toml — the key IS the node name (flat, no wrapper)

         # Bronze: Load raw data
         [load_raw_sales]
         function = "src.pipelines.bronze.load_raw_sales"
         description = "Ingest raw sales CSV files into the Bronze layer"
         timeout = 600
         retry = 2

         # Silver: Clean and validate
         [clean_sales]
         function = "transformations.clean_sales_data"
         description = "Remove nulls, duplicates, and invalid amounts"
         timeout = 1200
         retry = 3

         # Silver: Enrich with customer data
         [enrich_sales]
         function = "transformations.enrich_with_customers"
         description = "Join sales data with customer master"
         timeout = 1200

         # Gold: Calculate daily business metrics
         [calculate_daily_metrics]
         function = "transformations.calculate_daily_metrics"
         description = "Aggregate sales by day, region, and segment"
         timeout = 1800

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         load_raw_sales:
           function: "src.pipelines.bronze.load_raw_sales"
           description: "Ingest raw sales CSV files into the Bronze layer"
           timeout: 600
           retry: 2

         clean_sales:
           function: "transformations.clean_sales_data"
           description: "Remove nulls, duplicates, and invalid amounts"
           timeout: 1200
           retry: 3

         enrich_sales:
           function: "transformations.enrich_with_customers"
           description: "Join sales data with customer master"
           timeout: 1200

         calculate_daily_metrics:
           function: "transformations.calculate_daily_metrics"
           description: "Aggregate sales by day, region, and segment"
           timeout: 1800

   .. tab-item:: JSON

      .. code-block:: json

         {
           "load_raw_sales": {
             "function": "src.pipelines.bronze.load_raw_sales",
             "description": "Ingest raw sales CSV files into the Bronze layer",
             "timeout": 600,
             "retry": 2
           },
           "clean_sales": {
             "function": "transformations.clean_sales_data",
             "description": "Remove nulls, duplicates, and invalid amounts",
             "timeout": 1200,
             "retry": 3
           },
           "enrich_sales": {
             "function": "transformations.enrich_with_customers",
             "description": "Join sales data with customer master",
             "timeout": 1200
           },
           "calculate_daily_metrics": {
             "function": "transformations.calculate_daily_metrics",
             "description": "Aggregate sales by day, region, and segment",
             "timeout": 1800
           }
         }

The ``function`` field uses Python import paths (→ see :doc:`/best_practices` for resolution rules).

Step 5: Create Pipeline Definitions
------------------------------------

Define your pipelines in ``config/pipelines.toml``. Ducta has no built-in
scheduler — the ``nodes`` list determines node execution order within a
pipeline (via each node's own ``dependencies``), and cross-pipeline ordering
(Bronze → Silver → Gold) plus scheduling is handled by an external orchestrator
such as Airflow or cron (see :doc:`airflow_integration`):

.. tab-set::

   .. tab-item:: TOML (Recommended)

      .. code-block:: toml

         # config/pipelines.toml — the key IS the pipeline name (flat, no wrapper)

         # Bronze layer pipeline
         [bronze_ingestion]
         description = "Ingest raw sales data"
         type = "batch"
         nodes = ["load_raw_sales"]

         # Silver layer pipeline
         [silver_cleansing]
         description = "Clean and enrich sales data"
         type = "batch"
         nodes = ["clean_sales", "enrich_sales"]

         # Gold layer pipeline
         [gold_aggregation]
         description = "Calculate business metrics"
         type = "batch"
         nodes = ["calculate_daily_metrics"]

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/pipelines.yaml
         # Bronze layer pipeline
         bronze_ingestion:
           description: "Ingest raw sales data"
           type: batch
           nodes:
             - load_raw_sales

         # Silver layer pipeline
         silver_cleansing:
           description: "Clean and enrich sales data"
           type: batch
           nodes:
             - clean_sales
             - enrich_sales

         # Gold layer pipeline
         gold_aggregation:
           description: "Calculate business metrics"
           type: batch
           nodes:
             - calculate_daily_metrics

   .. tab-item:: JSON

      .. code-block:: json

         {
           "bronze_ingestion": {
             "description": "Ingest raw sales data",
             "type": "batch",
             "nodes": ["load_raw_sales"]
           },
           "silver_cleansing": {
             "description": "Clean and enrich sales data",
             "type": "batch",
             "nodes": ["clean_sales", "enrich_sales"]
           },
           "gold_aggregation": {
             "description": "Calculate business metrics",
             "type": "batch",
             "nodes": ["calculate_daily_metrics"]
           }
         }

Step 6: Implement Transformation Logic
---------------------------------------

Create ``transformations.py``:

.. code-block:: python

   import pyspark.sql.functions as F
   from pyspark.sql import DataFrame

   def clean_sales_data(df: DataFrame) -> DataFrame:
       """Clean and validate sales data."""

       # Remove nulls
       df_clean = df.filter(
           F.col("transaction_id").isNotNull() &
           F.col("amount").isNotNull() &
           F.col("quantity").isNotNull()
       )

       # Remove invalid amounts
       df_clean = df_clean.filter(F.col("amount") > 0)
       df_clean = df_clean.filter(F.col("quantity") > 0)

       # Remove duplicates
       df_clean = df_clean.dropDuplicates(["transaction_id"])

       # Add audit columns
       df_clean = df_clean.withColumn(
           "ingestion_timestamp",
           F.current_timestamp()
       )

       return df_clean

Step 7: Run the Pipeline (CLI)
-------------------------------

.. code-block:: bash

   # Validate configuration
   ducta start --env dev --pipeline bronze_ingestion --validate-only

   # Run bronze layer
   ducta start --env dev --pipeline bronze_ingestion

   # Run silver layer
   ducta start --env dev --pipeline silver_cleansing

   # Run gold layer
   ducta start --env dev --pipeline gold_aggregation

   # Run with specific date range
   ducta start --env dev --pipeline bronze_ingestion \
     --start-date 2024-01-01 \
     --end-date 2024-01-31

Step 8: Run Programmatically
-----------------------------

Create ``run_pipeline.py``:

.. code-block:: python

   from ducta import PipelineExecutor, ContextLoader
   import logging

   logging.basicConfig(level=logging.INFO)
   logger = logging.getLogger(__name__)

   CONFIG_PATHS = {
       "global_settings": "config/global_settings.toml",
       "pipelines": "config/pipelines.toml",
       "nodes": "config/nodes.toml",
       "input": "config/input.toml",
       "output": "config/output.toml",
   }

   def run_complete_etl():
       """Run complete ETL pipeline."""

       # Load context for the "dev" environment
       context = ContextLoader().load_from_paths(CONFIG_PATHS, env="dev")
       executor = PipelineExecutor(context)

       # Bronze layer
       logger.info("Starting Bronze layer...")
       executor.run_pipeline("bronze_ingestion")
       logger.info("Bronze completed")

       # Silver layer
       logger.info("Starting Silver layer...")
       executor.run_pipeline("silver_cleansing")
       logger.info("Silver completed")

       # Gold layer
       logger.info("Starting Gold layer...")
       executor.run_pipeline("gold_aggregation")
       logger.info("Gold completed")

       print("\n✅ ETL completed successfully!")

   if __name__ == "__main__":
       run_complete_etl()

.. note::

   ``run_pipeline`` raises an exception on failure (it does not return a
   result object with a ``.success`` flag). Wrap each call in a
   ``try/except`` block if you need to handle failures without aborting the
   whole script.

Run it:

.. code-block:: bash

   python run_pipeline.py

Step 9: Monitor Results
------------------------

Check output data:

.. code-block:: bash

   # List bronze data
   ls data/bronze/sales/

   # List silver data
   ls data/silver/sales/

   # List gold data
   ls data/gold/daily_sales/

Query results with Spark:

.. code-block:: python

   from pyspark.sql import SparkSession

   spark = SparkSession.builder.appName("Check Results").getOrCreate()

   # Read gold data
   gold_df = spark.read.format("delta").load("data/gold/daily_sales")

   # Show sample
   gold_df.show()

   # Check metrics
   gold_df.groupBy("region").agg({
       "total_sales": "sum",
       "transaction_count": "sum"
   }).show()

Step 10: Schedule with Airflow
-------------------------------

Create ``airflow_dag.py``:

.. code-block:: python

   from airflow import DAG
   from airflow.operators.python import PythonOperator
   from datetime import datetime, timedelta
   from ducta import PipelineExecutor, ContextLoader

   default_args = {
       'owner': 'data-team',
       'depends_on_past': False,
       'start_date': datetime(2024, 1, 1),
       'email_on_failure': True,
       'email_on_retry': False,
       'retries': 3,
       'retry_delay': timedelta(minutes=5),
   }

   CONFIG_PATHS = {
       "global_settings": "config/global_settings.toml",
       "pipelines": "config/pipelines.toml",
       "nodes": "config/nodes.toml",
       "input": "config/input.toml",
       "output": "config/output.toml",
   }

   def run_ducta_pipeline(pipeline_name, **kwargs):
       context = ContextLoader().load_from_paths(CONFIG_PATHS, env="production")
       executor = PipelineExecutor(context)
       # run_pipeline raises on failure, which correctly fails the Airflow task
       executor.run_pipeline(pipeline_name, start_date=kwargs['ds'], end_date=kwargs['ds'])

   with DAG(
       'sales_etl',
       default_args=default_args,
       schedule_interval='0 2 * * *',  # Daily at 2 AM
       catchup=False
   ) as dag:

       bronze = PythonOperator(
           task_id='bronze_ingestion',
           python_callable=run_ducta_pipeline,
           op_kwargs={'pipeline_name': 'bronze_ingestion'}
       )

       silver = PythonOperator(
           task_id='silver_cleansing',
           python_callable=run_ducta_pipeline,
           op_kwargs={'pipeline_name': 'silver_cleansing'}
       )

       gold = PythonOperator(
           task_id='gold_aggregation',
           python_callable=run_ducta_pipeline,
           op_kwargs={'pipeline_name': 'gold_aggregation'}
       )

       bronze >> silver >> gold

Next Steps
----------

- Add monitoring and best practices: :doc:`/best_practices`
- Explore more :doc:`/tutorials/index`

Complete Code
-------------

All code from this tutorial is available at:
https://github.com/faustinolopezramos/ducta/tree/main/examples/batch_etl
