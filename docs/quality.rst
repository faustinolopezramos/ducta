Data Quality
============

Ducta Quality is a unified framework for validating data reliability at every stage of your pipeline. It bridges the gap between pre-execution structural checks (**Sanity**) and post-execution statistical validation (**Quality Gates**).

Key Features
------------

- **Dual-Phase Validation**: Fail-fast before processing (Sanity) and validate results after (DQ).
- **Engine Agnostic**: The same checks work on **Spark** and **Pandas**.
- **16 Built-in Checks**: Schema, null rates, duplicates, drift detection, schema drift, and more.
- **Quality Gates**: Weighted scoring to automatically block pipelines with "bad" data.
- **Statistical Baselines**: Automatic drift detection based on historical data.

Phases of Validation
--------------------

1. Sanity Phase (Pre-execution)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Structural checks run on node inputs. If a sanity check fails with ``fail_fast = true``, the node function is never executed.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — top-level key IS the node name (flat, no wrapper)
         [load_data.sanity_checks]
         enabled = true
         fail_fast = true
         checks.schema = { expected_columns = ["id", "amount", "ts"] }
         checks.empty_dataset = {}

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         load_data:
           sanity_checks:
             enabled: true
             fail_fast: true
             checks:
               schema:
                 expected_columns: ["id", "amount", "ts"]
               empty_dataset: {}

   .. tab-item:: JSON

      .. code-block:: json

         {
           "load_data": {
             "sanity_checks": {
               "enabled": true,
               "fail_fast": true,
               "checks": {
                 "schema": { "expected_columns": ["id", "amount", "ts"] },
                 "empty_dataset": {}
               }
             }
           }
         }

2. Validation Phase (Post-execution)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Statistical and business rule checks run on node outputs.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         # config/nodes.toml — flat: [<node_name>.data_quality]
         [transform_data.data_quality]
         enabled = true
         checks.null_rate = { columns = ["id"], threshold = 0.01 }
         checks.duplicates = { columns = ["id"] }
         checks.range = { column = "amount", min = 0, max = 1000000 }

   .. tab-item:: YAML

      .. code-block:: yaml

         # config/nodes.yaml
         transform_data:
           data_quality:
             enabled: true
             checks:
               null_rate:
                 columns: ["id"]
                 threshold: 0.01
               duplicates:
                 columns: ["id"]
               range:
                 column: amount
                 min: 0
                 max: 1000000

   .. tab-item:: JSON

      .. code-block:: json

         {
           "transform_data": {
             "data_quality": {
               "enabled": true,
               "checks": {
                 "null_rate": { "columns": ["id"], "threshold": 0.01 },
                 "duplicates": { "columns": ["id"] },
                 "range": { "column": "amount", "min": 0, "max": 1000000 }
               }
             }
           }
         }

Quality Gates
-------------

Quality gates aggregate multiple checks into a single score (0-1). You can configure thresholds to **Warn** or **Block** the pipeline.

When a gate blocks, its ``behavior`` decides what happens to the run:

- ``skip_downstream`` *(default)* — skip the blocked node's descendants, but let
  independent branches keep running. The run does not fail; the blocked node and
  its skipped descendants are recorded in the Run Certificate.
- ``stop_all`` — abort the whole pipeline.
- ``warn_only`` — log the gate failure and let the node proceed as if it passed.

The gate outcome for every node (score, pass/fail, errors/warnings) is recorded in
the Run Certificate's ``quality`` section automatically — no output persistence
needed — so a certificate proves which gates the run actually passed.

.. tab-set::

   .. tab-item:: TOML

      .. code-block:: toml

         [transform_data.data_quality.quality_gate]
         behavior = "stop_all"               # stop_all, skip_downstream, warn_only
         min_pass_rate = 0.95                # Require 95% of checks to pass

         [transform_data.data_quality.quality_gate.score_weights]
         schema = 0.5
         null_rate = 0.3
         duplicates = 0.2

   .. tab-item:: YAML

      .. code-block:: yaml

         transform_data:
           data_quality:
             quality_gate:
               behavior: stop_all
               min_pass_rate: 0.95
               score_weights:
                 schema: 0.5
                 null_rate: 0.3
                 duplicates: 0.2

   .. tab-item:: JSON

      .. code-block:: json

         {
           "transform_data": {
             "data_quality": {
               "quality_gate": {
                 "behavior": "stop_all",
                 "min_pass_rate": 0.95,
                 "score_weights": {
                   "schema": 0.5,
                   "null_rate": 0.3,
                   "duplicates": 0.2
                 }
               }
             }
           }
         }

Available Checks
----------------

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Category
     - Checks
   * - **Structural** (8)
     - ``schema``, ``row_count``, ``null_rate``, ``empty_dataset``, ``duplicates``, ``range``, ``referential_integrity``, ``schema_drift``
   * - **Temporal** (3)
     - ``freshness``, ``incremental_volume``, ``anomaly_detection``
   * - **Distribution** (2)
     - ``drift_detection`` (compares against historical baseline), ``statistical``
   * - **Cross-table** (2)
     - ``cross_table_referential``, ``dataset_completeness``
   * - **Business** (1)
     - ``business_rules`` (SQL or Python lambdas)

Custom Checks
-------------

You can register your own validation logic using the Ducta Quality API:

.. code-block:: python

   from ducta.quality import BaseQualityCheck, register_check

   @register_check("my_custom_check")
   class MyCheck(BaseQualityCheck):
       def run(self, df, config, adapter, context_datasets=None):
           # Logic here
           return self._create_result(passed=True, message="Success!")

Reporting & Visibility
----------------------

Ducta automatically generates reports in the ``.quality/`` directory:

- **Terminal Reports**: Rich, colored tables summarizing check results.
- **JSON/Parquet artifacts**: Persistent history for auditing and trend analysis.
- **Drift Baselines**: Statistical profiles stored as ``baseline.json``.

Reports, baselines, and history are scoped **per pipeline**, not shared globally, so two
pipelines that happen to have a node with the same name never mix or overwrite each other's
quality data::

   .quality/
     <pipeline_name>/
       <dataset_name>/
         reports/<run_id>.json
         baseline.json
         history.json
     _adhoc/
       <dataset_name>/...   # runs with no real pipeline (e.g. `ducta quality run` on a bare file)

The same scoping applies to the optional structured output (``data_quality.output`` /
``global_config.quality.output``, when ``enabled: true``), which persists under
``<base_path>/<report_type>/<pipeline_name>/<node_name>/<run_id>``.
