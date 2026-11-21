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

The ``ml_scoring`` template: train and promote a model, then score with it.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ducta.console.templates.base import BaseTemplate


class MLScoringTemplate(BaseTemplate):
    """Train, promote, then score new data with the promoted model.

    Two pipelines, because training and scoring run on different schedules:
    ``train`` fits a model, registers it and promotes it to production only if it
    beats the baseline; ``score`` names the model by stage (``ml_stage: serving``),
    so it always scores with whatever is in production, and its checks ask whether
    the model is behaving — scores in range, a sane share flagged, scores
    distributed as they were on the validation set.
    """

    TEMPLATE_NAME = "ML Scoring"
    TEMPLATE_DESCRIPTION = (
        "Train and promote a model, then score new data with it: serving node, "
        "prediction checks and the model version in the run certificate"
    )
    TEMPLATE_TYPE = "ml_scoring"
    ARCHITECTURE = "ml"
    SAMPLE_MODULE = "pipelines.churn"
    SAMPLE_MODULE_PATH = ("pipelines", "churn.py")
    DEFAULT_PIPELINE = "train"
    # The release that generated it: the nodes use persist_model(promote=...).
    REQUIREMENTS = f"ducta[spark,mlops]>={BaseTemplate.this_release()}\n"
    GITIGNORE_EXTRA = "\n# Models and experiment tracking\nmodels/\nmlops_data/\n"

    def quick_start(self) -> List[str]:
        return [
            "# 1. Train; the model is promoted to production if it beats the baseline",
            "ducta start -e dev -p train",
            "",
            "# 2. Score new customers with whatever model is in production",
            "ducta start -e dev -p score",
            "",
            "# Which model scored them: the certificate names the exact version",
            "ducta certify show -e dev --run-id <run-id>",
        ]

    def project_yaml(self) -> str:
        return self._render(
            """\
# yaml-language-server: $schema=.ducta/schema/project.json
#
# The project: its name, where data lives, engine settings, and what changes
# per environment. Datasets are in catalog.yaml, the pipelines in pipelines/.
version: 2
project: @@PROJECT@@
description: Churn scoring - train and promote a model, then score new customers

paths: {input: data, output: data}

settings:
  mode: local
  max_parallel_nodes: 2
  fail_on_error: true
  # off | record | required | signed. The score run's certificate names the
  # exact model version that produced every score.
  evidence_level: @@EVIDENCE@@
  random_seed: 42
@@SPARK@@  # Experiments, runs and the model registry the score pipeline reads from.
  mlops_enabled: true
  mlops_required: false
  mlops_path: mlops_data
  mlops:
    # The gate a new model passes to reach production: train's persist_model
    # promotes through it, and so does `ducta model promote`.
    promotion_policy: {metric: val_auc, compare_to: current_production, min_delta: 0.0}

defaults:
  catalog:
    "gold.*": {format: parquet}

environments:
  dev:
    settings: {log_level: DEBUG}
  staging:
    # What CI runs (.github/workflows/ml.yml): tracked, like production.
    settings: {mlops_required: true}
  prod:
    settings: {mlops_required: true}
"""
            + self._sandbox_note()
            + """
metadata:
  template: ml_scoring
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# Every dataset, once. The format of gold.* comes from `defaults.catalog` in
# ducta.yaml.

# What the model learns from. A contract: checked every time a node reads it.
customers:
  description: Customers with a known outcome - what the model learns from
  format: csv
  path: data/customers.csv
  options: {header: true, inferSchema: true}
  quality:
    checks:
      empty_dataset: true
      schema:
        expected_columns: [customer_id, tenure_months, monthly_spend, support_calls, churned]

# What the score pipeline scores: the same features, no outcome yet.
new_customers:
  description: Customers to score - no outcome yet
  format: csv
  path: data/new_customers.csv
  options: {header: true, inferSchema: true}
  quality:
    checks:
      empty_dataset: true
      schema:
        expected_columns: [customer_id, tenure_months, monthly_spend, support_calls]

gold.churn.validation_scores:
  description: The promoted model's scores on its validation set - the reference
    prediction_drift compares every scoring run against

gold.churn.scores:
  description: Every new customer with its churn score
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "train": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# Fit, check against the baseline, register, promote. Promotion is a decision
# the code makes explicitly - the score pipeline uses whatever is in production.
description: "Churn: train a model and promote it if it beats the baseline"
type: ml
requires_dates: false
model_version: "1.0.0"

hyperparams: {n_estimators: 100, max_depth: 6}
split: {method: stratified, stratify_col: churned, test_size: 0.2, seed: 42}

nodes:
  train:
    description: "Train, register, promote; write the validation scores"
    run: pipelines.churn:train
    ml_stage: training
    inputs: {customers: customers}
    outputs: [gold.churn.validation_scores]
""",
            "score": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# A serving node names its model; Ducta resolves the stage to one version when
# the run starts, verifies the artifact's hash, loads it and - with no `run` -
# applies it with the built-in scorer. The certificate records which version.
description: "Churn: score new customers with the production model"
type: ml
requires_dates: false

# When the scores drift from the validation reference, Ducta runs `train` right after
# this run. The new model reaches production only if it passes
# settings.mlops.promotion_policy; at most once a day.
retrain: {run: train, when: [prediction_drift], cooldown: 1d}

nodes:
  score:
    description: "Add churn_score to every new customer"
    ml_stage: serving
    model:
      name: churn-model
      stage: production
      # persist_model saves a pickle, and loading a pickle runs it: trust it only
      # because this project's own train pipeline registered it.
      trust_artifact: true
      method: predict_proba        # the probability of churn, not a 0/1 label
      output_col: churn_score
      # features: default to the columns the model was registered with
    inputs: [new_customers]
    outputs: [gold.churn.scores]
    # Is the model behaving? Checked before the scores are written.
    quality:
      checks:
        prediction_contract: {column: churn_score, min: 0, max: 1}
        # A model that suddenly flags everyone (or no one) has a broken input.
        prediction_rate: {column: churn_score, threshold: 0.5, min: 0.05, max: 0.6}
        # Scores distributed as they were when the model was validated.
        prediction_drift:
          column: churn_score
          reference: gold.churn.validation_scores
          method: psi
          threshold: 0.2
      gate: {max_errors: 0}
""",
        }

    def _customer(self, i: int) -> Tuple[int, int, str, int, float]:
        """One customer: churn driven by support calls and a short tenure."""
        noise = (((i * 1103515245 + 12345) % 2147483648) / 2147483648 - 0.5) * 2.0
        support = (i * 5) % 7
        tenure = 1 + (i * 7) % 60
        spend = f"{20 + (i * 13) % 80}.00"
        return i, tenure, spend, support, 0.7 * support - 0.05 * tenure + noise

    def seed_files(self) -> Dict[str, str]:
        """``customers.csv`` to learn from, ``new_customers.csv`` to score."""
        known = [self._customer(i) for i in range(1, 801)]
        cutoff = sorted(c[4] for c in known)[int(len(known) * 0.7)]
        header = "customer_id,tenure_months,monthly_spend,support_calls"
        customers = [f"{header},churned"] + [
            f"{i},{tenure},{spend},{support},{1 if score > cutoff else 0}"
            for i, tenure, spend, support, score in known
        ]
        new = [header] + [
            f"{i},{tenure},{spend},{support}"
            for i, tenure, spend, support, _ in (self._customer(i) for i in range(801, 1001))
        ]
        return {
            "data/customers.csv": "\n".join(customers) + "\n",
            "data/new_customers.csv": "\n".join(new) + "\n",
            ".github/workflows/ml.yml": self._ml_ci_workflow("train", "score"),
        }

    def generate_sample_code(self) -> Optional[str]:
        return '''"""
Churn: train a model, and promote it to production if it beats the baseline.

There is no scoring code here: the score pipeline's serving node names the model
(``model: {name: churn-model, stage: production}``) and Ducta's built-in scorer
applies it. Write a ``run`` function for it only when scoring needs more than
"features in, score out".
"""
from typing import Any

from loguru import logger

FEATURES = ["tenure_months", "monthly_spend", "support_calls"]
TARGET = "churned"


def train(customers: Any, ml_context: Any = None) -> Any:
    """Fit, gate on the baseline, register, promote; return the validation scores.

    Promotion goes through settings.mlops.promotion_policy: a model no better than
    the one in production is registered but stays in staging, and the node fails so
    the drift reference (its output) keeps describing the model in production.
    """
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score

    from ducta.mlrun import persist_model, split_dataframe

    params = {"n_estimators": 100, "max_depth": 6, **(ml_context.get("hyperparams") or {})}
    seed = ml_context.get("node_seed", 42)
    data = customers.toPandas() if hasattr(customers, "toPandas") else customers

    # The split declared in pipelines/train.yaml; ml_context proves it was applied.
    train_df, val_df = split_dataframe(
        data, ml_context.get("split"), default_seed=seed, ml_context=ml_context
    )
    model = RandomForestClassifier(**params, random_state=seed).fit(
        train_df[FEATURES], train_df[TARGET]
    )
    val_scores = model.predict_proba(val_df[FEATURES])[:, 1]
    auc = roc_auc_score(val_df[TARGET], val_scores)
    logger.info("Validation AUC {:.3f}", auc)
    if auc < 0.55:  # 0.5 is what a model with no signal scores
        raise ValueError(f"The model does not beat the baseline: validation AUC {auc:.3f}")

    registered = persist_model(
        model,
        ml_context,
        name="churn-model",
        framework="sklearn",
        metrics={"val_auc": float(auc)},
        hyperparameters=params,
        X=train_df[FEATURES],  # the feature contract the scorer reads its columns from
        promote="production",  # through settings.mlops.promotion_policy
    )
    if registered.get("promotion_refused"):
        raise ValueError(
            f"churn-model v{registered['version']} stays in staging: "
            f"{registered.get('promotion_refused')}"
        )

    # The reference prediction_drift compares every scoring run against.
    return pd.DataFrame({"churn_score": val_scores})
'''

    def readme(self) -> str:
        return f"""# {self.project_name}

Train a churn model, promote it, then **score new customers with whatever model
is in production** - and prove afterwards which model produced each score.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline train   # fit, gate, register, promote
ducta start --env dev --pipeline score   # score data/new_customers.csv
```

## How the scoring works

`pipelines/score.yaml` has one node and no Python:

```yaml
score:
  ml_stage: serving
  model: {{name: churn-model, stage: production, method: predict_proba, output_col: churn_score}}
```

- **Resolved once per run.** `stage: production` names whichever version is in
  production when the run starts; every node in that run uses that version.
- **Verified.** The registry recorded the artifact's SHA-256 when `train`
  registered it; a copy that no longer matches is refused.
- **Recorded.** `ducta certify show` lists, under the node, the model's name,
  version, the stage it came from and that hash.

## Is the model behaving?

The score node's checks run before the scores are written:

| Check | Catches |
|---|---|
| `prediction_contract` | a score missing or outside [0, 1] |
| `prediction_rate` | a model that suddenly flags everyone, or no one |
| `prediction_drift` | scores no longer distributed as on the validation set (`gold.churn.validation_scores`) |

## Promotion

`train` registers every model, and promotes it through
`settings.mlops.promotion_policy` (in `ducta.yaml`): the first one goes to production,
a later one only if its `val_auc` beats the model in production. One that does not
stays in staging, and the train run fails saying so — production, and the drift
reference, are left alone. `ducta model list` shows the versions and their stages.

## Retrain on drift

`score` declares `retrain: {{run: train, when: [prediction_drift], cooldown: 1d}}`.
When its scores drift from the validation reference, Ducta runs `train` right after
the scoring run — at most once a day. The training run's certificate says what
started it (`triggered_by`); the next `score` serves the new model if it was promoted.

To see it, score customers unlike the training ones, e.g. double every
`monthly_spend` in `data/new_customers.csv`, then `ducta start -e dev -p score`.

Run `train` by hand at any time; `ducta certify diff` between two score runs shows
when the model changed.

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
