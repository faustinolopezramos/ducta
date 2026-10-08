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
"""

# Serving: score data with a registered model.
#
# A node with ``ml_stage: serving`` names its model in the pipeline file
# (``model: {name: churn, stage: production}``, or an MLflow ``uri``). Ducta
# resolves that reference to one exact version when the run starts, downloads and
# hashes the artifact, loads it, and hands it to the node as ``ml_context.model``
# — with ``ml_context.model_ref`` saying exactly which model it is. The run
# certificate records the same facts, so "which model produced this output?" has
# a verifiable answer.
#
# A serving node without ``run`` uses :func:`predict`, which applies the model to
# its single input and adds the prediction as a column.

from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from ducta.setting.project_schema import ModelRef

#: Frameworks whose artifact is a pickle: loading one executes it.
PICKLE_FRAMEWORKS = frozenset({"sklearn", "scikit-learn", "pickle", "joblib", "custom"})
#: Frameworks Ducta loads itself. Any other is downloaded and left to the node's own
#: function, which finds it at ``ml_context.model_ref.local_path``.
LOADABLE_FRAMEWORKS = PICKLE_FRAMEWORKS | {"xgboost", "lightgbm", "mlflow_pyfunc", "spark-mllib"}


class ServingError(RuntimeError):
    """A serving node's model could not be resolved, verified, loaded or applied."""


@dataclass(frozen=True)
class ResolvedModel:
    """A model reference pinned to one exact version."""

    source: str
    name: str
    version: int
    uri: str
    framework: str
    stage_at_resolution: Optional[str] = None
    registered_sha256: Optional[str] = None
    input_schema: Optional[Dict[str, str]] = None


@dataclass
class ServingModel:
    """What a serving node is told about its model (``ml_context.model_ref``)."""

    ref: ModelRef
    resolved: ResolvedModel
    local_path: Optional[str] = None
    artifact_sha256: Optional[str] = None
    hash_source: Optional[str] = None
    model: Any = field(default=None, repr=False)

    @property
    def features(self) -> Optional[List[str]]:
        if self.ref.features:
            return list(self.ref.features)
        if self.resolved.input_schema:
            return list(self.resolved.input_schema)
        return None

    def evidence(self) -> Dict[str, Any]:
        """What the run certificate records about this model."""
        r = self.resolved
        return {
            "source": r.source,
            "name": r.name,
            "version": r.version,
            "stage_at_resolution": r.stage_at_resolution,
            "uri": r.uri,
            "framework": r.framework,
            "artifact_sha256": self.artifact_sha256,
            "hash_source": self.hash_source,
        }


# ── resolution ───────────────────────────────────────────────────────────────


def _registry_stage(stage: str) -> Any:
    from ducta.mlrun.model_registry import ModelStage

    return ModelStage(stage.capitalize())


def resolve_model(
    ref: ModelRef, *, registry: Any = None, mlflow_client: Any = None
) -> ResolvedModel:
    """Pin ``ref`` to one version. Reads metadata only; downloads nothing."""
    if ref.source == "mlflow":
        if mlflow_client is None:
            raise ServingError("model source: mlflow needs MLflow (pip install 'ducta[mlops]')")
        return _resolve_mlflow(ref, mlflow_client)
    if registry is None:
        raise ServingError(f"model '{ref.name}': no model registry is configured (settings.mlops)")
    from ducta.mlrun.exceptions import ModelNotFoundError

    try:
        if ref.version is not None:
            mv = registry.get_model_version(ref.name, ref.version)
        else:
            mv = registry.get_model_by_stage(ref.name, _registry_stage(str(ref.stage)))
    except ModelNotFoundError as e:
        wanted = f"version {ref.version}" if ref.version is not None else f"stage {ref.stage}"
        raise ServingError(
            f"model '{ref.name}' has no {wanted} in the registry — register it, or "
            f"promote a version to {ref.stage or 'that stage'} ({e})"
        ) from e
    stage = getattr(mv.metadata.stage, "value", mv.metadata.stage)
    return ResolvedModel(
        source="ducta",
        name=str(ref.name),
        version=int(mv.version),
        uri=mv.artifact_uri,
        framework=str(mv.metadata.framework).lower(),
        stage_at_resolution=str(stage).lower() if stage else None,
        registered_sha256=getattr(mv, "artifact_sha256", None),
        input_schema=mv.metadata.input_schema,
    )


