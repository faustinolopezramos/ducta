# Ducta Check

> **The data-quality engine of Ducta.** It runs declarative, engine-agnostic quality checks (Pandas **or** Spark) at two points in a node's lifecycle — pre-execution **sanity checks** on inputs and post-execution **data-quality checks** on outputs — and enforces **Quality Gates** that can block, warn, or skip downstream work based on the results.

## At a glance

| | |
|---|---|
| **Purpose** | Validate data before/after each node and gate the pipeline on the results |
| **Layer** | Data quality |
| **Depends on** | `setting` (node/quality schemas) |
| **Used by** | `core` (node quality phases), `console`, `api` (quality endpoints) |
| **Key entry points** | `SanityPhaseRunner`, `ValidationPhaseRunner`, `QualityGateEvaluator`, `register_check`, `DFAdapter` |
| **Install** | Bundled with the core engine (`pip install ducta`) |

## Where it fits

```mermaid
flowchart TD
    console["console · CLI"] --> core
    api["api · REST / WebSocket"] --> core
    ui["ui · Web UI"] --> api
    setting["setting · Config foundation"] --> core["core · Orchestration"]
    core --> gate["gate · Data I/O"]
    core --> stream["stream · Streaming"]
    core --> check["check · Data quality"]
    core --> mlrun["mlrun · MLOps"]
    style check fill:#4f46e5,stroke:#312e81,color:#fff
```

---

## 1. Overview

### For Non-Technical Users
Bad data quietly corrupts everything built on top of it. Ducta Check is the **inspection station** on the assembly line:
*   **Checks the data before and after each step** — is it empty, are values missing, is the schema what we expected, did the numbers drift from yesterday?
*   **Decides what to do about problems** — a "quality gate" can stop the pipeline, raise a warning, or skip only the steps that depend on the bad data.
*   **Keeps a record** of every inspection so teams can see quality trends and audit what happened.

### For Technical Users
Ducta Check is the validation layer, implementing:
*   **Engine-agnostic checks**: a `DFAdapter` normalizes counts, schema, nulls, percentiles, anti-joins, and sampling across Pandas and Spark, so every check runs identically on both (`core.py`).
*   **Extensible registry**: checks self-register via `@register_check`, and `load_quality_extensions` imports user modules to add custom checks (`core.py`, `checks/`).
*   **Two-phase runners**: `SanityPhaseRunner` (pre-execution, fail-fast) and `ValidationPhaseRunner` (post-execution, gate-aware) orchestrate check execution and reporting (`engine.py`).
*   **Quality Gates**: `QualityGateEvaluator` computes a weighted score and evaluates `max_errors`, `max_warnings`, `min_pass_rate`, `score_threshold`, and `required_checks`, producing a `GateResult` with a `behavior` (`skip_downstream` | `stop_all` | `warn_only`) (`gate.py`).
*   **Profiles & auto-tuning**: reusable named check bundles and `ThresholdAdvisor`/`apply_auto_tune` for data-driven thresholds (`profiles.py`, `advisor.py`).
*   **Persistence**: `QualityOutputManager` + pluggable `StorageBackend`s persist reports (parquet/delta/json/csv) with a `QualityService` facade (`output_manager.py`, `storage.py`, `service.py`).

### Built-in checks
`empty_dataset`, `null_rate`, `schema`, `schema_drift`, `row_count`, `duplicates`, `range`, `referential_integrity`, `cross_table_referential`, `anomaly_detection`, `incremental_volume`, `freshness`, `drift_detection`, `statistical`, `dataset_completeness`, `business_rules`, and on a model's output `prediction_contract`, `prediction_rate`, `prediction_drift` — plus any custom `@register_check`. `anomaly_detection` compares a column's mean with the stored baseline (a dataset-level signal, not a per-row flag).

---

## 2. Configuration & Schemas

Users write checks in three places (see `docs/quality.rst`): a dataset's `checks` in `catalog.yaml` and a node's `input_checks` — both compiled into the node's `sanity_checks` (pre-execution, per input) — and a node's `quality` block, compiled into `data_quality` (post-execution). The `quality` block's `gate` becomes `quality_gate`; per-input blocks keep theirs as `gate` under `sanity_checks.inputs.<dataset>`; `on_fail` becomes `behavior`. The engine-side keys are:

