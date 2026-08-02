# Ducta Test Suite

Real, executable unit tests for the Ducta modules. The suite is **engine-light**:
almost every test exercises pure Python logic (config parsing/validation,
dependency resolution, security sanitizers, data-quality checks over pandas,
MLOps bookkeeping, JWT/auth, SSRF guards) and runs **without a PySpark/JVM
environment**. Tests that genuinely need Spark are marked `@pytest.mark.spark`
and skip automatically when `pyspark` is absent.

## Running

```bash
# Everything
poetry run pytest

# A single module's suite
poetry run pytest tests/core
poetry run pytest tests/check tests/mlrun tests/stream tests/console tests/api

# With coverage
poetry run pytest --cov=ducta --cov-report=term-missing
```

`pyproject.toml` sets `pythonpath = ["src"]`, so tests always run against the
local working copy regardless of any editable install.

## Layout

| Path | Module under test | Focus |
|------|-------------------|-------|
| `tests/core/` | `ducta.core` | dependency DAG resolution, retry policy, sweep expansion, **Run Certificate** hashing/signing/tamper-detection, secure module import |
| `tests/check/` | `ducta.check` | `DFAdapter` (pandas), built-in quality checks, `QualityGateEvaluator` scoring & blocking |
| `tests/mlrun/` | `ducta.mlrun` | data fingerprinting, reproducible splits (random/temporal/group/stratified), `MLOpsConfig`, `FileLock`, hyperparameter grids |
| `tests/stream/` | `ducta.stream` | topological sort + cycle detection, traversal-safe checkpoint paths, `QueryHealthMonitor`, error helpers |
| `tests/console/` | `ducta.console` | CLI argument validators, date parsing, exit codes |
| `tests/api/` | `ducta.api` | `AuthService` (bcrypt + JWT), **SSRF** host guards, production config guards, `/health` smoke test |
| `tests/setting/`, `tests/gate/` | `ducta.setting`, `ducta.gate` | pre-existing suites (see note below) |

## Environment notes

- Required test deps: `pytest`, `pandas`, `numpy`, `pydantic`, `jose`, `bcrypt`,
  `fastapi`, `sqlalchemy`, `pyyaml`.
- Optional deps that gate some tests: `pyspark`, `polars`, `sqlglot` (absent →
  the relevant paths are skipped or exercised via their pure-Python fallbacks).
- Fixtures that write data use CSV (parquet needs `pyarrow`/`fastparquet`).

## A note on the `setting`/`gate` suites

The `tests/setting/` and `tests/gate/` directories use an older mock-based
design (they inject fake `pydantic`/`pyspark`/`ducta.*` modules into
`sys.modules` at import time). That approach conflicts with the real-dependency
style used everywhere else, so a handful of those tests fail when the whole
suite runs in one process (real pydantic actually validates; import order
changes which Spark stub is bound). They are **not** part of the newly authored
suites and were already failing before. Converting them to the real-dependency
style is a recommended follow-up.