def _resolve_mlflow(ref: ModelRef, client: Any) -> ResolvedModel:
    target = str(ref.uri)[len("models:/") :]
    if "@" in target:
        name, alias = target.split("@", 1)
        mv = client.get_model_version_by_alias(name, alias)
        stage: Optional[str] = f"@{alias}"
    else:
        name, _, version = target.partition("/")
        if not version.isdigit():
            raise ServingError(
                f"model uri '{ref.uri}': name a version (models:/{name}/3) or an alias "
                f"(models:/{name}@champion); MLflow 3 no longer resolves stages"
            )
        mv = client.get_model_version(name, version)
        stage = None
    version_number = int(mv.version)
    return ResolvedModel(
        source="mlflow",
        name=name,
        version=version_number,
        uri=f"models:/{name}/{version_number}",
        framework="mlflow_pyfunc",
        stage_at_resolution=stage,
    )


# ── download, verify, load ───────────────────────────────────────────────────


def artifact_digest(path: Path) -> str:
    """SHA-256 of a file, or of a directory's relative paths and contents in order."""
    h = hashlib.sha256()
    if path.is_file():
        files = [(path.name, path)]
    else:
        files = sorted((p.relative_to(path).as_posix(), p) for p in path.rglob("*") if p.is_file())
    for rel, p in files:
        if not path.is_file():
            h.update(rel.encode() + b"\0")
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return "sha256:" + h.hexdigest()


def _download(resolved: ResolvedModel, registry: Any, workdir: Path) -> Path:
    dest = workdir / f"{resolved.source}-{resolved.name}-v{resolved.version}"
    if resolved.source == "mlflow":
        import mlflow

        return Path(
            mlflow.artifacts.download_artifacts(artifact_uri=resolved.uri, dst_path=str(dest))
        )
    registry.storage.read_artifact(resolved.uri, str(dest))
    return dest


def _load_pickle(path: Path) -> Any:
    # Deserializing a pickle executes it. Every caller reaches this only after the
    # node opted in with model.trust_artifact: true — the same trust boundary
    # ArtifactValidator applies at registration (trust_artifact_source).
    try:
        import joblib  # handles plain pickles too
    except ImportError:  # pragma: no cover — joblib ships with scikit-learn
        import pickle

        with open(path, "rb") as f:
            return pickle.load(f)
    return joblib.load(path)


def _load_booster(path: Path, framework: str, trusted: bool) -> Any:
    """xgboost/lightgbm: the native format first (safe); a pickled estimator if trusted."""
    try:
        if framework == "xgboost":
            import xgboost as xgb

            booster = xgb.Booster()
            booster.load_model(str(path))
            return booster
        import lightgbm as lgb

        return lgb.Booster(model_file=str(path))
    except ImportError:
        raise
    except Exception as native_error:  # noqa: BLE001 — not the native format: maybe a pickle
        if not trusted:
            raise ServingError(
                f"{framework} artifact is not in the native format, and loading it as a "
                "pickle needs model.trust_artifact: true"
            ) from native_error
        return _load_pickle(path)


def _load_spark_ml(path: str) -> Any:
    """A saved Spark ML model, of whatever class its metadata names. Executes nothing."""
    import importlib
    import json

    from pyspark.sql import SparkSession

    spark = SparkSession.getActiveSession()
    if spark is None:
        raise ServingError("a spark-mllib model needs an active Spark session to load")
    meta = json.loads(spark.sparkContext.textFile(f"{path}/metadata").first())
    jvm_class = str(meta["class"])
    module_name, _, class_name = jvm_class.replace("org.apache.spark.ml", "pyspark.ml").rpartition(
        "."
    )
    if not module_name.startswith("pyspark.ml"):
        raise ServingError(f"'{jvm_class}' is not a Spark ML model class")
    try:
        model_cls = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError):
        # pyspark keeps most models one package up (pyspark.ml.classification, ...).
        model_cls = getattr(importlib.import_module(module_name.rsplit(".", 1)[0]), class_name)
    return model_cls.load(path)