*   **`sanity_checks`**: `inputs: {dataset: {checks, gate, profile, fail_fast}}` (one block per input), or node-wide `enabled`, `fail_fast`, `profile`, `checks`, optional `sanity_gate`.
*   **`data_quality`**: `enabled`, `fail_fast`, `dataset_name`, `profile`, `checks: {name: config}`, optional `quality_gate`, `output`.
*   **Gate keys**: `max_errors`, `max_warnings` (`-1` = unlimited), `min_pass_rate`, `score_threshold`, `score_weights`, `required_checks`, `behavior`.
*   **`output`**: `enabled`, `format`, `write_mode`, `partition_by`, `per_node`, `global_summary`.

Precedence: node-level config always wins over profile defaults, which win over global defaults.

---

## 3. Configuration Examples

```yaml
# ducta.yaml — reusable profiles and custom checks
version: 2
project: sales
paths: {input: data, output: data}
settings:
  quality:
    extensions: [myproject.custom_checks]    # auto-loaded @register_check modules
    profiles:
      bronze_defaults:
        checks: {empty_dataset: true, null_rate: {columns: [id], threshold: 0}}
```

```yaml
# pipelines/sales.yaml — checks on the input and on the output, plus a persisted report
nodes:
  clean_sales:
    run: myproject.nodes:clean_sales
    inputs: {raw: raw_sales}
    outputs: [core.analytics.sales_clean]
    input_checks:
      raw_sales:
        profile: bronze_defaults
        fail_fast: true
    quality:
      fail_fast: false
      checks:
        row_count: {min: 1000}
        range: {column: amount, min: 0}
        duplicates: {columns: [id]}
      gate:
        required_checks: [duplicates]
        score_threshold: 0.9
      output: {enabled: true, format: parquet}
```

---

## 4. Python Quickstart

### Step 1: Run a check directly via the adapter
```python
import pandas as pd
from ducta.check import DFAdapter, QUALITY_CHECKS_REGISTRY

df = pd.DataFrame({"id": [1, 2, 2, None]})
adapter = DFAdapter(df)                       # works for Spark too
check = QUALITY_CHECKS_REGISTRY["null_rate"]()
result = check.run(df, {"column": "id", "max": 0.0}, adapter)
print(result.passed, result.message)
```

### Step 2: Run the post-execution validation phase
```python
from ducta.check import ValidationPhaseRunner

runner = ValidationPhaseRunner(context=context, fail_fast=False)
report = runner.run(
    dataset_name="sales_clean",
    df=result_df,
    config={"checks": {"row_count": {"min": 1000}, "duplicates": {"columns": ["id"]}}},
)
print(report.passed, report.score, report.errors_count)
```

### Step 3: Evaluate a Quality Gate
```python
from ducta.check import QualityGateEvaluator

gate = QualityGateEvaluator.from_config(
    report,
    node_gate_cfg={"max_errors": 0, "required_checks": ["duplicates"]},
)
print(gate.action, gate.behavior, gate.triggered_rules)   # e.g. GateAction.BLOCK ...
```

### Step 4: Register a custom check
```python
from typing import ClassVar, FrozenSet

from ducta.check import register_check, BaseQualityCheck

@register_check("positive_amounts")
class PositiveAmountsCheck(BaseQualityCheck):
    # Optional, but worth declaring: preflight uses it to reject a misspelled
    # parameter before the run. Without it, `positive_amounts: {colum: amount}`
    # validates clean and the check then runs against a column that is None.
    # `enabled`, `type` and `severity` are always accepted; omit CONFIG_PARAMS
    # entirely and only the check's *name* is validated.
    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset({"column"})

    def run(self, df, config, adapter, context_datasets=None):
        bad = adapter.filter_where(f"{config['column']} < 0")
        return self._create_result(passed=bad == 0, message=f"{bad} negative rows")
```

`ducta config validate` reports, before anything runs and without a Spark
session: check names that are not in the registry, parameters a check does not
accept, and a `quality_gate.behavior` that would silently fall back. A check
name typo used to surface at runtime as *"Quality gate blocked"* — a verdict
about your data, for a mistake in your config.

### Step 5: Run + persist against a file (service facade)
```python
from ducta.check import QualityService

# Runs checks on a local file, persists the report, and returns it as a dict.
report = QualityService.run_checks(
    input_path="data/sales.parquet",
    format="parquet",
    config_path="checks.yaml",
    workspace=".",
)
trend = QualityService.get_trend("sales", workspace=".")   # historical scores
```
