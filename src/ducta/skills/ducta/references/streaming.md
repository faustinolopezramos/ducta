# Streaming pipelines (Spark Structured Streaming)

A pipeline with `type: streaming` (or `hybrid`, mixing batch and stream nodes) whose
nodes are `kind: stream`. Start from `ducta template --template streaming_basic` (a file
stream that runs locally) or `hybrid_basic`.

```yaml
# pipelines/events.yaml
type: streaming
requires_dates: false
nodes:
  clean_events:
    kind: stream
    stream:
      input:
        format: kafka                       # kafka | kinesis | delta_stream | file_stream
        options:
          kafka.bootstrap.servers: broker:9092
          subscribe: events
      transform:
        key: clean_events                   # a registered transform
        module: pipelines.transforms        # imported so it can register itself
        params: {min_amount: 0.0}
      output:
        format: delta
        path: ${paths.output}/${env}/silver/events
      streaming:
        checkpoint_location: ${paths.output}/${env}/_ckpt/clean_events
        output_mode: append                 # append | update | complete
        trigger: {type: processing_time, interval: 10 seconds}
        watermark: {column: event_time, delay: 10 minutes}
```

A `file_stream` input needs `file_format` and a `schema`
(`schema: event_id STRING, amount DOUBLE, ts TIMESTAMP`).

**Where keys go:** how the query runs (`checkpoint_location`, `trigger`,
`output_mode`, `query_name`, `watermark`) belongs in `streaming:`. The same key beside
`input` or inside `output` is an error.

**One checkpoint per node and per environment.** Build paths and checkpoints from
`${paths.output}` and `${env}`; two environments sharing a checkpoint share state.

Triggers: `processing_time` (with `interval`), `once`, `available_now`, `continuous`.
Default: `processing_time` every 10 seconds, `append`.

## Transforms

```python
# pipelines/transforms.py
from pyspark.sql import DataFrame, functions as F

def clean_events(df: DataFrame, params: dict) -> DataFrame:
    return df.filter(F.col("amount") >= params.get("min_amount", 0))

def register_transforms(registry) -> None:
    registry.register("clean_events", clean_events)
```

Only registered transforms run. Modules are imported from the transform's `module`,
from `settings.streaming_transform_modules`, or `ducta stream run --transforms-module`.
Omit `transform` to copy the stream as-is; add `model:` (as in [mlops](mlops.md)) to
score each micro-batch.

## Running

```bash
ducta stream run --pipeline events --env dev             # start and return
ducta stream run --pipeline events --env dev --mode sync # wait for the queries
ducta stream status --env dev --output-format json
ducta stream stop --execution-id ID --env dev
```

`ducta start --pipeline events --mode sync` also runs streaming and hybrid pipelines.

**Backfills and CI:** a terminating trigger (`once`, `available_now`) plus `--mode sync`
turns a stream into a batch job. Switch it per environment:

```yaml
environments:
  sandbox:
    pipelines.events.nodes.clean_events.stream.streaming.trigger: {type: available_now}
```

## Common problems

| Symptom | Fix |
|---|---|
| "checkpoint already in use" | another query uses that checkpoint: give each node (and environment) its own |
| transform not found | the module is not imported or does not call `registry.register` with that key |
| `trigger` / `checkpoint_location` "not allowed here" | move it under `stream.streaming` |
| the command returns at once and nothing seems to happen | default `--mode async`: use `ducta stream status`, or `--mode sync` |
| scoring a stream fails on Java 21 | streaming model scoring needs Arrow: use JDK 17 |