def _spark_readable_path(registry: Any, resolved: ResolvedModel, local_path: Path) -> str:
    """Where Spark itself can read the artifact: a cluster cannot read the driver's
    temporary copy, but it can read the registry's own storage."""
    storage = getattr(registry, "storage", None)
    if storage is not None and hasattr(storage, "_get_volume_path"):
        return str(storage._get_volume_path(resolved.uri))
    if storage is not None and hasattr(storage, "_get_full_path"):
        return str(storage._get_full_path(resolved.uri))
    return str(local_path)


def load_model(
    resolved: ResolvedModel, local_path: Path, *, trust: bool, registry: Any = None
) -> Any:
    """Load a downloaded artifact. ``None`` for a framework the node loads itself."""
    framework = resolved.framework
    if framework == "spark-mllib":
        return _load_spark_ml(_spark_readable_path(registry, resolved, local_path))
    if framework in PICKLE_FRAMEWORKS:
        if not trust:
            raise ServingError(
                f"model '{resolved.name}' v{resolved.version} is a {framework} pickle; "
                "loading it executes its contents. Set model.trust_artifact: true if this "
                "registry only holds models your own pipelines registered."
            )
        return _load_pickle(local_path)
    if framework in ("xgboost", "lightgbm"):
        return _load_booster(local_path, framework, trust)
    if framework == "mlflow_pyfunc":
        import mlflow

        return mlflow.pyfunc.load_model(str(local_path))
    logger.info(
        "Model '{}' v{} ({}) downloaded to {}; Ducta does not load this framework itself — "
        "load it in the node from ml_context.model_ref.local_path",
        resolved.name,
        resolved.version,
        framework,
        local_path,
    )
    return None


def prepare_model(
    ref: ModelRef, *, registry: Any, mlflow_client: Any, workdir: Path
) -> ServingModel:
    """Resolve, download, verify and load one model reference."""
    resolved = resolve_model(ref, registry=registry, mlflow_client=mlflow_client)
    local_path = _download(resolved, registry, workdir)
    digest = artifact_digest(local_path)
    if resolved.registered_sha256 and resolved.registered_sha256 != digest:
        raise ServingError(
            f"model '{resolved.name}' v{resolved.version}: the artifact's hash ({digest}) "
            f"does not match the one recorded at registration ({resolved.registered_sha256}) "
            "— it changed after it was registered"
        )
    model = load_model(resolved, local_path, trust=ref.trust_artifact, registry=registry)
    logger.info(
        "Serving model '{}' v{} ({}, {}){}",
        resolved.name,
        resolved.version,
        resolved.source,
        resolved.framework,
        f" — resolved from {resolved.stage_at_resolution}" if resolved.stage_at_resolution else "",
    )
    return ServingModel(
        ref=ref,
        resolved=resolved,
        local_path=str(local_path),
        artifact_sha256=digest,
        hash_source="registry" if resolved.registered_sha256 else "load",
        model=model,
    )


