"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

The ``ml_basic`` template: features, training, the model registry and a run table.
"""

from datetime import datetime
from typing import Dict, List, Optional

from ducta.console.templates.base import BaseTemplate


class MLBasicTemplate(BaseTemplate):
    """A churn model end to end: features in Spark, training in scikit-learn.

    What a first ML pipeline gets wrong is rarely the model: it is an unseeded
    split, hyperparameters buried in code, and a model shipped without asking
    whether it beats predicting the majority class. Each is declared in the
    pipeline file here (``split``, ``hyperparams``) or enforced by the node
    (the baseline gate), and the README says which is which.
    """

    TEMPLATE_NAME = "ML Basic"
    TEMPLATE_DESCRIPTION = (
        "Churn model: Spark features, scikit-learn training, declarative split, "
        "versioned hyperparameters and a baseline gate"
    )
    TEMPLATE_TYPE = "ml_basic"
    ARCHITECTURE = "ml"
    SAMPLE_MODULE = "pipelines.churn"
    SAMPLE_MODULE_PATH = ("pipelines", "churn.py")
    DEFAULT_PIPELINE = "churn_model"
    # The release that generated it: the nodes use persist_model(promote=...).
    REQUIREMENTS = f"ducta[spark,mlops]>={BaseTemplate.this_release()}\n"
    GITIGNORE_EXTRA = "\n# Models and experiment tracking\nmodels/\nmlops_data/\n"

    def quick_start(self) -> List[str]:
        pipeline = self.DEFAULT_PIPELINE
        return [
            "# Train the model (tracked, with a baseline gate)",
            f"ducta start -e dev -p {pipeline}",
            "",
            "# Override a hyperparameter for one run",
            f"ducta start -e dev -p {pipeline} --hyperparams '{{\"max_depth\": 3}}'",
            "",
            "# Compare every run in one table (gold.churn.runs), best first",
            "ducta start -e dev -p churn_runs",
            "",
            "# Check the project without running it (no Spark)",
            "ducta check -e dev",
        ]

    def project_yaml(self) -> str:
        return self._render(
            """\
# yaml-language-server: $schema=.ducta/schema/project.json
#
# The project: its name, where data lives, engine settings, and what changes
# per environment. Datasets are in catalog.yaml, the pipeline in pipelines/.
version: 2
project: @@PROJECT@@
description: Customer churn model - Spark features, scikit-learn training

# Base directories. Reference them anywhere as ${paths.input} / ${paths.output}.
paths: {input: data, output: data}

settings:
  mode: local                  # local | distributed | databricks
  max_parallel_nodes: 2
  fail_on_error: true
  # off | record | required | signed: what a run can prove about itself.
  evidence_level: @@EVIDENCE@@
  # Seeds random / numpy and gives every node its own deterministic seed
  # (ml_context["node_seed"]), so a run can be repeated exactly.
  random_seed: 42
@@SPARK@@  # Experiments, runs and the model registry. `type: ml` pipelines are tracked
  # automatically; mlops_required: true aborts a run that cannot be tracked.
  mlops_enabled: true
  mlops_required: false
  mlops_path: mlops_data

# Values a dataset or node gets unless it sets its own: the format per layer.
defaults:
  catalog:
    "silver.*": {format: parquet}
    "gold.*": {format: csv}

# An environment states only what differs from the base project above.
environments:
  dev:
    settings: {log_level: DEBUG}
  staging:
    # What CI runs (.github/workflows/ml.yml): tracked, like production.
    settings: {mlops_required: true}
  prod:
    # In production a model that cannot be tracked must not be shipped.
    settings: {mlops_required: true}
"""
            + self._sandbox_note()
            + """
# Free-form notes. Ducta does not read this block.
metadata:
  template: ml_basic
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# Every dataset, once. The format of silver.* and gold.* comes from
# `defaults.catalog` in ducta.yaml.

customers:
  description: One row per customer, with whether they churned
  format: csv
  path: data/customers.csv
  options: {header: true, inferSchema: true}
  # A contract: checked every time a node reads this dataset, before it runs.
  quality:
    fail_fast: true
    checks:
      empty_dataset: true
      schema:
        expected_columns: [customer_id, tenure_months, monthly_spend, support_calls, plan, churned]

silver.churn.features:
  description: Clean, de-duplicated model inputs

gold.churn.metrics:
  description: What the trained model scored, against the baseline

