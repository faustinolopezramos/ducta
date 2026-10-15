# Installing Ducta

## Requirements

- Python **3.10 to 3.13**.
- For Spark pipelines: a **JDK** on `PATH` (or `JAVA_HOME`). PySpark 3.5 supports
  Java 8/11/17; on Java 21 its Arrow path cannot run (see below).
- Linux, macOS or Windows.

Always install into a virtual environment:

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install "ducta[spark]"
ducta --version
```

With conda: `conda create -n ducta python=3.12 && conda activate ducta`, then `pip install`.

## Extras

The core package runs configuration, validation and pandas-only work. Everything
else is an extra — install only what the project needs:

| Extra | Adds | Needed for |
|---|---|---|
| `spark` | pyspark, pyarrow | running Spark pipelines locally (most projects) |
| `delta` | delta-spark | `format: delta`, merge writes, time travel |
| `api` | FastAPI, uvicorn, SQLAlchemy, GitPython… | `ducta ui`, `ducta server` |
| `database` | SQLAlchemy and Postgres/SQLite drivers | persisting server history in a database |
| `mlops` | mlflow, scikit-learn, numpy, scipy, optuna | ML pipelines, `ducta experiment`, `ducta model` |
| `boost` | xgboost, lightgbm | gradient-boosting models, native model formats |
| `ai` | httpx, anthropic, keyring | `ducta ai` (also needs `api`) |
| `databricks` | databricks-connect | `mode: databricks` |
| `monitoring` | prometheus-client | metrics export |
| `all` | every extra above except `databricks` | |

```bash
pip install "ducta[spark,delta,mlops]"
```

A missing extra shows up as `No module named '<package>'` and exit code **1**
from `ducta start`, with the `pip install` to run.
`python3 scripts/check_env.py` lists which extras are importable.

## Check the installation

```bash
python3 scripts/check_env.py           # versions, extras, Java, warnings — JSON
ducta --version
ducta template --list-templates
```

`check_env.py` asks the Python behind the `ducta` command, not the one running the
script, so it works when `python3` is a different interpreter.

## Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `ducta: command not found` | The environment is not active, or its scripts folder is not on `PATH`. | Activate the venv/conda env; or run `python -m pip show ducta` to see where it is. |
| `No module named 'pyspark'` / exit code 1 | The `spark` extra is missing. | `pip install "ducta[spark]"` in the same environment. |
| `JAVA_GATEWAY_EXITED` / "Java gateway process exited" | No JDK, or an incompatible one. | Install a JDK (17 recommended for PySpark 3.5) and set `JAVA_HOME`. |
| Arrow errors on Java 21 (`UnsupportedOperationException`, `sun.misc.Unsafe`, `DirectByteBuffer`) | PySpark 3.5's bundled Arrow cannot run on JDK 21+. | Use JDK 17, or add `spark.sql.execution.arrow.pyspark.enabled: "false"` under `settings.spark_config`. Scoring with `mapInPandas` falls back to a slower row path. |
| Wheels fail to build on Apple Silicon | An x86 Python under Rosetta. | Use an arm64 Python. |
| Behind a corporate proxy | pip cannot reach PyPI. | Set `HTTPS_PROXY`, or `pip install --proxy …`. |

## Upgrading

`pip install --upgrade "ducta[...]"`, then `ducta config validate` on every
environment of each project: new versions can add checks that report problems an
older version accepted.