class ModelCache:
    """The models one run serves: each reference is resolved and loaded once.

    Pinning happens here — two nodes naming ``stage: production`` in the same run
    get the same version even if a promotion lands between them.
    """

    def __init__(
        self,
        registry_factory: Callable[[], Any],
        mlflow_client_factory: Callable[[], Any],
    ) -> None:
        self._registry_factory = registry_factory
        self._mlflow_client_factory = mlflow_client_factory
        self._models: Dict[Tuple[Any, ...], ServingModel] = {}
        self._lock = threading.Lock()
        self._workdir = Path(tempfile.mkdtemp(prefix="ducta-serving-"))
        weakref.finalize(self, shutil.rmtree, self._workdir, True)

    @staticmethod
    def _key(ref: ModelRef) -> Tuple[Any, ...]:
        return (ref.source, ref.name, ref.stage, ref.version, ref.uri, ref.trust_artifact)

    def get(self, raw_ref: Any) -> ServingModel:
        ref = raw_ref if isinstance(raw_ref, ModelRef) else ModelRef.model_validate(raw_ref)
        key = self._key(ref)
        with self._lock:
            cached = self._models.get(key)
            if cached is None:
                cached = prepare_model(
                    ref,
                    registry=self._registry_factory() if ref.source == "ducta" else None,
                    mlflow_client=self._mlflow_client_factory() if ref.source == "mlflow" else None,
                    workdir=self._workdir,
                )
                self._models[key] = cached
        if cached.ref == ref:
            return cached
        # Same model, other scoring options (features, output_col, method).
        return ServingModel(**{**cached.__dict__, "ref": ref})


def model_cache_for(
    context: Any, registry_factory: Optional[Callable[[], Any]] = None
) -> ModelCache:
    """A :class:`ModelCache` on the project's registry (``settings.mlops``) and MLflow."""

    def _registry() -> Any:
        from ducta.mlrun.config import MLOpsContext

        return MLOpsContext.from_context(context).model_registry

    return ModelCache(
        registry_factory=registry_factory or _registry,
        mlflow_client_factory=lambda: mlflow_client_from_context(context),
    )


def mlflow_client_from_context(context: Any) -> Any:
    """An ``MlflowClient`` on the project's ``settings.mlflow`` tracking/registry URI."""
    try:
        from mlflow import MlflowClient
    except ImportError as e:
        raise ServingError("model source: mlflow needs MLflow (pip install 'ducta[mlops]')") from e
    from ducta.mlrun.config import TrackingURIResolver
    from ducta.mlrun.mlflow import _allow_file_store

    gs = getattr(context, "global_config", {}) or {}
    cfg = gs.get("mlflow", {}) or {}
    tracking_uri = TrackingURIResolver.resolve_tracking_uri(
        tracking_uri=cfg.get("tracking_uri"), context=context
    )
    registry_uri = cfg.get("registry_uri") or tracking_uri
    for uri in (tracking_uri, registry_uri):
        if uri:
            _allow_file_store(uri)
    if tracking_uri:
        import mlflow

        # pyfunc downloads resolve models:/ URIs through the global registry URI.
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_registry_uri(registry_uri)
    return MlflowClient(tracking_uri=tracking_uri, registry_uri=registry_uri)


# ── scoring ──────────────────────────────────────────────────────────────────


def _as_vector(values: Any, method: str) -> Any:
    import numpy as np

    arr = np.asarray(getattr(values, "values", values))
    if method == "predict_proba" and arr.ndim == 2:
        if arr.shape[1] == 2:
            return arr[:, 1]
        if arr.shape[1] != 1:
            raise ServingError(
                f"predict_proba returned {arr.shape[1]} classes; the built-in scorer keeps "
                "one probability per row (binary classifiers). Use method: predict, or "
                "score in your own run function."
            )
    if arr.ndim == 2 and arr.shape[1] == 1:
        arr = arr[:, 0]
    if arr.ndim != 1:
        raise ServingError(
            f"the model returned shape {arr.shape}; the built-in scorer writes one value "
            "per row. Score in your own run function for multi-output models."
        )
    return arr


def _apply(model: Any, method: str, features_df: Any) -> Any:
    """Call ``method`` on ``model`` for one pandas batch."""
    kind = f"{type(model).__module__}.{type(model).__name__}"
    if kind.startswith("xgboost.core.Booster"):
        import xgboost as xgb

        return _as_vector(model.predict(xgb.DMatrix(features_df)), method)
    if kind.startswith("mlflow.pyfunc"):
        if method != "predict":
            raise ServingError(
                f"an MLflow pyfunc model only supports method: predict, not {method}"
            )
        return _as_vector(model.predict(features_df), method)
    fn = getattr(model, method, None)
    if fn is None:
        available = [
            m
            for m in ("predict", "predict_proba", "decision_function", "score_samples")
            if hasattr(model, m)
        ]
        raise ServingError(
            f"{type(model).__name__} has no {method}(); it has: {', '.join(available) or 'none'}"
        )
    return _as_vector(fn(features_df), method)


