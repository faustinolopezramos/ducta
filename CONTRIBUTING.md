# Contributing to Ducta

Welcome! This guide takes you from **zero** to **making and testing a change**,
assuming you know nothing about the project yet. Read the first two sections,
then pick **one** of the two setup paths.

> Using Ducta (not changing it)? You don't need this repo — `pip install ducta`.
> This guide is for **contributors** working on Ducta's source.

---

## 1. What Ducta is (30 seconds)

Ducta is a Python framework for building and running data pipelines (batch,
streaming, ML). A contributor typically touches:

- **`src/ducta/`** — the Python package (CLI, pipeline engine, API server…).
- **`src/ducta/ui/`** — the web interface (React + Vite). Optional to build.
- **`tests/`** — the test suite.

Dependencies are managed with **Poetry** (`pyproject.toml` + `poetry.lock` are
the source of truth — there is no hand-maintained `requirements.txt`).

---

## 2. Choose your setup path

|  | **Path A — Docker** | **Path B — Native (Poetry)** |
|---|---|---|
| Install on your machine | Just Docker Desktop | Python, Poetry (Node/Java if needed) |
| Keeps your machine clean | ✅ Everything lives in the container | ✅ if you use an in-project `.venv` (below) |
| Best when | You want zero local setup / native install fails on your OS | You want the fastest edit loop and are comfortable with Python tooling |

Both give you a live edit-and-test loop. **If unsure, use Path A.**

---

## Path A — Docker (nothing to install but Docker)

**1. Install Docker Desktop** (once): <https://www.docker.com/products/docker-desktop/>
(macOS: `brew install --cask docker`, then open it once). No Python, Java or
Node needed — they all live inside the container.

**2. Get the code and start it:**
```bash
git clone <repo-url> && cd ducta
docker compose up --build      # first time (builds the dev environment)
docker compose up              # afterwards
```
Open <http://localhost:8000/>. Edit files under `src/` on your machine — the
server **reloads automatically**.

**3. Run tests / a shell in the same environment:**
```bash
docker compose run --rm ducta pytest
docker compose run --rm ducta bash      # a shell with everything installed
```

**4. Clean up completely when you're done** (leaves your machine spotless):
```bash
docker compose down --rmi all -v
```

> Want a production-style run (baked image, no live editing)? Use the base file
> only: `docker compose -f docker-compose.yml up --build`.

---

## Path B — Native with Poetry

### B.1 Install the tools (once)

macOS (Homebrew) — Linux/Windows: install the equivalents.

| Tool | Needed for | macOS install |
|---|---|---|
| **Python 3.10–3.13** | everything | `brew install python@3.11` |
| **Poetry** | dependency & env manager | `brew install pipx && pipx ensurepath && pipx install poetry` |
| **Node** | building the web UI (optional) | `brew install node` |
| **Java 11** | running Spark pipelines (optional) | `brew install openjdk@11` |

> Windows: prefer **WSL2** so Spark works without `winutils`. Core/CLI/API work
> fine on plain Windows too.

### B.2 Keep everything inside the project (recommended)

So dependencies never scatter across your machine, tell Poetry to put the
virtual environment **inside the project**:
```bash
poetry config virtualenvs.in-project true   # once, global
```
Now each project keeps a self-contained `.venv/` folder — delete the project
folder and every dependency goes with it.

### B.3 Install

```bash
git clone <repo-url> && cd ducta
poetry install          # creates ./.venv, installs deps + dev tools, editable
```
You do **not** create a virtual environment yourself — `poetry install` does it
and installs the project in **editable** mode (your edits to `src/` apply
instantly). Pick the scope you need:

| Command | Installs |
|---|---|
| `poetry install` | Core + dev tools + tests |
| `poetry install -E api` | + the web/API backend |
| `poetry install --all-extras` | Everything (Spark, MLOps…) — needs Java |

### B.4 Build the web UI (only if you'll use it)

```bash
cd src/ducta/ui && npm ci && npm run build && cd ../../..
```
The API serves the compiled output. (For live UI development use `npm run dev`
instead of `build`.)

### B.5 Run and test

Everything runs **inside Poetry's environment** — prefix with `poetry run`
(or run `poetry shell` once and drop the prefix):
```bash
poetry run pytest                 # run the tests (tests/)
poetry run ducta --help           # the CLI, using your code
poetry run ducta ui --no-browser  # UI + API → http://localhost:8000
```
> Don't have Spark installed? Tests marked `spark` skip automatically — the rest
> still run.

---

## 3. Make a change → verify → propose it

The loop is the same whichever path you chose:

```bash
git checkout -b my-change          # 1. branch off

# 2. edit code under src/ … then verify:
#    (Docker: prefix each with `docker compose run --rm ducta`)
poetry run pytest                  #    tests pass
poetry run ruff format .           #    auto-format
poetry run ruff check .            #    lint
poetry run mypy src                #    type-check

git add -A && git commit -m "Describe your change"
git push origin my-change          # 3. open a Pull Request on GitHub
```

Keep changes focused, add or update tests for what you touch, and make sure the
four checks above are green before opening the PR.

---

## 4. Keeping your machine clean

| Path | Remove everything |
|---|---|
| Docker | `docker compose down --rmi all -v` (and `docker system prune -a` for the rest) |
| Native | delete the project folder (deps live in `./.venv` and `src/ducta/ui/node_modules`) |

Poetry's download cache is shared across projects and safe to clear anytime:
`poetry cache clear --all pypi`.

---

## 5. Where to look next

- **Docs:** `docs/` (build with `poetry run sphinx-build docs docs/_build`).
- **Per-module guides:** `src/ducta/<module>/README.md`.
- **The UI:** `src/ducta/ui/README.md`.
- **Changelog / status:** `CHANGELOG.md` (project is in alpha — things move).

Questions or stuck? Open an issue describing your OS, the command you ran, and
the full error.

---

## 6. License

Ducta is licensed under [Apache-2.0](LICENSE). By submitting a pull request,
you agree that your contribution is licensed under those same terms — this is
what Apache-2.0 itself already says in §5 ("Submission of Contributions"), so
there is no separate CLA to sign.
