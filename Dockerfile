# syntax=docker/dockerfile:1

# Two images, from the two packages this repository builds:
#
#   docker build --target cli    -t ducta:latest .         # `ducta`: engine + CLI
#   docker build --target server -t ducta-server:latest .  # `ducta-server`: + API and web app
#
# The server image is the CLI image plus the server: `ducta` works in both.

# Base image for the Python stages. continuumio/miniconda3 stopped at 26.7; this is
# its successor. Debian 13 underneath: JDK 21 (Spark 3.5 and 4 both run on it).
ARG CONDA_IMAGE=anaconda/miniconda:26.9.4

# ==============================================================================
# Stage: ui-build — compile the React/Vite frontend to static files.
# `npm run build` writes them into the server package (server/src/ducta_server/
# ui_dist), which the ducta-server wheel ships and ducta_server.main serves, so the
# container yields the same single-origin app (UI + API on one port) as a native
# install. Node lives only in this throwaway stage.
# ==============================================================================
FROM node:20-slim AS ui-build

WORKDIR /build/server/ui
# Install deps against the lockfile first for layer caching.
COPY server/ui/package.json server/ui/package-lock.json ./
RUN npm ci
# Then the sources, and build (tsc -b && vite build → /build/server/src/ducta_server/ui_dist).
COPY server/ui/ ./
RUN npm run build

# ==============================================================================
# Stage: pybuild — conda, a compiler and Poetry: what the stages below build with.
# build-essential is a safety net for arm64: a handful of transitive deps may still
# ship only as sdists for aarch64 and need a compiler. It never reaches an image.
# ==============================================================================
FROM ${CONDA_IMAGE} AS pybuild

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ==============================================================================
# Stage: wheels — build both wheels once, and the constraints from poetry.lock.
# Poetry lives in its own environment here, never in an image's.
# ==============================================================================
FROM pybuild AS wheels

RUN conda create -y -n build -c conda-forge --override-channels python=3.12 && conda clean -ya
ENV PATH=/opt/miniconda3/envs/build/bin:$PATH
RUN pip install "poetry>=1.8,<3.0" poetry-plugin-export

WORKDIR /build
COPY pyproject.toml poetry.lock README.md LICENSE ./
COPY src ./src
COPY server/pyproject.toml server/README.md server/LICENSE ./server/
COPY server/src ./server/src
COPY --from=ui-build /build/server/src/ducta_server/ui_dist ./server/src/ducta_server/ui_dist

# Real (non-editable) wheels; the versions pinned in poetry.lock as constraints, so
# the images get exactly what was resolved — no ad-hoc resolution at deploy time.
RUN poetry export --extras "spark mlops" --with server --without-hashes -o /dist/constraints.txt \
 && poetry build -f wheel -o /dist \
 && (cd server && poetry build -f wheel -o /dist)

# ==============================================================================
# Stages: env-cli / env-server — each image's Python environment, installed at the
# path the image runs it from (/opt/miniconda3/envs/ducta). pip writes that absolute
# path into every command it installs (`#!/opt/.../envs/ducta/bin/python`), so an
# environment must never be built under one path and copied to another.
# ==============================================================================
FROM pybuild AS env-cli

RUN conda create -y -n ducta -c conda-forge --override-channels python=3.12 && conda clean -ya
ENV PATH=/opt/miniconda3/envs/ducta/bin:$PATH
COPY --from=wheels /dist /dist
RUN pip install --no-cache-dir -c /dist/constraints.txt \
      "$(ls /dist/ducta-[0-9]*.whl)[spark,mlops]"

FROM env-cli AS env-server

RUN pip install --no-cache-dir -c /dist/constraints.txt "$(ls /dist/ducta_server-*.whl)"

# ==============================================================================
# Stage: base — the JRE and a non-root user, shared by both images. No build
# tools, no dev dependencies, no source tree, no Node.
# ==============================================================================
FROM ${CONDA_IMAGE} AS base

# JAVA_HOME points at a stable, architecture-independent symlink created below.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    JAVA_HOME=/opt/java \
    PATH=/opt/miniconda3/envs/ducta/bin:$PATH \
    PYTHONUNBUFFERED=1