def _spark_type(sample: Any) -> Any:
    from pyspark.sql import types as T

    kind = getattr(getattr(sample, "dtype", None), "kind", "f")
    return {
        "b": T.BooleanType(),
        "i": T.LongType(),
        "u": T.LongType(),
        "O": T.StringType(),
        "U": T.StringType(),
        "S": T.StringType(),
    }.get(kind, T.DoubleType())


def score(df: Any, serving: ServingModel) -> Any:
    """Add ``serving.ref.output_col`` to ``df`` (pandas or Spark) with the model's output."""
    model = serving.model
    ref = serving.ref
    if model is None:
        raise ServingError(
            f"Ducta does not load {serving.resolved.framework} models itself; give this "
            "node a run function that loads ml_context.model_ref.local_path"
        )
    if serving.resolved.framework == "spark-mllib":
        return _score_spark_ml(df, serving)
    features = serving.features
    if features is None and serving.resolved.source != "mlflow":
        raise ServingError(
            f"model '{serving.resolved.name}' has no registered input schema; list its "
            "columns in model.features"
        )
    columns = list(df.columns)
    if features is not None:
        missing = [c for c in features if c not in columns]
        if missing:
            raise ServingError(f"input is missing the model's feature columns: {missing}")

    if hasattr(df, "iloc"):  # pandas
        out = df.copy()
        values = _apply(model, ref.method, df[features] if features else df)
        if ref.output_type is not None:
            values = values.astype(_OUTPUT_TYPES[ref.output_type][1])
        out[ref.output_col] = values
        return out

    from pyspark.sql import types as T

    method, output_col = ref.method, ref.output_col
    if output_col in columns:  # re-scoring replaces the column rather than duplicating it
        df = df.drop(output_col)
    streaming = bool(getattr(df, "isStreaming", False))
    arrow = _arrow_udfs_work(df)
    if streaming and not arrow:
        raise ServingError(
            "scoring a stream needs Arrow (mapInPandas), which Spark 3 cannot run on "
            "Java 21+; run the stream on Java 17 or Spark 4"
        )

    input_cols = list(df.columns)
    if ref.output_type is not None:
        out_type: Any = getattr(T, _OUTPUT_TYPES[ref.output_type][0])()
    elif streaming or method != "predict":
        out_type = T.DoubleType()  # a stream cannot be sampled for its prediction type
    else:
        # Where Arrow cannot run, toPandas() fails too once the session enables Arrow.
        probe = (
            df.limit(1).toPandas() if arrow else _rows_to_pandas(df.limit(1).collect(), input_cols)
        )
        out_type = (
            T.DoubleType()
            if probe.empty
            else _spark_type(_apply(model, method, probe[features] if features else probe))
        )
    pandas_dtype = _PANDAS_DTYPES[type(out_type).__name__]

    def _score_batches(batches: Any) -> Any:
        # The model travels to the executors inside this closure (cloudpickle),
        # which also works where sparkContext.broadcast does not (Spark Connect).
        for pdf in batches:
            values = _apply(model, method, pdf[features] if features else pdf)
            pdf[output_col] = values.astype(pandas_dtype)
            yield pdf

    def _score_partition(rows: Any) -> Any:
        pdf = _rows_to_pandas(rows, input_cols)
        if pdf.empty:
            return iter(())
        scored = _apply(model, method, pdf[features] if features else pdf).astype(pandas_dtype)
        return (
            (*rec, _plain(value))
            for rec, value in zip(pdf.itertuples(index=False, name=None), scored)
        )

    # A new StructType: .add() on df.schema would mutate the input's cached schema.
    schema = T.StructType([*df.schema.fields, T.StructField(output_col, out_type, True)])
    if arrow:
        return df.mapInPandas(_score_batches, schema=schema)
    return df.sparkSession.createDataFrame(df.rdd.mapPartitions(_score_partition), schema)


