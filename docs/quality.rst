Data Quality
============

Ducta checks data at the two moments that matter: **before** a node runs, on
what it reads, and **after**, on what it wrote. A failing check can stop the
run, skip what depends on it, or only warn — and every outcome is recorded in
the run's certificate.

- **16 built-in checks** — schema, nulls, duplicates, ranges, freshness,
  drift, cross-table integrity, SQL business rules — plus your own.
- **Contracts** on datasets, checked wherever they are read.
- **Gates** that turn check results into a decision.
- The same checks run on **Spark** and **pandas**.

Where checks go
---------------

The same block — ``checks``, plus an optional ``gate`` — goes in three places:

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Place
     - Runs
   * - A dataset's ``quality`` in ``catalog.yaml``
     - Before every node that reads the dataset: its **contract**.
   * - A node's ``input_checks``
     - Before that node only, on one input. Replaces the dataset's contract for
       that node.
   * - A node's ``quality``
     - After the node, on what it wrote.

Input checks: before a node runs
--------------------------------

A contract belongs to the dataset, so it protects every consumer — the right
place for data another team or system produces:

.. code-block:: yaml

   # catalog.yaml
   orders_raw:
     format: csv
     path: ${paths.input}/orders.csv
     options: {header: true}
     quality:
       fail_fast: true               # stop checking at the first failure
       empty_dataset: true
       schema: {expected_columns: [order_id, amount, order_date]}
       row_count: {min: 1000}

When a contract fails, the node does not run. What happens to the rest of the
pipeline is the gate's decision (below; by default the node's dependants are
skipped).

Output checks: after a node runs
--------------------------------

.. code-block:: yaml

   # pipelines/etl.yaml
   nodes:
     clean:
       run: pipelines.etl:clean
       inputs: {raw: orders_raw}
       outputs: [silver.sales.orders]
       quality:
         checks:
           null_rate: {columns: [order_id], threshold: 0}
           duplicates: {columns: [order_id]}
           range: {column: amount, min: 0, max: 1000000}
         gate:
           max_errors: 0
           on_fail: stop_all

``check_name: true`` enables a check with its defaults; ``false`` disables it
(useful to switch off one check of a profile). With several outputs,
``dataset_name`` picks the one the checks apply to (default: the first).

Gates
-----

A gate turns the checks' results into a pass or a block:

.. list-table::
   :widths: 28 72
   :header-rows: 1

   * - Key
     - Effect
   * - ``max_errors``
     - Blocks when more error-severity checks fail. Default ``0``: without a
       gate, any failing check blocks.
   * - ``max_warnings``
     - Logs a warning when more warning-severity checks fail (never blocks).
   * - ``min_pass_rate``
     - Blocks when the share of passing checks is lower (``0.95`` = 95 %).
   * - ``required_checks``
     - Blocks when any of these checks fails — or is missing.
   * - ``score_threshold`` + ``score_weights``
     - Blocks when the weighted score (0–1) is lower, e.g.
       ``score_weights: {schema: 0.5, null_rate: 0.3, duplicates: 0.2}``.

When a gate blocks, ``on_fail`` decides what happens:

- ``skip_downstream`` *(default)* — the node's dependants are skipped;
  independent branches keep running and the run does not fail.
- ``stop_all`` — the whole run stops and fails.
- ``warn_only`` — the failure is logged and the pipeline continues.

Every node's gate outcome — score, pass/fail, errors and warnings — is recorded
in the Run Certificate's ``quality`` section, so the certificate proves which
gates a run passed.

Gates can be stricter in production only:

.. code-block:: yaml

   # ducta.yaml
   version: 2
   project: sales
   paths: {input: data, output: data}
   environments:
     prod:
       pipelines.etl.nodes.clean.quality.gate.on_fail: stop_all
       pipelines.etl.nodes.clean.quality.gate.max_errors: 0

Profiles
--------

A profile is a named set of checks, defined once in ``ducta.yaml`` (or in
``quality/profiles.yaml``, which keeps ``ducta.yaml`` short — see
:ref:`profiles-file`) and used by any block with ``profile:``. The block's own ``checks`` are merged on top, and
a profile name that does not exist is an error, not a silent no-op:

.. code-block:: yaml

   # ducta.yaml
   version: 2
   project: sales
   paths: {input: data, output: data}
   settings:
     quality:
       profiles:
         keyed:
           checks:
             empty_dataset: {enabled: true}
             duplicates: {columns: [id]}

.. code-block:: yaml

   # pipelines/customers.yaml
   nodes:
     dedupe:
       run: pipelines.customers:dedupe
       inputs: {raw: customers_raw}
       outputs: [silver.crm.customers]
       quality:
         profile: keyed
         checks:
           null_rate: {columns: [email], threshold: 0.05}

Available checks
----------------

``ducta quality list`` prints every registered check, including yours.

.. list-table::
   :widths: 24 76
   :header-rows: 1

   * - Category
     - Checks
   * - Structural
     - ``schema`` (``expected_columns``, ``strict``), ``row_count`` (``min``,
       ``max``), ``null_rate`` (``columns``, ``threshold``), ``empty_dataset``,
       ``duplicates`` (``columns``, ``max_duplicate_rate``), ``range``
       (``column``, ``min``, ``max``), ``referential_integrity``,
       ``schema_drift``
   * - Temporal
     - ``freshness``, ``incremental_volume``, ``anomaly_detection``
   * - Distribution
     - ``drift_detection`` (against the dataset's stored baseline),
       ``statistical``
   * - Cross-table
     - ``cross_table_referential``, ``dataset_completeness``
   * - Business
     - ``business_rules`` — SQL predicates each row must satisfy

A check that names a column the dataset does not have **fails**; it does not
silently check nothing. ``ducta quality validate-config --node NAME`` checks a
node's checks and profiles without reading data, and
``ducta profile --input FILE`` proposes the checks a dataset already satisfies.

Custom checks
-------------

.. code-block:: python

   # pipelines/quality_checks.py
   from ducta.check import BaseQualityCheck, register_check


   @register_check("positive_amounts")
   class PositiveAmounts(BaseQualityCheck):
       def __init__(self):
           super().__init__("positive_amounts")

       def _run_impl(self, df, config, adapter, context_datasets=None):
           # The adapter runs the same SQL condition on Spark and pandas.
           negatives = adapter.filter_where("amount < 0")
           return self._create_result(
               passed=negatives == 0,
               message=f"{negatives} row(s) with a negative amount",
               details={"negative_rows": negatives},
           )

Register the module in ``ducta.yaml`` and use the check like a built-in one:

.. code-block:: yaml

   # ducta.yaml
   version: 2
   project: sales
   paths: {input: data, output: data}
   settings:
     quality:
       extensions: [pipelines.quality_checks]

An exception inside ``_run_impl`` becomes a failed result, not a crashed run.
The API server does not import extension modules (it never runs code from a
workspace's configuration); the CLI does.

Reports
-------

Each run writes its reports next to the environment's data:

.. code-block:: text

   <paths.output>/<env>/.quality/
     <pipeline>/
       <node>/
         reports/<run_id>.json        # every check's result
         gate_results/<run_id>.json   # the gate's decision
         history.json                 # scores over time (trends)
         baseline.json                # statistics drift_detection compares against
     _adhoc/                          # `ducta quality run` on a bare file

Reports are scoped per pipeline, so two pipelines with a node of the same name
never mix. Read them with ``ducta quality report``, ``trend`` and ``score``, or
in the web app.
