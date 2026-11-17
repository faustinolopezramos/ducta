# Ducta Test Suite

Executable tests for every module. The suite is **engine-light**: almost every
test exercises pure Python logic (configuration parsing and validation,
dependency resolution, security sanitizers, data-quality checks over pandas,
MLOps bookkeeping, JWT/auth, SSRF guards) and runs **without a PySpark/JVM
environment**. Tests that genuinely need Spark are marked `@pytest.mark.spark`
and skip automatically when `pyspark` is absent; tests that touch the network
are marked `network`.

## Running

```bash
# Everything, in one process
poetry run pytest

# A single module's suite
poetry run pytest tests/core
poetry run pytest tests/check tests/mlrun tests/stream tests/console tests/server

# With coverage
poetry run pytest --cov=ducta --cov-report=term-missing
```

`pyproject.toml` sets `pythonpath = ["src", "server/src", "."]`, so tests always
run against the local working copy (the engine and the server package) regardless
of any editable install.

## Layout

| Path | Module under test | Focus |
|------|-------------------|-------|
| `tests/core/` | `ducta.core` | dependency DAG resolution, retry policy, sweep expansion, **Run Certificate** hashing/signing/tamper-detection, executors, secure module import |
| `tests/setting/` | `ducta.setting` | the strict project schema, loaders, `Context`, settings and environment variables |
| `tests/gate/` | `ducta.gate` | readers, writers, connections, SQL sanitizer, JDBC drivers |
| `tests/check/` | `ducta.check` | `DFAdapter` (pandas), built-in quality checks, `QualityGateEvaluator` scoring and blocking |
| `tests/mlrun/` | `ducta.mlrun` | data fingerprinting, reproducible splits, `MLOpsConfig`, the model registry, hyperparameter search |
| `tests/stream/` | `ducta.stream` | the plan, topological sort and cycle detection, checkpoint paths, `QueryHealthMonitor`, restarts, the journal |
| `tests/console/` | `ducta.console` | CLI parsers and commands, date parsing, exit codes |
| `tests/runs/` | `ducta.runs` | run records, the run ledger, failure diagnosis, the run table |
| `tests/project_store/` | `ducta.project_store` | reading and writing a project's files, draft validation, template extraction |
| `tests/ai/` | `ducta.ai` | providers over a mock transport, the draft loop, the Architect and Sentinel agents |
| `tests/skill/` | `ducta.skills` | the agent skill and its evals |
| `tests/server/` | `ducta_server` (the `ducta-server` package) | routes and RBAC, auth (bcrypt + JWT), SSRF guards, execution manager, schedules, `/health` |
| `tests/integration/` | engine end to end | pipeline runs, Delta merge, fingerprints, I/O round trips (need Spark) |
| `tests/test_*.py` | the package as a whole | architecture (import rules), public API, server/engine split, packaging, runtime checks |

## Environment notes

- Required test deps: `poetry install --with server` (the dev group plus the web
  server's dependencies, which `tests/server/` needs: FastAPI, SQLAlchemy, PyJWT,
  bcrypt…). The engine's tests need only the dev group.
- Optional deps that gate some tests: `pyspark`, `delta-spark`, `polars`,
  `sqlglot`, `mlflow` (absent → the relevant paths are skipped or exercised via
  their pure-Python fallbacks).
- Fixtures that write data use CSV (parquet needs `pyarrow`/`fastparquet`).

## A note on the `setting`/`gate` suites

Their `conftest.py` files install stand-ins for **missing** optional packages
(`pyspark`, `polars`…) so the modules import; a package that is installed is
never replaced. Run in one process with the real dependencies installed, the whole
suite passes.