gold.churn.runs:
  description: One row per training run, best first - its hyperparameters, metrics, model and certificate
  # The format is yours to choose: parquet | delta | csv | json (delta needs the
  # `delta` extra). Each run of churn_runs rebuilds the table from the tracked runs.
  format: parquet
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "churn_model": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# An ML pipeline versions what a notebook would bury in code: the split and the
# hyperparameters live here, so every run records exactly what it used. Override
# hyperparameters for one run with `--hyperparams '{"max_depth": 3}'`.
description: "Churn: prepare features, train, register the model"
type: ml
requires_dates: false
model_version: "1.0.0"

hyperparams: {n_estimators: 100, max_depth: 6}

# What `ducta start -p churn_model --search` explores: the `churn_model` key of
# hyperparams.yaml (versioned with the project, like everything else).
hyperparams_config: {path: hyperparams.yaml, key: churn_model}

# Applied by the training node with ducta.mlrun.split_dataframe. Model selection
# happens on `val`; `test` is scored once, at the end, for an honest estimate.
split: {method: stratified, stratify_col: churned, test_size: 0.2, val_size: 0.2, seed: 42}

nodes:
  prepare_features:
    description: "Drop duplicates and incomplete rows; keep what the model may see"
    run: pipelines.churn:prepare_features
    inputs: {customers: customers}
    outputs: [silver.churn.features]
    # Checks on this node's OUTPUT, before it is written.
    quality:
      checks:
        empty_dataset: true
        null_rate: {columns: [tenure_months, monthly_spend, plan, churned], threshold: 0.0}
        duplicates: {columns: [customer_id], max_duplicate_rate: 0.0}
        range: {column: tenure_months, min: 0}
        row_count: {min: 500}
      gate: {max_errors: 0, on_fail: skip_downstream}

  train:
    description: "Train a random forest; register it only if it beats the baseline"
    run: pipelines.churn:train
    ml_stage: training
    inputs: {features: silver.churn.features}
    outputs: [gold.churn.metrics]
