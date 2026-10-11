# MLOps: training, tracking, registry, serving

Needs `pip install "ducta[spark,mlops]"` (`boost` for XGBoost/LightGBM).

## Contents
- [An ML pipeline](#an-ml-pipeline)
- [The split is enforced](#the-split-is-enforced)
- [Tracking settings](#tracking-settings)
- [Hyperparameter runs](#hyperparameter-runs)
- [Experiments and the registry](#experiments-and-the-registry)
- [Serving a model](#serving-a-model)
- [Common problems](#common-problems)

## An ML pipeline

The split, hyperparameters and model version live in the pipeline file, not in code:

```yaml
# pipelines/ml.churn.yaml
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
    ml_stage: training              # bound to apply the split above
    hyperparams: {max_depth: 6}     # merged over the pipeline's
    inputs: {features: ml.churn.features}
    outputs: [ml.churn.metrics]
```

```python
# churn/model.py
from ducta.mlrun import split_dataframe

def train(features, ml_context=None):
    df = features.toPandas()
    train_df, test_df = split_dataframe(df, ml_context.split, ml_context=ml_context)
    model = fit(train_df, **ml_context.hyperparams, random_state=ml_context.node_seed)
    ...
```

`ml_stage`: `feature_engineering`, `training`, `evaluation`, `serving`. The function
receives an `ml_context` (`split`, `hyperparams`, `node_seed`, `cv_folds`, tracking
handles, `model` for serving) when it declares that parameter.

`ducta.mlrun.train_with_search(estimator, X, y, ml_context, task=…, scoring=…,
baseline_metric=…, min_delta=…, name=…)` does split → search → evaluate → baseline gate →
log → register in one call.

## The split is enforced

A node with its own `split:`, or with `ml_stage: training|evaluation` under a pipeline
`split:`, **must** call `split_dataframe` (or `kfold_splits`) with its `ml_context`, or
it fails before its output is written. `settings.split_enforcement: warn` relaxes this.
`ducta config validate` reports unknown split keys, a stratified split without
`stratify_col`, an unknown `ml_stage`, a split no node applies, and a bound node
without an `ml_context` parameter.

```bash
ducta config show --ml --pipeline ml.churn     # what each node will be given, and why
```

Precedence: node `split`/`hyperparams`/`model_version` over the pipeline's
(hyperparameters merge key by key); `--hyperparams`/`--model-version` override both for
one run.

## Tracking settings

```yaml
# ducta.yaml
settings:
  mlops_path: models          # one registry for the whole project (else per pipeline, next to its data)
  mlops_required: false       # true: a run aborts when tracking cannot start
  # mlops_enabled: auto by default (on when the pipeline has an ML node)
  mlflow:                     # optional, also record in MLflow (3.15+)
    enabled: true
    experiment_name: churn
    tracking_uri: sqlite:////srv/mlflow/mlflow.db   # or http://mlflow.internal:5000
environments:
  dev:
    settings: {mlops_enabled: false}
```

Only `mlops_enabled`, `mlops_required`, `mlops_path` and `mlflow` are read from the
project; other `settings.mlops` keys have no effect. Tuning knobs come from environment
variables (`DUCTA_MLOPS_PATH`, `DUCTA_MLOPS_BACKEND`, `DUCTA_MLOPS_MAX_VERSIONS`, …).
MLflow 3 refuses a plain folder store by default: use a database or server URI.

## Hyperparameter runs

```bash
ducta start --env dev --pipeline ml.churn --hyperparams '{"max_depth": 4}'
ducta start --env dev --pipeline ml.churn --sweep sweep.yaml          # cartesian grid
ducta start --env dev --pipeline ml.churn --search --search-trials 30 # uses hyperparams_config
```

`hyperparams_config` (in the pipeline) defines `algorithm: grid|random|bayesian`,
`n_trials` and `objective.metric`. Optimise a **validation** metric, never a test one.

## Experiments and the registry

```bash
ducta experiment list --env dev --pipeline ml.churn
ducta experiment runs EXPERIMENT_ID --env dev --pipeline ml.churn
ducta experiment show RUN_ID --env dev --pipeline ml.churn
ducta experiment compare RUN_A RUN_B --env dev --pipeline ml.churn
ducta model promote churn_model 3 production --env dev --pipeline ml.churn
ducta model gc --dry-run --env dev --pipeline ml.churn
```

Pass `--env` and `--pipeline` (or `--storage-path`): without them the commands look in
`./mlops_data`, rarely where a run wrote. Stages: `staging` (new versions), `production`,
`archived`. Promotion follows the promotion policy; `--force` bypasses it (audit-logged
— only when the user asks). `<version>` is the registry's integer (`3` or `v3`).

## Serving a model

```yaml
# pipelines/score.yaml
type: ml
requires_dates: false
nodes:
  score:
    ml_stage: serving
    model:
      name: churn_clf
      stage: production          # or version: 3; or source: mlflow + uri: "models:/churn_clf@champion"
      trust_artifact: true       # required for pickle/joblib (sklearn) models
      features: [tenure, spend]  # default: the model's registered input schema
      output_col: churn_score    # default: prediction
      method: predict_proba      # predict | predict_proba | decision_function | score_samples
    inputs: {customers: silver.crm.customers}
    outputs: [gold.crm.churn_scores]
    quality:
      prediction_contract: {column: churn_score, min: 0, max: 1}
```

Without `run:` the built-in scorer adds `output_col`. One version per run: `stage` is
resolved when the run starts. Native XGBoost/LightGBM or `spark-mllib` models load
without `trust_artifact`. The `ml_scoring` template (`ducta template --template
ml_scoring`) shows train → promote → score.

## Common problems

| Symptom | Fix |
|---|---|
| node fails: split not applied | call `split_dataframe(df, ml_context.split, ml_context=ml_context)` in the bound node |
| `ml_context` is None | the pipeline is not `type: ml`, or the function lacks the `ml_context` parameter |
| experiment/model commands find nothing | pass `--env` and `--pipeline` (or `--storage-path`) |
| model refuses to load | add `trust_artifact: true` for pickles, or persist natively (`framework="xgboost", native=True`) |
| scoring on Java 21 is slow or fails on streams | Spark 3 + Java 21 cannot run Arrow: use JDK 17 |
| MLflow file store refused | use `tracking_uri: sqlite:///…` or a server |
