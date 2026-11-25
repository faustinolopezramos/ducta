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

The ``hybrid_basic`` template: a batch dimension feeding a stream-static join.
"""

from datetime import datetime
from typing import Dict, List, Optional

from ducta.console.templates.base import BaseTemplate


class HybridBasicTemplate(BaseTemplate):
    """One pipeline whose batch phase feeds its streaming phase.

    ``type: hybrid`` runs every batch node to the end, with the full batch
    engine (parallelism, retries, quality gates), and only then starts the
    queries, so a stream node can depend on a batch node. A batch *pipeline*
    cannot depend on a streaming one, because a stream never completes. The
    stream here is a ``file_stream`` over JSON files, so it runs with nothing
    installed but Spark; swapping it for Kafka is shown in the README.
    """

    TEMPLATE_NAME = "Hybrid Basic"
    TEMPLATE_DESCRIPTION = (
        "Batch dimension table feeding a stream-static join, in one `type: hybrid` pipeline"
    )
    TEMPLATE_TYPE = "hybrid_basic"
    ARCHITECTURE = "hybrid"
    SAMPLE_MODULE = "pipelines.orders"
    SAMPLE_MODULE_PATH = ("pipelines", "orders.py")
    DEFAULT_PIPELINE = "orders"

    def quick_start(self) -> List[str]:
        pipeline = self.DEFAULT_PIPELINE
        return [
            "# Run the batch phase, then the stream, to completion",
            f"ducta start -e dev -p {pipeline} --mode sync",
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
# per environment. Batch datasets are in catalog.yaml; the stream node declares
# its own source and sink in pipelines/orders.yaml.
version: 2
project: @@PROJECT@@
description: Batch dimension table enriching an order stream

# Base directories. Reference them anywhere as ${paths.input} / ${paths.output}.
paths: {input: data, output: data}

settings:
  mode: local                  # local | distributed | databricks
  max_parallel_nodes: 2
  fail_on_error: true
  # off | record | required | signed: what a run can prove about itself.
  evidence_level: @@EVIDENCE@@
@@SPARK@@  # Imported before any stream starts, so the transform is registered by the
  # time the node that names it is built.
  streaming_transform_modules: [pipelines.orders]
  max_streaming_pipelines: 5

# Values a dataset or node gets unless it sets its own.
defaults:
  catalog:
    "silver.*": {format: parquet}

# An environment states only what differs from the base project above.
environments:
  dev:
    settings: {log_level: DEBUG}
"""
            + self._sandbox_note()
            + """
# Free-form notes. Ducta does not read this block.
metadata:
  template: hybrid_basic
"""
        )

    def catalog_yaml(self) -> str:
        return """\
# yaml-language-server: $schema=.ducta/schema/catalog.json
#
# The batch side's datasets. The stream node's source and sink are inline in
# pipelines/orders.yaml; its output is not a catalog dataset.

products:
  description: Product dimension (reference data, updated by batch)
  format: csv
  path: data/products.csv
  options: {header: true, inferSchema: true}
  quality:
    fail_fast: true
    checks:
      empty_dataset: true
      schema: {expected_columns: [product_id, category, unit_price]}

silver.shop.products:
  description: Clean product dimension, the static side of the stream join
"""

    def pipeline_yamls(self) -> Dict[str, str]:
        return {
            "orders": """\
# yaml-language-server: $schema=../.ducta/schema/pipeline.json
#
# `type: hybrid`: the batch node runs to the end first, then the query starts.
# If the batch phase fails or a gate blocks it, no query starts. A stream node
# says what it waits for with `after:` (its input is inline, so Ducta cannot
# infer the order from a dataset).
description: "Hybrid: build the product dimension (batch), then enrich orders (stream)"
type: hybrid
requires_dates: false

nodes:
  # -- batch phase ----------------------------------------------------------
  build_products:
    description: "Clean the product dimension and write it as Parquet"
    run: pipelines.orders:build_products
    inputs: {products_raw: products}
    outputs: [silver.shop.products]
    quality:
      checks:
        empty_dataset: true
        null_rate: {columns: [product_id, unit_price], threshold: 0.0}
        duplicates: {columns: [product_id], max_duplicate_rate: 0.0}
      gate: {max_errors: 0, on_fail: skip_downstream}

  # -- streaming phase ------------------------------------------------------
  enrich_orders:
    description: "Join each order with its product and compute the revenue"
    kind: stream
    after: [build_products]
    stream:
      input:
        format: file_stream
        file_format: json
        # Required: a stream cannot infer its schema.
        schema: order_id STRING, product_id INT, quantity INT, ts TIMESTAMP
        options:
          path: ${paths.input}/orders
          # One file per micro-batch, so the demo shows several batches.
          maxFilesPerTrigger: 1
      # `params` is a plain dict and cannot carry a DataFrame, so the dimension
      # is passed as a path and read inside the transform. Keep it under a key
      # named `path`: that is what gets ${paths.output} and ${env} expanded.
      transform:
        key: enrich_orders
        module: pipelines.orders
        params:
          products: {path: "${paths.output}/${env}/silver/shop/products"}
      output:
        format: parquet
        path: ${paths.output}/${env}/gold/shop/orders_enriched
      streaming:
        checkpoint_location: ${paths.output}/${env}/_ckpt/enrich_orders
        output_mode: append
        # Processes what is there and stops, so the whole pipeline finishes and
        # can run in CI. Use `10s` to keep the query running instead.
        trigger: available_now
"""
        }

    _CATEGORIES = ("electronics", "grocery", "apparel", "home", "toys")

    def seed_files(self) -> Dict[str, str]:
        """``data/products.csv`` (one dirty row) and five order files, one event each."""
        rows = [
            f"{pid},{self._CATEGORIES[pid % len(self._CATEGORIES)]},{5 + (pid * 11) % 90}.50"
            for pid in range(1, 31)
        ]
        # A verbatim duplicate: build_products deduplicates, and its gate checks it.
        rows.append(rows[6])
        files = {"data/products.csv": "\n".join(["product_id,category,unit_price", *rows]) + "\n"}
        for n in range(1, 6):
            events = [
                '{"order_id": "o%d%d", "product_id": %d, "quantity": %d, "ts": "2026-01-01T10:%02d:00"}'
                % (n, k, 1 + (n * 7 + k * 5) % 30, 1 + (n + k) % 4, n * 10 + k)
                for k in range(1, 4)
            ]
            files[f"data/orders/orders_{n:03d}.json"] = "\n".join(events) + "\n"
        return files

    def generate_sample_code(self) -> Optional[str]:
        return '''"""
The batch node and the streaming transform of the `orders` hybrid pipeline.

``build_products`` is an ordinary batch node. ``enrich_orders`` is a streaming
transform: Ducta calls it as ``fn(df)`` or ``fn(df, params)`` with the
streaming DataFrame, and it must return one. It gets no start/end date,
because a stream has no date range.
"""
from typing import Any, Dict, Optional

from loguru import logger


def build_products(
    products_raw: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Drop repeated products so the join below matches each order exactly once."""
    cleaned = products_raw.dropDuplicates(["product_id"])
    logger.info("Products: {:,} distinct", cleaned.count())
    return cleaned


def enrich_orders(df: Any, params: Optional[Dict[str, Any]] = None) -> Any:
    """Stream-static join: attach each order's category and compute its revenue.

    The products are plain Parquet written by the batch node. Spark treats a
    static DataFrame joined with a streaming one as a stream-static join and
    reads the table as it is at the start of each micro-batch, so re-running
    ``build_products`` with corrected data is picked up by a running stream.
    """
    from pyspark.sql import functions as F

    path = ((params or {}).get("products") or {}).get("path")
    if not path:
        raise ValueError("enrich_orders needs params.products.path (see pipelines/orders.yaml)")
    products = df.sparkSession.read.parquet(path).select("product_id", "category", "unit_price")
    return (
        df.join(products, "product_id", "left")
        .withColumn("revenue", F.round(F.col("quantity") * F.col("unit_price"), 2))
        .select("order_id", "product_id", "category", "quantity", "revenue", "ts")
    )


def register_transforms(registry: Any) -> None:
    """Called by Ducta before the pipeline starts: maps the name a node uses to the function."""
    registry.register("enrich_orders", enrich_orders)
    logger.info("Registered streaming transforms: enrich_orders")
'''

    def readme(self) -> str:
        return f"""# {self.project_name}

A **hybrid** pipeline built with **Ducta**: a batch node builds a product
dimension, then a streaming query enriches a stream of orders against it, all
in one execution.

## Run it

```bash
pip install -r requirements.txt
ducta start --env dev --pipeline orders --mode sync
```

`type: hybrid` runs the batch phase to the end first (with its quality gate),
and only then starts the query. If the batch phase fails or the gate blocks it,
no query starts. The query uses `trigger: available_now`: it processes the five
order files in `data/orders/` and stops, so the run finishes and fits in CI.

```
products.csv        31 rows    one repeated product
silver products     30 rows    de-duplicated, the static side of the join
gold orders         15 rows    each order with its category and revenue
```

## What is different from a batch pipeline

**1. Order between a stream node and the rest is explicit.** The stream node's
input is inline, so Ducta cannot infer the order from a dataset:
`after: [build_products]`.

**2. A transform cannot receive a DataFrame.** `params` is a plain dict, so the
dimension travels as a *path* and the transform reads it. Keep the path under a
key named `path`: that is what gets `${{paths.output}}` and `${{env}}` expanded.

**3. A batch pipeline cannot depend on a streaming one**, because a stream never
completes. Inside a `type: hybrid` pipeline, a stream can depend on batch nodes.

## Keep the query running

Replace `trigger: available_now` with `trigger: 10s` in `pipelines/orders.yaml`,
start it with `ducta stream run --pipeline orders --env dev`, and drop another
`.json` file into `data/orders/` to watch it picked up.

## Switching the source to Kafka

Replace the `input` block of `enrich_orders`:

```yaml
input:
  format: kafka
  options:
    kafka.bootstrap.servers: "localhost:9092"
    subscribe: "orders"
    startingOffsets: "latest"
```

Kafka delivers `key`/`value` as bytes, so parse the JSON in your transform
(`from_json(col("value").cast("string"), schema)`) before the join.

## Project structure

```
{self.project_name}/
├── ducta.yaml                  # project, paths, settings, per-environment overrides
├── catalog.yaml                # the batch datasets (the source has a contract)
├── pipelines/
│   ├── orders.yaml             # the hybrid pipeline: a batch node, then a stream node
│   └── orders.py               # build_products + the streaming transform
├── .ducta/schema/              # JSON Schemas: autocompletion in VS Code/JetBrains
└── data/
    ├── products.csv            # sample dimension
    └── orders/                 # the watched source directory
```

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
