MLOps & Experiment Tracking
============================

Ducta's MLOps module provides a unified infrastructure for managing the machine learning lifecycle. It focuses on observability, reproducibility, and deployment of models within your data pipelines.

Core Capabilities
-----------------

*   **Experiment Tracking**: Automatic logging of parameters, metrics, and models.
*   **Model Registry**: Centralized management of model versions and lifecycle stages (Staging, Production, Archived).
*   **Artifact Management**: Store models, plots, and datasets securely in cloud storage.
*   **MLflow Integration**: Native support for MLflow as a backend for tracking and registry.

Configuration
-------------

Ducta turns tracking on automatically for ``ml``-type pipelines — you don't call
any setup function in your code. Three keys under ``settings`` in ``ducta.yaml``
steer it:

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Key
     - Default
     - Description
   * - ``mlops_enabled``
     - auto
     - ``true`` or ``false`` forces tracking on or off. Left out, tracking is on
       when the pipeline being run has an ML node. ``settings.mlops.enabled`` is
       the same switch; when both are written, the nested one wins.
   * - ``mlops_required``
     - ``false``
     - ``true`` aborts the run if tracking cannot start; ``false`` logs a warning
       and runs without it.
   * - ``mlops_path``
     - see below
     - Directory that holds the experiments and the model registry.

Without ``mlops_path``, each pipeline keeps its tracking next to its data, in
``<paths.output>/<env>/<schema>/<folder>/experiment_tracking`` and
``.../model_registry`` — for the pipeline ``ml.student_risk``, that is
``data/dev/ml/student_risk/``.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "churn"

         [paths]
         input = "data"
         output = "data"

         [settings]
         mlops_path = "models"
         mlops_required = false

         [environments.dev.settings]
         mlops_enabled = false

         [environments.prod.settings]
         mlops_required = true

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: churn
         paths: {input: data, output: data}
         settings:
           mlops_path: models           # one registry for every pipeline of the project
           mlops_required: false
         environments:
           dev:
             settings: {mlops_enabled: false}      # fast iteration, no tracking
           prod:
             settings: {mlops_required: true}      # no tracking, no run

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "churn",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "mlops_path": "models",
             "mlops_required": false
           },
           "environments": {
             "dev": {
               "settings": {
                 "mlops_enabled": false
               }
             },
             "prod": {
               "settings": {
                 "mlops_required": true
               }
             }
           }
         }

.. note::

   Only the keys above are read from ``ducta.yaml``. A ``settings.mlops`` block
   with other keys (``storage_path``, ``backend_type``, ...) is accepted without
   an error and **has no effect** on a pipeline run.

**Tuning knobs, through the environment.** The retention, buffering, retry and
backend options of the MLOps module are read from environment variables by
``ducta mlops ...`` and the API, not from the project file:

.. list-table::
   :widths: 38 20 42
   :header-rows: 1

   * - Variable
     - Default
     - Meaning
   * - ``Ducta_MLOPS_BACKEND``
     - ``local``
     - ``local``, ``databricks`` or ``distributed``.
   * - ``Ducta_MLOPS_PATH``
     - ``./mlops_data``
     - Root of experiments, registry and artifacts for the ``ducta mlops`` commands.
   * - ``Ducta_MLOPS_MODEL_RETENTION_DAYS``
     - ``90``
     - Days to keep archived model versions before GC.
   * - ``Ducta_MLOPS_MAX_VERSIONS``
     - ``100``
     - Versions kept per model.
   * - ``Ducta_MLOPS_METRIC_BUFFER_SIZE``
     - ``100``
     - Metrics buffered in memory before flushing to disk.
   * - ``Ducta_MLOPS_AUTO_FLUSH``
     - ``true``
     - Flush metric buffers at the end of a run.
   * - ``Ducta_MLOPS_CIRCUIT_BREAKER``
     - ``false``
     - Protect the system during backend outages.
   * - ``DATABRICKS_CATALOG`` / ``DATABRICKS_SCHEMA`` / ``DATABRICKS_VOLUME``
     - ``main`` / ``ml_tracking`` / ``mlops_artifacts``
     - Unity Catalog location for the Databricks backend.