# Install the headless JRE and expose it at a fixed path regardless of arch.
# The Debian package installs to /usr/lib/jvm/java-21-openjdk-<arch> (amd64 or
# arm64); we resolve that real directory from the `java` binary and symlink it
# to /opt/java (= JAVA_HOME). This is what lets PySpark start on both x86-64 and
# Apple-Silicon/arm64 hosts without editing the Dockerfile per platform.
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends openjdk-21-jre-headless && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sfn "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java && \
    "$JAVA_HOME/bin/java" -version

RUN useradd --create-home --uid 1000 --shell /bin/bash ducta
WORKDIR /ducta
RUN mkdir -p /ducta/data && chown -R ducta:ducta /ducta

# ==============================================================================
# Image: cli — `ducta` (engine + CLI). Mount a project and run it:
#   docker run --rm -v "$PWD:/ducta/project" -w /ducta/project ducta start -p <pipeline>
# ==============================================================================
FROM base AS cli

COPY --from=env-cli /opt/miniconda3/envs/ducta /opt/miniconda3/envs/ducta
USER ducta
EXPOSE 4040
ENTRYPOINT ["ducta"]
CMD ["--help"]

# ==============================================================================
# Image: server — `ducta-server`: the API and the web app on one port, plus `ducta`.
# ==============================================================================
FROM base AS server

COPY --from=env-server /opt/miniconda3/envs/ducta /opt/miniconda3/envs/ducta
USER ducta

EXPOSE 8000 4040

# Healthcheck uses the bundled Python (no curl/wget dependency), so it behaves
# identically on every host platform.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# --no-browser because there is no browser in a container; --host 0.0.0.0 so the
# port is reachable from the host (which then needs AUTH_ENABLED, or
# --allow-unauthenticated when the exposure is intended).
ENTRYPOINT ["ducta-server"]
CMD ["--host", "0.0.0.0", "--port", "8000", "--no-browser"]

# ==============================================================================
# Stage: dev — a batteries-included contributor environment (miniconda).
#
# This is what a collaborator uses to work on Ducta WITHOUT installing Python,
# Java, Spark or anything else on their machine: every dependency is already in
# the conda env, both packages are on the path from the source tree, and
# docker-compose mounts ./src and ./server/src so edits are live (the API
# hot-reloads). Built only when the compose dev override selects `target: dev`.
# ==============================================================================
FROM ${CONDA_IMAGE} AS dev

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    JAVA_HOME=/opt/java \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# JRE (for the Spark paths) + a compiler (arm64 sdists) + git, resolved to a
# stable, architecture-independent JAVA_HOME just like the base stage.
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        build-essential openjdk-21-jre-headless git && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    ln -sfn "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java

# One conda env for the project; Poetry installs straight into it (no nested
# virtualenv) so `python`, `pytest` and `ducta` all resolve without activation.
RUN conda create -y -n ducta -c conda-forge --override-channels python=3.12 && conda clean -ya
ENV PATH=/opt/miniconda3/envs/ducta/bin:$PATH
RUN pip install --no-cache-dir "poetry>=1.8,<3.0" && poetry config virtualenvs.create false

WORKDIR /workspace
# Deps first (cached across code changes), then the engine installs editable and
# the server from its source tree (its dependencies come from the `server` group).
# Tests are provided at runtime by the compose bind-mount (./tests), so they are
# not copied here (and .dockerignore keeps them out of the build context).
COPY pyproject.toml poetry.lock README.md LICENSE ./
COPY src ./src
COPY server/pyproject.toml server/README.md server/LICENSE ./server/
COPY server/src ./server/src
RUN poetry install --with dev,server --extras "spark mlops" \
 && pip install --no-cache-dir --no-deps -e ./server

EXPOSE 8000 4040

# Hot-reloading API server. The compose dev override mounts ./src and ./server/src,
# so saving a file reloads the server. Run tests with:
#   docker compose run --rm ducta pytest
CMD ["uvicorn", "ducta_server.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/workspace/src", "--reload-dir", "/workspace/server/src"]
