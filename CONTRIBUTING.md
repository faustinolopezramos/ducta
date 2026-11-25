# Contributing to Ducta

Welcome! This guide takes you from **zero** to **a change that passes CI**,
assuming you know nothing about the project yet.

> Using Ducta (not changing it)? You don't need this repo — `pip install ducta`.
> This guide is for **contributors** working on Ducta's source.

**Already know Poetry?** The short version:

```bash
git clone <repo-url> && cd ducta
poetry install --with server                     # engine + server deps + dev tools
poetry run pip install --no-deps -e ./server     # the ducta-server command, from your code
poetry run pre-commit install                    # lint, format and checks on commit/push
poetry run pytest                                # Spark tests skip without pyspark
```

---

## 1. What is where

Ducta is a Python framework for building and running data pipelines (batch,
streaming, ML). It ships as **two packages from this one repository, always at the
same version**:

| Path | What it is |
|---|---|
| `src/ducta/` | The `ducta` package: the pipeline engine and the `ducta` CLI. One folder per module (`setting`, `gate`, `check`, `mlrun`, `stream`, `core`, `console`, `ai`…), most with a `README.md` |
| `server/` | The `ducta-server` package: the API (`server/src/ducta_server/`) and the web app (`server/ui/`, React + Vite) |
| `tests/` | The tests of both; `tests/README.md` maps each folder to its module |
| `docs/` | The Sphinx documentation |
| `scripts/` | Maintenance scripts (the skill's CLI reference, the OpenAPI dump…) |
| `.github/workflows/` | CI (`ci.yml`), the dependency compatibility probe and the release |

Dependencies are managed with **Poetry**: `pyproject.toml` + `poetry.lock` are
the source of truth (there is no hand-maintained `requirements.txt`).

---

## 2. Choose your setup path

|  | **Path A — Docker** | **Path B — Native (Poetry)** |
|---|---|---|
| Install on your machine | Docker Desktop | Python, Poetry (Node and Java if needed) |
| Keeps your machine clean | ✅ everything lives in the container | ✅ with an in-project `.venv` (below) |
| Web app | not built (API only) unless you build it — see A.3 | `npm run build` once (B.4) |
| Best when | native install fails on your OS, or you only touch Python | the fastest edit loop, or you work on the web app |

Both give you a live edit-and-test loop. **If you will work on the web app, use Path B.**

---

## Path A — Docker

**A.1 Install Docker Desktop** (once): <https://www.docker.com/products/docker-desktop/>
(macOS: `brew install --cask docker`, then open it once). Python and Java live
inside the container.

**A.2 Get the code and start it:**

```bash
git clone <repo-url> && cd ducta
docker compose up --build        # first time (builds the dev image; several minutes)
docker compose up                # afterwards
```

It runs on your machine only, with authentication off. The API answers on
<http://localhost:8000/> — interactive docs at
<http://localhost:8000/docs>, liveness at `/health`. Edit files under `src/` or
`server/src/` on your machine and the server **reloads automatically** (they are
mounted into the container).

**A.3 The web app.** It is compiled from `server/ui/` and not kept in git, and the
dev image does not build it. Build it once on your machine (needs Node, see B.4)
and the container serves it on the next reload:

```bash
cd server/ui && npm ci && npm run build && cd ../..
```

**A.4 Tests or a shell in the same environment:**

```bash
docker compose run --rm ducta pytest
docker compose run --rm ducta bash      # a shell with everything installed
```

**A.5 Clean up completely when you're done:**

```bash
docker compose down --rmi all -v
```

> The deployable server (the `server` image with the web app built in, accounts,
> PostgreSQL) is `docker-compose.yml` alone: copy `.env.example` to `.env`, fill it
> in, and run `docker compose -f docker-compose.yml --profile accounts up --build`.
> It refuses to start without credentials of your own. More in
> `docs/deployment_guide.rst`.

---

## Path B — Native with Poetry

### B.1 Install the tools (once)

macOS (Homebrew) — Linux/Windows: install the equivalents.

| Tool | Needed for | macOS install |
|---|---|---|
| **Python 3.11–3.14** | everything (3.14 needs Spark 4) | `brew install python@3.13` |
| **Poetry 2** | dependency & env manager | `brew install pipx && pipx ensurepath && pipx install poetry` |
| **Node 20+** | building the web app (optional) | `brew install node` |
| **Java 17** | running Spark (optional; Spark 4 needs 17 or 21; on 21, PySpark 3.5 cannot use Arrow) | `brew install openjdk@17` |

> Windows: prefer **WSL2** so Spark works without `winutils`. The engine, CLI and
> server work on plain Windows too.

### B.2 Keep everything inside the project (recommended)

So dependencies never scatter across your machine, tell Poetry to put the
virtual environment **inside the project**:

```bash
poetry config virtualenvs.in-project true   # once, global
```

Each project then keeps a self-contained `.venv/` folder: delete the project
folder and every dependency goes with it.

### B.3 Install

```bash
git clone <repo-url> && cd ducta
poetry install --with server                  # creates ./.venv: engine (editable), server deps, dev tools
poetry run pip install --no-deps -e ./server  # the ducta-server package, editable
```

You do **not** create a virtual environment yourself — `poetry install` does it,
and both packages are installed in **editable** mode: your edits to `src/` and
`server/src/` apply instantly. Add what you need:

| Command | Adds |
|---|---|
| `poetry install --extras spark --with server` | PySpark, to run pipelines and the `spark` tests (needs Java) |
| `poetry install --extras all --with server` | Everything CI installs (Spark, Delta, MLOps, AI…). Not `--all-extras`: it adds `databricks`, which replaces PySpark |
| `poetry install --with docs` | Sphinx, to build `docs/` |

`poetry install` without `--with server` is enough for the engine alone, but
`tests/server/` then cannot import the server's dependencies.

### B.4 Build the web app (only if you'll use it)

```bash
cd server/ui && npm ci && npm run build && cd ../..
```

The build lands in `server/src/ducta_server/ui_dist`, which the server serves. For
live web-app development, run `npm run dev` in `server/ui/` next to the server
instead.

### B.5 Run and test

Everything runs **inside Poetry's environment** — prefix with `poetry run`, or
activate it once with `eval "$(poetry env activate)"` and drop the prefix:

```bash
poetry run pytest                         # the whole suite
poetry run pytest tests/check             # one module
poetry run pytest -m "not spark"          # skip the tests that start Spark
poetry run ducta --help                   # the CLI, from your code
poetry run ducta-server --no-browser      # web app + API → http://localhost:8000 (needs B.3 and B.4)
```

Tests marked `spark` skip on their own when `pyspark` is not installed.

---

## 3. Make a change → verify → propose it

```bash
git checkout -b my-change                                  # 1. branch off

# 2. edit … then verify, with the commands CI runs
#    (Docker: prefix each with `docker compose run --rm ducta`)
poetry run pytest                                          # tests pass
poetry run ruff format src server/src tests scripts        # format
poetry run ruff check src server/src tests scripts         # lint
poetry run mypy src/ducta server/src/ducta_server          # type-check (engine + server)

git add <files> && git commit -m "Describe your change"
git push origin my-change                                  # 3. open a Pull Request
```

Keep changes focused, add or update tests for what you touch, and make sure the
four checks above are green before opening the PR.

`poetry run pre-commit install` (once) runs most of this for you: ruff, file
hygiene, secret detection, the skill's CLI reference, `poetry.lock` and the web
app's checks on every commit, and mypy on every push. Run `git` from the
environment where the dev dependencies are installed (the local hooks use the
`python` on your `PATH`). Formatting is `ruff format` only — do not add Black next
to it.

### Depending on what you touched

| You changed… | Also run / update |
|---|---|
| The web app (`server/ui/`) | `cd server/ui && npx tsc -b && npm run test:run && npm run lint && npm run ui:quality` |
| A CLI command or option | `poetry run python scripts/gen_skill_cli_reference.py` — regenerates the skill's `references/cli.md` (the commit hook fails until you do) |
| Dependencies in `pyproject.toml` | `poetry lock`, and commit `poetry.lock` with it |
| Documentation (`docs/`) | `poetry run sphinx-build -W --keep-going docs docs/_build/html` — CI fails on any warning |
| A configuration example in the docs or a README | `poetry run pytest tests/setting/test_doc_snippets_format2.py` — every project YAML example must validate against the schema |
| Something a user or operator notices | an entry under `## [Unreleased]` in `CHANGELOG.md`, and the docs that describe it |

### Rules the tests enforce

- **Module boundaries** (`tests/test_architecture.py`): no two packages import each
  other at module level; nothing in `ducta` imports the server (`ducta_server`); the
  engine (`setting`, `gate`, `check`, `mlrun`, `stream`, `core`, `project_store`,
  `runs`) does not import the CLI or the AI layer — it reports through
  `ducta.reporting`.
- **Public API** (`tests/test_public_api.py`): what `import ducta` exposes is a
  promise. Adding or removing a name there is a deliberate change, with a
  CHANGELOG entry.
- **The two packages** (`tests/test_server_split.py`):
  `ducta` works without `ducta-server` installed, and both carry the same version.

### What CI runs on a pull request

`ci.yml`: lint, format and mypy; the test suite on Python 3.11–3.14 with Spark 4.2
(and once with Spark 3.5); a clean install of the built wheels on every Python; both
Docker images; the web app (typecheck, tests, quality, lint); the docs build; and a
dependency audit.

### Security

Found a vulnerability? Do not open a public issue or PR: report it privately as
[SECURITY.md](SECURITY.md) explains. In your changes, never commit a `.env` or a
key, and keep secrets in environment variables — the server withholds its own
from pipeline runs (`src/ducta/server_secrets.py`).

---

## 4. When something goes wrong

| Symptom | Likely cause |
|---|---|
| `ducta` behaves like an older release | another environment's `ducta` is first on your `PATH`: use `poetry run ducta`, or check `pip show ducta` |
| `http://localhost:8000/` answers `404`, `/docs` works | the web app is not built: B.4 |
| Docker: the server exits with `jwt_secret_key must be overridden in production` | you ran `docker-compose.yml` alone (the deployable server) without a filled-in `.env`; for development run `docker compose up` (A.2) |
| Spark tests fail with a Java error, or Arrow warns of leaked memory | no JDK, or JDK 21 with PySpark 3.5: install JDK 17 (B.1) |
| Spark stopped working after installing extras | `--all-extras` installed `databricks-connect`, which replaces PySpark: reinstall with `--extras all` (B.3) |

---

## 5. Keeping your machine clean

| Path | Remove everything |
|---|---|
| Docker | `docker compose down --rmi all -v` (and `docker system prune -a` for the rest) |
| Native | delete the project folder (dependencies live in `./.venv` and `server/ui/node_modules`) |

Poetry's download cache is shared across projects and safe to clear anytime:
`poetry cache clear --all pypi`.

---

## 6. Where to look next

- **Docs:** `docs/` (`poetry install --with docs`, then `poetry run sphinx-build docs docs/_build/html`).
- **Per-module guides:** `src/ducta/<module>/README.md`.
- **The server and the web app:** `server/src/ducta_server/README.md`, `server/ui/README.md`.
- **Tests:** `tests/README.md` (layout, optional dependencies, markers).
- **Security model:** `SECURITY.md`.
- **Changelog / status:** `CHANGELOG.md` (the project is in alpha — things move).

Questions or stuck? Open an issue with your OS, the command you ran, and the full
error.

---

## 7. License

Ducta is licensed under [Apache-2.0](LICENSE). By submitting a pull request,
you agree that your contribution is licensed under those same terms — this is
what Apache-2.0 itself already says in §5 ("Submission of Contributions"), so
there is no separate CLA to sign.