#: ``output_type`` → the Spark type name and the numpy dtype a prediction is cast to.
_OUTPUT_TYPES = {
    "double": ("DoubleType", "float64"),
    "long": ("LongType", "int64"),
    "string": ("StringType", "str"),
    "boolean": ("BooleanType", "bool"),
}
_PANDAS_DTYPES = dict(_OUTPUT_TYPES.values())


def _score_spark_ml(df: Any, serving: ServingModel) -> Any:
    """A Spark ML model scores with transform(); keep the input plus output_col.

    Its pipeline assembles its own features, so ``model.features`` is not used.
    """
    if hasattr(df, "iloc"):
        raise ServingError("a spark-mllib model scores Spark DataFrames, not pandas")
    from pyspark.ml.functions import vector_to_array
    from pyspark.sql import functions as F

    model, ref = serving.model, serving.ref
    last = model.stages[-1] if hasattr(model, "stages") and model.stages else model
    columns = [c for c in df.columns if c != ref.output_col]
    out = model.transform(df.select(*columns))
    if ref.method == "predict":
        value = F.col(
            last.getPredictionCol() if hasattr(last, "getPredictionCol") else "prediction"
        )
    elif ref.method == "predict_proba":
        prob = last.getProbabilityCol() if hasattr(last, "getProbabilityCol") else "probability"
        value = vector_to_array(F.col(prob)).getItem(1)
    else:
        raise ServingError(
            f"a spark-mllib model supports method: predict or predict_proba, not {ref.method}"
        )
    if ref.output_type is not None:
        value = value.cast(ref.output_type)
    return out.select(*columns, value.alias(ref.output_col))


def _rows_to_pandas(rows: Any, columns: List[str]) -> Any:
    """Spark rows as a pandas frame, without Arrow.

    object dtype keeps every value exactly as Spark gave it (a null in an integer
    column stays None instead of becoming a float NaN).
    """
    import pandas as pd

    return pd.DataFrame([r.asDict() for r in rows], columns=columns, dtype=object)


def _plain(value: Any) -> Any:
    """A numpy scalar as the Python value Spark's row converter accepts."""
    return value.item() if hasattr(value, "item") else value


_arrow_warned = False


def _arrow_udfs_work(df: Any) -> bool:
    """Whether Arrow-based Python UDFs (mapInPandas) run on this cluster.

    Spark 3.x ships Arrow 12, which cannot allocate buffers on Java 21+
    (``DirectByteBuffer.<init>(long, int) not available``) whatever JVM flags are
    set. There the scorer falls back to a row-based path: slower, but correct.
    """
    global _arrow_warned
    try:
        jvm = df.sparkSession.sparkContext._jvm
        java = str(jvm.java.lang.System.getProperty("java.specification.version"))
    except Exception:  # noqa: BLE001 — Spark Connect: no local JVM, the server decides
        return True
    java_major = int(java.split(".")[1] if java.startswith("1.") else java.split(".")[0])
    spark_major = int(str(df.sparkSession.version).split(".")[0])
    if java_major < 21 or spark_major >= 4:
        return True
    if not _arrow_warned:
        _arrow_warned = True
        logger.warning(
            "Spark {} on Java {}: Arrow-based scoring (mapInPandas) does not run on this "
            "combination, so the built-in scorer uses a slower row-based path. Run Spark "
            "on Java 17 (or Spark 4) for vectorized scoring.",
            df.sparkSession.version,
            java,
        )
    return False


def predict(
    *args: Any,
    ml_context: Any = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **inputs: Any,
) -> Any:
    """The built-in serving function: score the node's single input with its model."""
    dfs = [d for d in (*args, *inputs.values()) if d is not None]
    if len(dfs) != 1:
        raise ServingError(
            f"the built-in scorer reads exactly one input, got {len(dfs)}; join them "
            "upstream or give this node a run function"
        )
    serving = ml_context.get("model_ref") if ml_context is not None else None
    if serving is None:
        raise ServingError("the built-in scorer needs a model: declare model: on the node")
    return score(dfs[0], serving)
