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

The ``medallion_basic`` template: bronze, silver and gold in one batch pipeline.
"""

from datetime import datetime
from typing import Dict

from ducta.console.templates.base import BaseTemplate

PIPELINES_ETL_MODULE = "pipelines.etl"


class MedallionBasicTemplate(BaseTemplate):
    """Functional Medallion template: minimal, clean, and production-ready."""

    TEMPLATE_NAME = "Medallion Basic"
    TEMPLATE_DESCRIPTION = (
        "Batch ETL across bronze/silver/gold, with quality gates that block on real defects"
    )
    TEMPLATE_TYPE = "medallion_basic"
    ARCHITECTURE = "medallion"
    SAMPLE_MODULE = PIPELINES_ETL_MODULE
    SAMPLE_MODULE_PATH = ("pipelines", "etl.py")
    DEFAULT_PIPELINE = "etl"

    def project_yaml(self) -> str:
        return self._render(
            """\
# yaml-language-server: $schema=.ducta/schema/project.json
#
# The project: its name, where data lives, engine settings, and what changes
# per environment. Datasets are in catalog.yaml, pipelines in pipelines/.
version: 2
project: @@PROJECT@@
description: Medallion ETL (bronze, silver, gold) with quality gates

# Base directories. Reference them anywhere as ${paths.input} / ${paths.output}.
paths: {input: data, output: data}

# Every engine setting. `ducta config schema` lists them all.
settings:
  mode: local                  # local | distributed | databricks
  max_parallel_nodes: 4
  fail_on_error: true
  # off | record | required | signed: what a run can prove about itself.
  evidence_level: @@EVIDENCE@@
@@SPARK@@  quality:
    # Modules with your own @register_check classes (see pipelines/checks/).
    # extensions: [pipelines.checks.custom_checks]
    profiles:
      default:
        checks:
          empty_dataset: {enabled: true}

# Values a dataset or node gets unless it sets its own. Here: the format of each
# layer, so catalog.yaml only says what is specific to a dataset. Also available:
# defaults.node (retry, timeout_seconds, ...) and a per-pipeline `defaults:`.
defaults:
  catalog:
    "bronze.*": {format: parquet}
    "silver.*": {format: parquet}
    "gold.*": {format: csv}

# An environment states only what differs from the base project above.
environments:
  dev:
    settings: {max_parallel_nodes: 1, log_level: DEBUG}
  prod:
    settings: {max_parallel_nodes: 8}
"""
            + self._sandbox_note()
            + """
# Free-form notes. Ducta does not read this block.
metadata:
  template: medallion_basic
  layers: [bronze, silver, gold]
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# Every dataset, once, whether a node reads it, writes it, or both.
# A dotted name (schema.folder.table) with no `path` is stored at
# ${paths.output}/${env}/<schema>/<folder>/<table>.

source_data:
  description: Source orders (CSV, JSON or Parquet)
  format: csv
  path: data/input.csv
  options: {header: true, inferSchema: true}
  # A contract: checked every time a node reads this dataset, before it runs.
  quality:
    fail_fast: true
    empty_dataset: true
    schema: {expected_columns: [order_id, category, amount, order_date]}

# The format of bronze.*, silver.* and gold.* comes from `defaults.catalog` in
# ducta.yaml; a dataset states only what is its own. Datasets are overwritten on
# each run unless you add `write: {mode: append}` (or merge).
bronze.etl.raw_data:
  description: Raw data landed by `extract` (bronze)

silver.etl.clean_data:
  description: Clean data produced by `transform` (silver)

gold.etl.final_output:
  description: Final output, one row per category (gold)
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "etl": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# The file name is the pipeline name. Run order comes from the datasets:
# `transform` reads what `extract` writes, so it runs after it (use `after:`
# only when nothing connects two nodes).
description: "Complete ETL pipeline: Extract → Transform → Load"
type: batch
requires_dates: false        # not incremental: runs without --start-date/--end-date

nodes:
  extract:
    description: "Bronze: land the source exactly as it arrived"
    run: pipelines.etl:extract
    inputs: {source_data: source_data}     # {function parameter: dataset}
    outputs: [bronze.etl.raw_data]

  transform:
    description: "Silver: deduplicate, drop incomplete and invalid rows"
    run: pipelines.etl:transform
    inputs: {raw_data: bronze.etl.raw_data}
    outputs: [silver.etl.clean_data]
    # Checks on this node's OUTPUT, evaluated before it is written. They pass
    # only because `transform` cleans the data: break it and the gate blocks
    # the run before gold exists.
    quality:
      fail_fast: false
      null_rate: {columns: [amount], threshold: 0.0}
      duplicates: {columns: [order_id], max_duplicate_rate: 0.0}
      # A negative amount is a refund or an entry error, not a missing value:
      # null_rate and duplicates both pass on it, so only this check notices.
      range: {column: amount, min: 0}
      # A floor, not a ceiling: catches a transform that drops most rows.
      row_count: {min: 400}
      # skip_downstream: gold is skipped and nothing bad is written.
      # Use stop_all to abort the whole run instead.
      gate: {max_errors: 0, on_fail: skip_downstream}

  load:
    description: "Gold: aggregate into one row per category"
    run: pipelines.etl:load
    inputs: {clean_data: silver.etl.clean_data}
    outputs: [gold.etl.final_output]
    quality:
      empty_dataset: true
      row_count: {min: 1}
