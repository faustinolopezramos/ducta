# Troubleshooting

Find the symptom (search for words of the error), confirm the cause with the command
given, then apply the fix. If nothing matches: `ducta <command> --help`,
`ducta config schema`, and `python3 scripts/check_env.py`.

## Contents
- [Installation and environment](#installation-and-environment)
- [Configuration and validation](#configuration-and-validation)
- [Running](#running)
- [Data and Spark](#data-and-spark)
- [Quality](#quality)
- [Ingestion](#ingestion)
- [ML, streaming, server, AI](#ml-streaming-server-ai)

## Installation and environment

| Symptom | Likely cause | Confirm | Fix |
|---|---|---|---|
| `ducta: command not found` | environment not active | `check_env.py`: `ducta.command` null | activate the venv/conda env, or `pip install ducta` |
| `No module named 'pyspark'` (or another package), exit 5 | extra not installed | `check_env.py` → `extras` | `pip install "ducta[spark]"` (or the extra named) |
| `JAVA_GATEWAY_EXITED`, "Java gateway process exited" | no JDK / wrong `JAVA_HOME` | `check_env.py` → `java` | install JDK 17; set `JAVA_HOME` |
| errors mentioning Arrow, `sun.misc.Unsafe`, `DirectByteBuffer` on Java 21 | PySpark 3.5 Arrow cannot run on JDK 21+ | `check_env.py` warns | JDK 17, or `settings.spark_config: {spark.sql.execution.arrow.pyspark.enabled: "false"}` |
| skill and Ducta versions differ | upgraded Ducta | `check_env.py` → `ducta` | trust `--help` and `ducta config schema`; `ducta skill install --force` updates the skill |

## Configuration and validation

Always start with `ducta config validate --env ENV --output-format json`.

| Symptom | Likely cause | Fix |
|---|---|---|
| "No Ducta project" / no `ducta.yaml` found | running outside the project | `cd` into it, or `--base-path` (`--config` for `ducta stream`) |
| `unknown key 'X' — did you mean 'Y'?` | typo or key in the wrong place | apply `fix.replace`; check `ducta config schema` for where the key belongs |
| "reads 'X', which is not in the catalog" | dataset not declared, or misspelled | declare it once in the catalog, or use the suggested name |
| "is written by both" | two nodes write one dataset | give one of them a new output |
| "cycle" | nodes depend on each other through data, `after` or `depends_on` | break the loop: split a dataset, remove an `after` |
| "cannot load function" / `function_not_found` | wrong `run:` path, or the module does not import | check `module:function` is relative to the project root; import the module in Python to see the real error |
| an `inputs` key "is not a parameter" | key ≠ function parameter name | rename the key or the parameter to match |
| "already defined" in two files | same dataset/profile declared twice | keep one |
| a dotted override "there is no node 'X'" | typo in `environments.<env>` | fix the path; it must name something that exists |
| `${NAME}` left unexpanded | variable not set in that shell / `.env` | set it, or check the spelling |
| `${…PASSWORD…}` refused | secret-looking names cannot be interpolated | use the source's `<SOURCE>_USER/_PASSWORD` convention or platform credentials |
| YAML value read as boolean/number | unquoted `no`, `on`, `1e3`, `08` | quote it |
| `ducta.yaml` and `ducta.toml` both present | one file per role | keep one |

## Running

| Symptom | Likely cause | Fix |
|---|---|---|
| asks for `--start-date`/`--end-date` | `requires_dates: true` is the default | pass both dates, or set `requires_dates: false` if the pipeline processes everything |
| exit 3, pipeline not found | wrong name | `ducta config list-pipelines` (name = file stem) |
| exit 7, "locked" | another run writes the same output | wait for it and retry; check `settings.run_lock` |
| "succeeded" but nodes did not run | a gate blocked with `on_fail: skip_downstream`, or `on_missing_input: skip` | read the run summary; fix the data or the check |
| node skipped: input missing | upstream not run yet | run the upstream pipeline (`depends_on`) or the whole chain |
| node timed out | over `node_timeout_seconds`/`timeout_seconds` | raise the limit, or speed the node; pure Python: `run_in_process: true` |
| exit 6, security refusal | `run:` names a module outside the project | keep node code inside the project |
| exit 2 on `ducta start` | invalid configuration or failed preflight | run `ducta config validate --output-format json` |

## Data and Spark

| Symptom | Likely cause | Fix |
|---|---|---|
| `Path does not exist`, `FileNotFoundError` | input path wrong for that environment | `ducta config show --env ENV --pipeline P` to see the resolved path |
| `UNRESOLVED_COLUMN … Did you mean` | column renamed/misspelled | use the suggested column; check the upstream schema |
| data type mismatch | schema changed upstream | declare `schema:` in the catalog or cast in the function |
| duplicated rows after a re-run | `write.mode: append` | `merge` with `keys`, or `replaceWhere` |
| "duplicate keys" on merge | the batch has repeated keys | deduplicate before writing |
| `OutOfMemoryError` | collecting to the driver (`toPandas`) or huge shuffles | stay in Spark; raise memory in `spark_config`; process windows |
| `format: delta` fails | `delta` extra missing | `pip install "ducta[delta]"` |

## Quality

| Symptom | Fix |
|---|---|
| a check names a column the data lacks → it fails | fix the column name; checks never pass silently |
| `threshold` out of range for `null_rate` | it is a share 0–1 (`0.05` = 5 %) |
| unknown profile | define it in `settings.quality.profiles` or `quality/profiles.yaml` |
| custom check not found | add its module to `settings.quality.extensions`; the web server never imports them |
| gate too strict in dev | relax it in `environments.dev`, keep prod strict |
| reports not found | `ducta quality report --dataset D --env ENV --pipeline P` (reports are per pipeline) |

## Ingestion

See [ingestion](ingestion.md#troubleshooting): credentials as `<SOURCE>_USER` /
`<SOURCE>_PASSWORD`, driver download into `lib/jdbc/`, `ducta init ingestion test`.

## ML, streaming, server, AI

See the "Common problems" table at the end of [mlops](mlops.md),
[streaming](streaming.md), [server-and-ui](server-and-ui.md),
[databricks](databricks.md) and [ai-builder](ai-builder.md).