The upper-case spelling (``DUCTA_MLOPS_PATH``) is accepted as well.

MLflow tracking (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~

With the ``mlops`` extra installed, ``settings.mlflow`` also records every run, node,
metric and model in MLflow (version 3.15 or later):

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # ducta.toml
         version = 2
         project = "churn"

         [paths]
         input = "data"
         output = "data"

         [settings.mlflow]
         enabled = true
         experiment_name = "churn"
         tracking_uri = "sqlite:////srv/mlflow/mlflow.db"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # ducta.yaml
         version: 2
         project: churn
         paths: {input: data, output: data}
         settings:
           mlflow:
             enabled: true
             experiment_name: churn
             tracking_uri: sqlite:////srv/mlflow/mlflow.db   # or http://mlflow.internal:5000

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "version": 2,
           "project": "churn",
           "paths": {
             "input": "data",
             "output": "data"
           },
           "settings": {
             "mlflow": {
               "enabled": true,
               "experiment_name": "churn",
               "tracking_uri": "sqlite:////srv/mlflow/mlflow.db"
             }
           }
         }

Use a database or a tracking server for ``tracking_uri``. MLflow 3 keeps the local
folder store (``tracking_uri: mlruns``, ``file://...``) only in maintenance mode and
refuses it by default; Ducta still accepts one, so runs already recorded there stay
readable, and says so with a warning. Convert such a folder with
``mlflow migrate-filestore``, or set ``MLFLOW_ALLOW_FILE_STORE=false`` to have MLflow
refuse it. A ``tracking_uri`` without a scheme (``mlruns``) is placed under
``<paths.output>/<env>/``; one with a scheme (``sqlite:///``, ``http://``) is used as
written. Without ``tracking_uri``, MLflow uses ``./mlflow.db`` in the working directory.

Writing an ML Pipeline
----------------------

The split, the hyperparameters and the model version live in the pipeline file, so a
data scientist changes an experiment without touching Python — and Ducta makes sure
the Python actually uses them.

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/churn.toml
         type = "ml"
         requires_dates = false
         model_version = "1.0"

         [hyperparams]
         n_estimators = 200
         max_depth = 8

         [split]
         method = "stratified"
         stratify_col = "churned"
         test_size = 0.2
         seed = 42

         [nodes.build_features]
         run = "churn.features:build_features"
         ml_stage = "feature_engineering"
         outputs = [
             "ml.churn.features",
         ]

         [nodes.build_features.inputs]
         customers = "silver.crm.customers"

         [nodes.train]
         run = "churn.model:train"
         ml_stage = "training"
         outputs = [
             "ml.churn.metrics",
         ]

         [nodes.train.hyperparams]
         max_depth = 6

         [nodes.train.inputs]
         features = "ml.churn.features"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/churn.yaml
         type: ml
         requires_dates: false
         model_version: "1.0"
         hyperparams: {n_estimators: 200, max_depth: 8}
         split: {method: stratified, stratify_col: churned, test_size: 0.2, seed: 42}
         nodes:
           build_features:
             run: churn.features:build_features
             ml_stage: feature_engineering
             inputs: {customers: silver.crm.customers}
             outputs: [ml.churn.features]
           train:
             run: churn.model:train
             ml_stage: training                 # bound to apply the split above
             hyperparams: {max_depth: 6}        # merged over the pipeline's
             inputs: {features: ml.churn.features}
             outputs: [ml.churn.metrics]

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "type": "ml",
           "requires_dates": false,
           "model_version": "1.0",
           "hyperparams": {
             "n_estimators": 200,
             "max_depth": 8
           },
           "split": {
             "method": "stratified",
             "stratify_col": "churned",
             "test_size": 0.2,
             "seed": 42
           },
           "nodes": {
             "build_features": {
               "run": "churn.features:build_features",
               "ml_stage": "feature_engineering",
               "inputs": {
                 "customers": "silver.crm.customers"
               },
               "outputs": [
                 "ml.churn.features"
               ]
             },
             "train": {
               "run": "churn.model:train",
               "ml_stage": "training",
               "hyperparams": {
                 "max_depth": 6
               },
               "inputs": {
                 "features": "ml.churn.features"
               },
               "outputs": [
                 "ml.churn.metrics"
               ]
             }
           }
         }

.. code-block:: python

   # churn/model.py
   from ducta.mlrun import split_dataframe

   def train(features, ml_context=None):
       df = features.toPandas()
       # The split declared in the pipeline file — never a second copy in code.
       train_df, test_df = split_dataframe(df, ml_context.split, ml_context=ml_context)
       model = fit(train_df, **ml_context.hyperparams, random_state=ml_context.node_seed)
       ...

**Where each value comes from.** A ``split``, ``hyperparams`` or ``model_version``
written on a node overrides the pipeline's (hyperparameters are merged key by key).
A run's ``--hyperparams`` and ``--model-version`` override both, for that run.

**Who must apply the split.** A node with its own ``split:``, and a node with
``ml_stage: training`` or ``evaluation`` under a pipeline ``split:``. Other nodes (feature
engineering) receive ``ml_context.split`` too but are not bound by it. A bound node
that finishes without calling ``split_dataframe`` (or ``kfold_splits``) with its
``ml_context`` **fails before its output is written** — its model would have been
fitted and scored on a partition nobody declared. ``settings.split_enforcement: warn``
lets the run continue with a warning instead.

**Checked before anything runs.** ``ducta config validate`` reports, with file and line:
an unknown key in a ``split`` (``stratify_column``), a ``stratified`` split without
``stratify_col``, an unknown ``ml_stage`` (``trainning`` — which would quietly free a
node from the split), a pipeline ``split`` that no node is bound to apply, and a bound
node whose function has no ``ml_context`` parameter to receive it.

**See what each node will get:**

.. code-block:: bash

   ducta config show --ml --pipeline churn

.. code-block:: text

   churn:
     type: ml
     split_enforcement: error
     split: {method: stratified, stratify_col: churned, test_size: 0.2, seed: 42}
     nodes:
       build_features: {ml_stage: feature_engineering, split_from: pipeline, must_apply_split: false, ...}
       train:          {ml_stage: training, split_from: pipeline, must_apply_split: true,
                        hyperparams: {n_estimators: 200, max_depth: 6}, model_version: '1.0'}

**What the run certificate proves.** Each ML node's entry carries an ``ml`` block:
the split it was given, where it was declared (``node`` or ``pipeline``), whether it was
bound to apply it, **whether it did**, its model version and its hyperparameters. The
split is recorded as applied only when the node really called ``split_dataframe``.

**MLflow.** A model, metric or artifact that fails to reach MLflow is logged as an
error. With ``settings.mlflow.required: true`` (or ``mlops_required: true``) it fails
the node instead, so a run never reports success without the model it was meant to log.

Tracking Inside a Node
----------------------

For an ``ml``-type pipeline, Ducta creates the experiment and run for you and
delivers everything a node needs through a typed ``ml_context`` argument (an
``MLNodeContext``). You just read the tracking handles from it and
log — no ``init``/``get_context`` calls:

.. code-block:: python

   from typing import Any, Optional
   from ducta import MLNodeContext   # typed, but ml_context also works as a dict


   def train(training_data: Any, ml_context: Optional[MLNodeContext] = None) -> Any:
       ml_context = ml_context or {}

       # Reproducibility + hyperparameters are supplied by Ducta
       seed = ml_context.get("node_seed", 42)
       params = {"n_estimators": 100, **(ml_context.get("hyperparams") or {})}

       model = my_trainer.fit(training_data, random_state=seed, **params)
       f1 = my_evaluator.score(model)

       # Log to the auto-created run, if MLOps is active for this pipeline
       mlops = ml_context.get("mlops_context")
       run_id = ml_context.get("mlops_run_id")
       if mlops and run_id and getattr(mlops, "experiment_tracker", None):
           tracker = mlops.experiment_tracker
           for key, value in params.items():
               tracker.log_parameter(run_id, key, value)
           tracker.log_metric(run_id, "f1", f1)

       return model

.. note::
   The run is opened before your node runs and closed after it returns
   (``COMPLETED`` on success, ``FAILED`` on exception) — you never manage its
   lifecycle. :doc:`tutorials/mlops` builds a complete pipeline around a node
   like this one.

Model Registry
--------------

The Ducta registry provides version-controlled model management. Newly registered models start in the **Staging** stage by default.

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Stage
     - Description
   * - ``Staging``
     - Default stage. Used for validation and testing.
   * - ``Production``
     - Active model serving live predictions.
   * - ``Archived``
     - Deprecated versions. Eligible for garbage collection.

**Promotion (CLI — the recommended path):**

.. code-block:: bash

   # ducta model promote <name> <version> <staging|production|archived>
   ducta model promote sales_predictor 1.2.0 production

   # Clean up old versions past the retention window
   ducta model gc --dry-run

Promotion to ``production`` is checked against your promotion policy; use
``--force`` to bypass it (the bypass is audit-logged). See :doc:`cli_usage` for
the full ``ducta model`` and ``ducta experiment`` command reference.

Serving a Model
---------------

A node with ``ml_stage: serving`` scores data with a registered model. It names the
model; Ducta resolves it, verifies it and hands it over loaded:

.. tab-set::
   :sync-group: ducta-format

   .. tab-item:: TOML
      :sync: toml

      .. code-block:: toml

         # pipelines/score.toml
         type = "ml"
         requires_dates = false

         [nodes.score]
         ml_stage = "serving"
         outputs = [
             "gold.crm.churn_scores",
         ]

         [nodes.score.model]
         name = "churn_clf"
         stage = "production"
         trust_artifact = true
         features = [
             "tenure",
             "spend",
         ]
         output_col = "churn_score"
         method = "predict_proba"

         [nodes.score.inputs]
         customers = "silver.crm.customers"

   .. tab-item:: YAML
      :sync: yaml

      .. code-block:: yaml

         # pipelines/score.yaml
         type: ml
         requires_dates: false
         nodes:
           score:
             ml_stage: serving
             model:
               name: churn_clf
               stage: production           # or version: 3
               trust_artifact: true        # required for a pickle/joblib (sklearn) model
               features: [tenure, spend]   # default: the model's registered input schema
               output_col: churn_score     # default: prediction
               method: predict_proba       # predict | predict_proba | decision_function | score_samples
             inputs: {customers: silver.crm.customers}
             outputs: [gold.crm.churn_scores]

   .. tab-item:: JSON
      :sync: json

      .. code-block:: json

         {
           "type": "ml",
           "requires_dates": false,
           "nodes": {
             "score": {
               "ml_stage": "serving",
               "model": {
                 "name": "churn_clf",
                 "stage": "production",
                 "trust_artifact": true,
                 "features": [
                   "tenure",
                   "spend"
                 ],
                 "output_col": "churn_score",
                 "method": "predict_proba"
               },
               "inputs": {
                 "customers": "silver.crm.customers"
               },
               "outputs": [
                 "gold.crm.churn_scores"
               ]
             }
           }
         }

Without ``run``, the built-in scorer applies the model to the node's single input
and adds ``output_col`` — on a pandas or a Spark DataFrame (``mapInPandas``; on
Spark 3 with Java 21+, where Arrow cannot run, a slower row-based path). With
``run``, your function receives the model:

.. code-block:: python

   def score(customers, ml_context=None):
       model = ml_context.model                      # loaded once per run
       ref = ml_context.model_ref                    # which model, exactly
       ...                                           # ref.local_path for frameworks
                                                     # Ducta does not load itself

**One version per run.** ``stage: production`` is resolved when the run starts, and
every node naming it in that run gets that version, even if a promotion lands
mid-run. The next run resolves it again.

**Output type.** In batch the scorer infers the prediction's Spark type from one
row; ``output_type: double | long | string | boolean`` sets it instead.

**A Spark ML model.** Register the directory ``model.save(path)`` writes, with
``framework: spark-mllib``. It loads without unpickling anything, scores with
``model.transform`` (its pipeline assembles its own features, so ``features`` is
not used) and supports ``method: predict`` or ``predict_proba``. It is read from
the registry's own storage, so a cluster can read it too.

**On a stream.** A ``kind: stream`` node takes the same block under ``stream:``:

.. code-block:: yaml

   score_events:
     kind: stream
     stream:
       input: {format: kafka, options: {subscribe: events, ...}}
       output: {format: delta, path: ${paths.output}/${env}/scored_events}
       model: {name: fraud, stage: production, trust_artifact: true, output_type: double}
       streaming: {trigger: {processing_time: 30 seconds}}

Without a ``transform`` the built-in scorer applies the model to each
micro-batch; a transform declared with an ``ml_context`` parameter receives the
model instead (``def score(df, params, ml_context=None)``). The model is resolved
when the query starts and kept for its lifetime — a restart resolves the stage
again — and the pipeline status lists it under ``served_models``. A stream cannot
be sampled, so its prediction type is ``double`` unless ``output_type`` says
otherwise. Scoring a stream needs Arrow (``mapInPandas``): Spark 3 on Java 21+
cannot run it, and the node says so.

**From MLflow.** ``model: {source: mlflow, uri: "models:/churn_clf@champion"}`` (or
``models:/churn_clf/3``) resolves the alias to a version through
``settings.mlflow.tracking_uri`` and loads it as a pyfunc model (``method: predict``).

**What is checked.** A pickle-based model (sklearn, joblib, pickle) loads only with
``trust_artifact: true``: loading it runs its contents. The registry records each
artifact's SHA-256 at registration, and a copy that no longer matches is refused.
``ducta config validate`` warns when the model does not resolve yet — a chain may
register it in an earlier pipeline.

**What the certificate proves.** The node's ``ml.model`` entry records the source,
name, the version the run pinned, the stage it was resolved from and the artifact's
hash; ``ducta certify diff`` reports when two runs scored with different models.

Training at Scale
-----------------

``split_dataframe`` takes a Spark DataFrame as well as a pandas one, and splits it
without collecting it to the driver — so a training set that does not fit in
memory never has to:

.. code-block:: python

   from ducta.mlrun import split_dataframe

   def train(features, ml_context=None):
       train_df, test_df = split_dataframe(features, ml_context.split, ml_context=ml_context)
       model = pipeline.fit(train_df)               # pyspark.ml
       ...

The methods keep their guarantees: ``random`` and ``group`` assign rows by a hash
of their content (or group) and the seed, so the assignment does not depend on
partitioning and a group never spans two partitions; ``stratified`` takes exactly
``test_size`` of each class; ``temporal`` cuts at the time column's quantiles.
They are the same proportions as the pandas path, not the same rows.
``kfold_splits`` still needs pandas.

Register a ``pyspark.ml`` model with ``framework="spark-mllib"`` (the directory
``model.save`` wrote); the registry checks its layout without loading it, and the
serving node scores with it on Spark. For gradient boosting,
``pip install "ducta[boost]"`` adds XGBoost and LightGBM, whose native formats
(``.json``/``.ubj``, ``.txt``) load without trusting a pickle.

Lineage & Reproducibility
-------------------------

Ducta MLOps captures essential metadata automatically to ensure reproducibility:

- **Data Fingerprinting:** Generates content digests for input/output datasets.
  ``fingerprint_mode`` selects how much is covered: ``auto`` (default — the
  Delta table version, the run's incremental window, or every row of a small
  dataset), ``exact`` (order-independent digest over every row), ``sample``
  (schema plus the first ``fingerprint_sample_rows`` rows) or ``schema``
  (schema and row count only).
  Each fingerprint records the engine and algorithm that produced it, so
  fingerprints measured differently are reported as *not comparable* rather
  than as changed data.
- **Environment Snapshot:** Records Python version, OS, installed packages, and Git commit hash for every run.
- **Config Snapshots:** A full copy of the active configuration is attached as a JSON artifact to the run.

Reliability
-----------

The registry is safe to use from concurrent runs: writes to metadata and
artifacts are applied atomically, so a failure part-way through a promotion or
registration rolls back cleanly instead of leaving a half-written model. Backend
health (storage reachable, tracking server up) is checked when MLOps
initializes, and problems surface in the run logs.

Next Steps
----------

- :doc:`tutorials/mlops` - Build a complete end-to-end ML pipeline.
- :doc:`best_practices` - Standards for naming experiments and models.