"""
        }

    def readme(self) -> str:
        return _medallion_readme_v2(self)

    #: Rows whose ``amount`` is blank, so `transform` has real nulls to drop and
    #: the silver null_rate check has something to have actually verified.
    _NULL_ROWS = frozenset({37, 88, 145, 190, 233, 271, 318, 366, 402, 447, 480, 495})
    #: Orders repeated verbatim at the end of the file, so deduplication is a
    #: visible step rather than a claim.
    _DUPLICATED_ORDERS = (12, 74, 155, 219, 288, 341, 409, 468)
    #: Rows with a negative ``amount`` — a refund or entry error, not a missing
    #: value — so the silver `range` check has a defect only *it* catches
    #: (null_rate and duplicates would both pass on these rows untouched).
    _NEGATIVE_AMOUNT_ROWS = frozenset({15, 60, 120, 175, 260, 305, 355, 390, 430, 475})
    _CATEGORIES = ("electronics", "grocery", "apparel", "home", "toys")

    def get_sample_data(self) -> str:
        """A deliberately dirty CSV, so the medallion layers have work to do."""
        header = "order_id,category,amount,order_date"
        rows = []
        for order_id in range(1, 501):
            category = self._CATEGORIES[order_id % len(self._CATEGORIES)]
            base_amount = f"{50 + (order_id * 7) % 450}.00"
            if order_id in self._NULL_ROWS:
                # Blank (not 0) — a missing amount, which is what null_rate is about.
                amount = ""
            elif order_id in self._NEGATIVE_AMOUNT_ROWS:
                amount = f"-{base_amount}"
            else:
                amount = base_amount
            day = (order_id % 28) + 1
            rows.append(f"{order_id},{category},{amount},2025-01-{day:02d}")

        by_id = {int(r.split(",", 1)[0]): r for r in rows}
        rows.extend(by_id[order_id] for order_id in self._DUPLICATED_ORDERS)

        return "\n".join([header, *rows]) + "\n"


def _medallion_readme_v2(template: "BaseTemplate") -> str:
    """README for a format-2 medallion project."""
    return f"""# {template.project_name}

A medallion ETL pipeline built with **Ducta**.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline etl
```

The sample data is **deliberately dirty** — 12 rows with a missing `amount`,
8 verbatim duplicates, and 10 rows with a negative `amount` — so the run has
something real to do:

```
bronze  508 rows   raw, exactly as it arrived
silver  478 rows   deduplicated, incomplete and invalid rows dropped
gold      5 rows   one row per category
```

## Then prove what happened

```bash
ducta certify list                       # every run recorded here
ducta certify show   --run-id <run-id>   # what ran, on which data
ducta certify verify --run-id <run-id>   # integrity (+ signature, with the key)
```

## See the quality gate work

`pipelines/etl.yaml` asserts on the silver layer that `amount` has no nulls, no
negative values, and `order_id` has no duplicates, with a gate of
`max_errors: 0`. To watch it block:

1. Open `pipelines/etl.py` and comment out the `cleaned.dropna()` line in
   `transform`.
2. Re-run `ducta start --env dev --pipeline etl`.

The gate blocks, `load` is skipped, and **gold is never written**.

## Project structure

```
{template.project_name}/
├── ducta.yaml             # project, paths, settings, per-environment overrides
├── catalog.yaml           # every dataset once: format, path, how it is written,
│                          #   and the checks it must always pass (contracts)
├── pipelines/
│   ├── etl.yaml           # the pipeline: its nodes, their inputs/outputs, checks
│   ├── etl.py             # your transformations (plain functions)
│   └── checks/custom_checks.py
├── .ducta/schema/         # JSON Schemas: autocompletion in VS Code/JetBrains
└── data/
    ├── input.csv          # sample source
    └── dev/               # bronze/ silver/ gold/ written per environment
```

An environment only states what differs — for example, in `ducta.yaml`:

```yaml
environments:
  prod:
    settings: {{max_parallel_nodes: 8, evidence_level: signed}}
    paths: {{output: s3://my-lake/prod}}
```

## What to change first

1. Point `source_data` in `catalog.yaml` at your own data.
2. Rewrite the three functions in `pipelines/etl.py`.
3. Update the checks in `pipelines/etl.yaml` to assert what *your* transform
   guarantees.

## Useful commands

```bash
ducta config list-pipelines                  # what is defined here
ducta config validate                        # config check, no Spark
ducta config schema --out .                  # refresh the editor schemas
ducta server start --port 8000               # web UI (pip install ducta-server)
```

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