""",
            "churn_runs": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# The leaderboard: one table with a row per churn_model run, joining what was
# tracked (hyperparameters, metrics), the model it registered and its run
# certificate. Run it after training; read it with Spark, pandas or a BI tool.
# It sees churn_model's runs because both share `mlops_path` in ducta.yaml.
description: "Churn: a table of every training run, best first"
type: ml
requires_dates: false

nodes:
  runs:
    description: "Join tracked runs, registered models and certificates"
    run: pipelines.churn:runs
    outputs: [gold.churn.runs]
""",
        }

    #: Customers with a blank ``monthly_spend`` and customers repeated verbatim,
    #: so the feature node has something real to drop (as in the medallion data).
    _BLANK_SPEND = frozenset({17, 83, 140, 222, 301, 377, 450, 512, 560, 589})
    _DUPLICATED = (5, 99, 187, 264, 333, 401)
    _PLANS = ("basic", "plus", "pro")

    def seed_files(self) -> Dict[str, str]:
        """``data/customers.csv``: churn driven by support calls, short tenure and the basic plan."""
        scored = []
        for i in range(1, 601):
            plan = self._PLANS[i % 3]
            noise = (((i * 1103515245 + 12345) % 2147483648) / 2147483648 - 0.5) * 3.0
            support = (i * 5) % 7
            tenure = 1 + (i * 7) % 60
            plan_effect = 1.0 if plan == "basic" else -0.5 if plan == "pro" else 0.0
            score = 0.7 * support - 0.04 * tenure + plan_effect + noise
            scored.append((i, tenure, support, plan, score))
        cutoff = sorted(s[4] for s in scored)[int(len(scored) * 0.7)]
        rows = []
        for i, tenure, support, plan, score in scored:
            if i in self._BLANK_SPEND:
                spend = ""
            else:
                spend = f"{20 + (i * 13) % 80 + (15 if plan == 'pro' else 0)}.00"
            rows.append(f"{i},{tenure},{spend},{support},{plan},{1 if score > cutoff else 0}")
        by_id = {int(r.split(",", 1)[0]): r for r in rows}
        rows.extend(by_id[i] for i in self._DUPLICATED)
        header = "customer_id,tenure_months,monthly_spend,support_calls,plan,churned"
        return {
            "data/customers.csv": "\n".join([header, *rows]) + "\n",
            "hyperparams.yaml": self._HYPERPARAMS,
            ".github/workflows/ml.yml": self._ml_ci_workflow("churn_model"),
        }

    #: The search `--search` runs. Each trial is a run of its own; the objective is the
    #: validation AUC the training node logs — never a test metric.
    _HYPERPARAMS = """\
churn_model:
  algorithm: random
  n_trials: 6
  objective: {metric: val_auc, type: maximize}
  search_space:
    max_depth: {min: 3, max: 12}
    n_estimators: [50, 100, 200]
"""

    def generate_sample_code(self) -> Optional[str]:
        return '''"""
Churn model: prepare features in Spark, then train and register with scikit-learn.

``prepare_features`` receives and returns a Spark DataFrame. ``train`` converts
its input to pandas, which is what scikit-learn takes. Ducta also hands any node
that accepts it an
``ml_context``: the versioned hyperparameters and split, a deterministic seed,
and the experiment tracker and model registry of the run it already opened.

Four habits this module keeps, and your own nodes should too:

1. a reproducible split, with the seed from config, never an unseeded one;
2. hyperparameters from ``pipelines/churn_model.yaml``, never hard-coded;
3. a baseline: a model is only worth registering if it beats the trivial one;
4. the test set is scored once, after the model is chosen on validation data.
"""
from typing import Any, Optional

from loguru import logger


def prepare_features(
    customers: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Drop duplicates and incomplete rows, and keep only what the model may see.

    Rows with a missing value are dropped, not filled: inventing a spend of 0
    would teach the model that "unknown" means "free", and would also make the
    ``null_rate`` check in the pipeline pass for the wrong reason.
    """
    from pyspark.sql import functions as F

    before = customers.count()
    cleaned = (
        customers.dropDuplicates(["customer_id"])
        .dropna(subset=["tenure_months", "monthly_spend", "plan", "churned"])
        .withColumn("churned", F.col("churned").cast("int"))
        .select(
            "customer_id",
            "tenure_months",
            "monthly_spend",
            "support_calls",
            "plan",
            "churned",
        )
    )
    logger.info("Features: kept {:,} of {:,} customers", cleaned.count(), before)
    return cleaned


def train(features: Any, ml_context: Any = None) -> Any:
    """Train a random forest and register it if it beats the majority-class baseline."""
    import pandas as pd
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import f1_score, roc_auc_score

    from ducta.mlrun import persist_model, split_dataframe

    ml_context = ml_context or {}
    params = {"n_estimators": 100, "max_depth": 6, **(ml_context.get("hyperparams") or {})}
    seed = ml_context.get("node_seed", 42)

    # The model needs pandas. Converting here, not in the catalog, works whether
    # the dataset is read back from disk or handed over in memory.
    if hasattr(features, "toPandas"):
        features = features.toPandas()

    # One-hot encode `plan`; it has three fixed values, so doing it before the
    # split leaks nothing.
    data = pd.get_dummies(features.drop(columns=["customer_id"]), columns=["plan"], dtype=int)

    # The split is declared in pipelines/churn_model.yaml. Passing ml_context
    # lets the run certificate prove this is the split that actually ran.
    train_df, val_df, test_df = split_dataframe(
        data, ml_context.get("split"), default_seed=seed, ml_context=ml_context
    )
    target = "churned"
    x_train, y_train = train_df.drop(columns=[target]), train_df[target]
    x_val, y_val = val_df.drop(columns=[target]), val_df[target]
    x_test, y_test = test_df.drop(columns=[target]), test_df[target]

    baseline = DummyClassifier(strategy="prior").fit(x_train, y_train)
    baseline_auc = roc_auc_score(y_val, baseline.predict_proba(x_val)[:, 1])  # 0.5: no signal

    model = RandomForestClassifier(**params, random_state=seed).fit(x_train, y_train)
    val_auc = roc_auc_score(y_val, model.predict_proba(x_val)[:, 1])
    # Scored once, after the model is chosen: never used to tune or to decide.
    test_auc = roc_auc_score(y_test, model.predict_proba(x_test)[:, 1])
    test_f1 = f1_score(y_test, model.predict(x_test))
    logger.info("AUC val={:.3f} test={:.3f} (baseline {:.3f})", val_auc, test_auc, baseline_auc)

    # A gate relative to the baseline, not an absolute threshold: on imbalanced
    # data the majority-class predictor can clear almost any fixed bar.
    if val_auc < baseline_auc + 0.05:
        raise ValueError(
            f"The model does not beat the baseline: val AUC {val_auc:.3f} vs {baseline_auc:.3f}"
        )

    metrics = {
        "val_auc": float(val_auc),
        "test_auc": float(test_auc),
        "test_f1": float(test_f1),
        "baseline_auc": float(baseline_auc),
    }
    persist_model(
        model,
        ml_context,
        name="churn-model",
        framework="sklearn",
        metrics=metrics,
        hyperparameters=params,
        X=x_train,
        y=y_train,
    )
    return pd.DataFrame([metrics])


def runs(ml_context: Any = None) -> Any:
    """One row per ``churn_model`` run, best validation AUC first.

    Joins the tracked runs, the models they registered and their certificates. Run it
    with ``ducta start -e dev -p churn_runs``; it writes ``gold.churn.runs``, in the
    format ``catalog.yaml`` gives that dataset. The metric to order by is yours: change
    ``metric_val_auc`` to any ``metric_*`` column. Rank on validation, not on test.
    """
    from ducta.mlrun import run_summary

    table = run_summary(ml_context, pipeline="churn_model")
    if "metric_val_auc" in table.columns:
        table = table.sort_values("metric_val_auc", ascending=False).reset_index(drop=True)
    return table
'''

    def readme(self) -> str:
        return f"""# {self.project_name}

A **customer churn** pipeline built with **Ducta**: features in Spark, a
scikit-learn model, and the things that make a model trustworthy declared in
configuration rather than buried in code.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline churn_model
```

`data/customers.csv` is deliberately imperfect: 10 customers with no
`monthly_spend` and 6 repeated rows, so `prepare_features` has work to do and
its quality gate has something to verify.

```
customers          606 rows   as they arrived
silver features    590 rows   de-duplicated, incomplete rows dropped
gold metrics         1 row    val / test AUC, F1 and the baseline AUC
gold runs            1 row per run   (after `churn_runs`) hyperparameters, metrics, model
```

## What lives where

| | Where | Why there |
|---|---|---|
| Split (stratified, 60/20/20, seed 42) | `pipelines/churn_model.yaml` | versioned and recorded with every run |
| Hyperparameters | `pipelines/churn_model.yaml` | override once with `--hyperparams '{{"max_depth": 3}}'` |
| Random seed | `ducta.yaml` (`random_seed`) | one number makes a run repeatable |
| Experiment tracking, model registry | `ducta.yaml` (`mlops_*`) | `type: ml` pipelines are tracked automatically |
| Baseline gate | `pipelines/churn.py` | the model is registered only if it beats the trivial one |

## Search the hyperparameters

```bash
ducta start --env dev --pipeline churn_model --search
```

Six runs, each with values drawn from `hyperparams.yaml` (named by `hyperparams_config`
in `pipelines/churn_model.yaml`); it ends with the best one and its `val_auc`. Every trial's
model is registered, none promoted: promote the best with `ducta model promote`
(`ducta model list` shows the versions).

## Compare your runs in one table

Every `ducta start` is one tracked run. After a few (a different `--hyperparams`, or
a `--sweep`), build the table that puts them side by side:

```bash
ducta start --env dev --pipeline churn_runs
```

It writes `gold.churn.runs`: one row per run with its hyperparameters (`param_*`),
final metrics (`metric_*`), the model version it registered, the hash of the code and
of the data it ran on, and its certificate id. It is ordered by validation AUC; change
`metric_val_auc` in `runs()` to rank by another metric. The format is whatever
`catalog.yaml` says for that dataset (`parquet` by default; `delta` or `csv` also work).

## Then look at what happened

```bash
ducta certify list                       # every run recorded here
ducta certify show   --run-id <run-id>   # what ran, on which data, with which split
ducta check                              # config check, no Spark
```

## Project structure

```
{self.project_name}/
├── ducta.yaml                    # project, paths, settings, per-environment overrides
├── catalog.yaml                  # every dataset once (the source has a contract)
├── pipelines/
│   ├── churn_model.yaml          # the ML pipeline: split, hyperparameters, nodes
│   ├── churn_runs.yaml           # the leaderboard: a table of every run
│   └── churn.py                  # prepare_features (Spark), train (scikit-learn), runs
├── .ducta/schema/                # JSON Schemas: autocompletion in VS Code/JetBrains
└── data/customers.csv            # sample source
```

## What to change first

1. Point `customers` in `catalog.yaml` at your own data, and update its `schema` contract.
2. Replace the target, the feature columns and the model in `pipelines/churn.py`.
3. Keep the split, the baseline gate and the one-time test score.

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
