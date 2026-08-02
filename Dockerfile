# syntax=docker/dockerfile:1

# ==============================================================================
# Stage 1: ui-build — compile the React/Vite frontend to static files.
# The FastAPI server serves these from `ducta/ui/dist` (see ducta.api.main),
# so `ducta ui` inside the container yields the SAME single-origin app (UI +
# API on one port) that the CLI launches natively. Node lives only in this
# throwaway stage — the runtime image never ships a JS toolchain.
# ==============================================================================
FROM node:20-slim AS ui-build

WORKDIR /ui
# Install deps against the lockfile first for layer caching.
COPY src/ducta/ui/package.json src/ducta/ui/package-lock.json ./
RUN npm ci
# Then the sources, and build (tsc -b && vite build → /ui/dist).
COPY src/ducta/ui/ ./
RUN npm run build

# ==============================================================================
# Stage 2: builder — resolve and install the Python package + its extras.
# ==============================================================================
FROM continuumio/miniconda3:23.10.0-1 AS builder

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_NO_CACHE_DIR=1

# build-essential is a safety net for arm64: a handful of transitive deps may
# still ship only as sdists for aarch64 and need a compiler. It lives only in
# this throwaway builder stage, so the runtime image stays lean.
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN conda create -y -n ducta python=3.10 && conda clean -ya
ENV PATH=/opt/conda/envs/ducta/bin:$PATH

RUN pip install "poetry>=1.8,<3.0" poetry-plugin-export

WORKDIR /build
COPY pyproject.toml poetry.lock README.md ./
COPY src ./src

# Build a real (non-editable) wheel, then install it with its extras plus
# the versions pinned in poetry.lock as constraints, so the runtime image
# gets exactly what was resolved — no ad-hoc PyPI resolution at deploy time.
RUN poetry export --extras "spark api mlops" --without-hashes -o /tmp/constraints.txt \
 && poetry build -f wheel -o /tmp/dist \
 && WHEEL="$(ls /tmp/dist/*.whl)" \
 && pip install --no-cache-dir -c /tmp/constraints.txt "${WHEEL}[spark,api,mlops]"

# ==============================================================================
# Stage 3: runtime — lean image with only the JRE, the conda env built above,
# the compiled UI, and a non-root user. No build tools, no dev dependencies,
# no source tree, no Node.
# ==============================================================================
FROM continuumio/miniconda3:23.10.0-1 AS runtime

# JAVA_HOME points at a stable, architecture-independent symlink created below.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    JAVA_HOME=/opt/java \
    PATH=/opt/conda/envs/ducta/bin:$PATH \
    PYTHONUNBUFFERED=1

# Install the headless JRE and expose it at a fixed path regardless of arch.
# The Debian package installs to /usr/lib/jvm/java-11-openjdk-<arch> (amd64 or
# arm64); we resolve that real directory from the `java` binary and symlink it
# to /opt/java (= JAVA_HOME). This is what lets PySpark start on both x86-64 and
# Apple-Silicon/arm64 hosts without editing the Dockerfile per platform.
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends openjdk-11-jre-headless && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sfn "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java && \
    "$JAVA_HOME/bin/java" -version

COPY --from=builder /opt/conda/envs/ducta /opt/conda/envs/ducta

# Drop the compiled UI where the installed package expects it
# (ducta.api.main._UI_DIR = <package>/ui/dist). With this present the server
# serves the SPA at "/" and the API under "/api" on the same port.
COPY --from=ui-build /ui/dist /opt/conda/envs/ducta/lib/python3.10/site-packages/ducta/ui/dist

RUN useradd --create-home --uid 1000 --shell /bin/bash ducta
WORKDIR /ducta
RUN mkdir -p /ducta/data && chown -R ducta:ducta /ducta
USER ducta

EXPOSE 8000 4040

# Healthcheck uses the bundled Python (no curl/wget dependency), so it behaves
# identically on every host platform.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# Launch the same way the CLI does (`ducta ui`): serves the React UI + API on
# one port. --no-browser because there is no browser in a container; --host
# 0.0.0.0 so the port is reachable from the host.
ENTRYPOINT ["ducta"]
CMD ["ui", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]

# ==============================================================================
# Stage 4: dev — a batteries-included contributor environment (miniconda).
#
# This is what a collaborator uses to work on Ducta WITHOUT installing Python,
# Java, Spark or anything else on their machine: every dependency is already in
# the conda env, the project is installed *editable*, and docker-compose mounts
# their local ./src over /workspace/src so edits are live (the API hot-reloads).
# Built only when the compose dev override selects `target: dev`.
# ==============================================================================
FROM continuumio/miniconda3:23.10.0-1 AS dev

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    JAVA_HOME=/opt/java \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# JRE (for the Spark paths) + a compiler (arm64 sdists) + git, resolved to a
# stable, architecture-independent JAVA_HOME just like the runtime stage.
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        build-essential openjdk-11-jre-headless git && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    ln -sfn "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java

# One conda env for the project; Poetry installs straight into it (no nested
# virtualenv) so `python`, `pytest` and `ducta` all resolve without activation.
RUN conda create -y -n ducta python=3.10 && conda clean -ya
ENV PATH=/opt/conda/envs/ducta/bin:$PATH
RUN pip install --no-cache-dir "poetry>=1.8,<3.0" && poetry config virtualenvs.create false

WORKDIR /workspace
# Deps first (cached across code changes), then the project installs editable.
# Tests are provided at runtime by the compose bind-mount (./tests), so they are
# not copied here (and .dockerignore keeps them out of the build context).
COPY pyproject.toml poetry.lock README.md ./
COPY src ./src
RUN poetry install --with dev --extras "spark api mlops"

# Serve the compiled UI (if the contributor has built src/ducta/ui/dist) so the
# same single-origin app is available in dev too; harmless when absent.
EXPOSE 8000 4040

# Hot-reloading API server. The compose dev override mounts ./src over
# /workspace/src, so saving a file reloads the server. Run tests with:
#   docker compose run --rm ducta pytest
CMD ["uvicorn", "ducta.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/workspace/src"]
