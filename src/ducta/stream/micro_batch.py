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

# A stream node's micro-batch, handled like a small batch run: rows a rule rejects
# go to quarantine, the rest is checked by the node's quality gate, and what passes
# is appended or merged into the sink. Used through ``foreachBatch`` only when the
# node asks for one of those (``output.mode: merge``, ``quarantine`` or
# ``quality``); every other node keeps Spark's native sink.
#
# Writes are idempotent per batch: Spark runs a batch again after a failure with
# the same id, and a Delta append tagged ``txnAppId``/``txnVersion`` is skipped the
# second time. The app id is the query's own id, read from its checkpoint, so a
# cleared checkpoint (batch ids restart at 0) is a new id and is not skipped.

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.setting.environments import sanitize_env_for_path
from ducta.spark_jvm import hadoop_configuration, jvm
from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.context_utils import get_active_env, get_context_value
from ducta.stream.exceptions import StreamingConfigurationError
from ducta.stream.factories import spark_option_value
from ducta.stream.query_manager import single_spec

#: Sinks the micro-batch path can write (a batch write of each exists).
MICRO_BATCH_SINKS = frozenset({"delta", "parquet", "json", "csv"})

#: Columns a quarantined row carries, besides its own.
QUARANTINE_COLUMNS = ("_ducta_reason", "_ducta_batch_id", "_ducta_run_id", "_ducta_quarantined_at")

DEFAULT_REPORT_EVERY = 100

#: Delta session confs that make a DML statement (MERGE) idempotent per batch.
_TXN_APP_ID_CONF = "spark.databricks.delta.write.txnAppId"
_TXN_VERSION_CONF = "spark.databricks.delta.write.txnVersion"


def _quality_config(node_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    dq = node_config.get("data_quality")
    if isinstance(dq, dict) and dq.get("enabled", True) and (dq.get("checks") or dq.get("profile")):
        return dq
    return None


def needs_micro_batch(node_config: Dict[str, Any]) -> bool:
    """Whether *node_config* is written through ``foreachBatch`` (see the module note)."""
    output = single_spec(node_config, "output")
    merging = isinstance(output, dict) and str(output.get("mode") or "").lower() == "merge"
    return (
        merging or bool(node_config.get("quarantine")) or _quality_config(node_config) is not None
    )


class _BufferedStorage:
    """A quality storage backend whose report writes wait for the batch's verdict.

    Reads go straight through. Reports and gate results (``save_*``) are kept and
    replayed by :meth:`flush`, or dropped: a passing batch only keeps its report one
    time in ``report_every``. State is not a report and is never dropped: the
    baseline is written at once (it used to be dropped with the reports, so the
    temporal checks had nothing to compare with for ~100 batches), and so is the
    history when it is a local JSON file. A parquet/delta history is a whole Spark
    rewrite per append, so there it keeps the reports' pace.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._pending: List[Any] = []
        cheap_history = str(getattr(inner, "format", "json")).lower() == "json"
        self._through = {"save_baseline"} | ({"append_history"} if cheap_history else set())

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name in self._through:
            return attr
        if name.startswith(("save_", "append_")) and callable(attr):

            def deferred(*args: Any, **kwargs: Any) -> None:
                self._pending.append((attr, args, kwargs))

            return deferred
        return attr

    def flush(self) -> None:
        for method, args, kwargs in self._pending:
            try:
                method(*args, **kwargs)
            except Exception as e:  # a report must never fail the batch
                logger.warning("Could not save a stream quality report: {}", e)
        self._pending.clear()


class MicroBatchSink:
    """``foreachBatch`` callable for one stream node."""

    def __init__(
        self,
        context: Any,
        node_config: Dict[str, Any],
        pipeline_name: str,
        checkpoint_location: str,
        run_id: Optional[str] = None,
        on_batch: Optional[Callable[[Dict[str, Any]], None]] = None,
        query_id_reader: Optional[Callable[[Any, str], Optional[str]]] = None,
    ) -> None:
        self.context = context
        self.node_name = str(node_config.get("name") or "unknown")
        self.pipeline_name = pipeline_name
        self.checkpoint_location = checkpoint_location
        self.run_id = run_id
        self.on_batch = on_batch
        self._read_query_id = query_id_reader or _query_id_from_checkpoint
        self._app_id: Optional[str] = None

        output = single_spec(node_config, "output") or {}
        self.format = str(output.get("format") or "").lower()
        if self.format not in MICRO_BATCH_SINKS:
            raise StreamingConfigurationError(
                f"Stream node '{self.node_name}' writes '{self.format}', which merge, "
                f"quarantine and quality do not support (use one of {sorted(MICRO_BATCH_SINKS)})",
                config_section="output.format",
            )
        self.path = str(output.get("path") or "")
        # The defaults the native writers add (DeltaStreamingWriter, CSVStreamingWriter).
        self.options = dict(output.get("options") or {})
        if self.format == "delta":
            self.options.setdefault("mergeSchema", "true")
            self.options.setdefault("delta.enableChangeDataFeed", "true")
        elif self.format == "csv":
            self.options.setdefault("header", "true")
        self.partition_by = output.get("partitionBy")
        self.mode = str(output.get("mode") or "append").lower()
        self.merge_spec = dict(output.get("merge") or {})

        quarantine = node_config.get("quarantine") or {}
        self.reject_when: Optional[str] = quarantine.get("reject_when") or None
        self.quarantine_path = str(
            quarantine.get("path")
            or default_quarantine_path(context, pipeline_name, self.node_name)
        )

        self.quality = _quality_config(node_config)
        gs = get_context_value(context, "global_config", {}) or {}
        self.report_every = int(gs.get("streaming_quality_report_every") or DEFAULT_REPORT_EVERY)
        self._runner: Any = None
        self._batches_seen = 0
        self._warned_at_least_once = False

    # ── the batch ────────────────────────────────────────────────────────────

    def __call__(self, batch_df: Any, batch_id: int) -> None:
        started = time.time()
        batch_id = int(batch_id)
        stats: Dict[str, Any] = {
            "node": self.node_name,
            "batch_id": batch_id,
            "rows_in": 0,
            "rows_written": 0,
            "rows_quarantined": 0,
            "gate": None,
        }
        batch_df.persist()
        try:
            stats["rows_in"] = batch_df.count()
            if stats["rows_in"]:
                self._process(batch_df, batch_id, stats)
        finally:
            batch_df.unpersist()
        stats["duration_ms"] = round((time.time() - started) * 1000.0, 1)
        self._batches_seen += 1
        if self.on_batch is not None:
            try:
                self.on_batch(stats)
            except Exception as e:  # bookkeeping must never fail the batch
                logger.debug("on_batch hook for '{}' failed: {}", self.node_name, e)

    def _process(self, df: Any, batch_id: int, stats: Dict[str, Any]) -> None:
        from pyspark.sql import functions as F  # type: ignore

        good, bad = df, None
        if self.reject_when:
            flagged = F.coalesce(F.expr(self.reject_when), F.lit(False))
            bad = self._tag(df.where(flagged), f"reject_when: {self.reject_when}", batch_id)
            good = df.where(~flagged)

        blocked_by: Optional[str] = None
        if self.quality is not None and good.take(1):
            blocked_by = self._check(good, batch_id, stats)

        if blocked_by is not None:
            # The gate judged the whole batch: none of it reaches the sink.
            tagged = self._tag(good, f"quality_gate: {blocked_by}", batch_id)
            bad = tagged if bad is None else bad.unionByName(tagged)
            good = None

        if bad is not None:
            stats["rows_quarantined"] = bad.count()
            if stats["rows_quarantined"]:
                # Same format as the sink: a parquet node needs no Delta for it.
                self._append(bad, self.quarantine_path, self.format, batch_id, suffix="quarantine")
                logger.warning(
                    "Stream node '{}' batch {}: {} row(s) quarantined at {}",
                    self.node_name,
                    batch_id,
                    stats["rows_quarantined"],
                    self.quarantine_path,
                )
        if good is not None:
            stats["rows_written"] = stats["rows_in"] - stats["rows_quarantined"]
            if stats["rows_written"]:
                if self.mode == "merge":
                    self._merge(good, batch_id)
                else:
                    self._append(good, self.path, self.format, batch_id)

    def _tag(self, df: Any, reason: str, batch_id: int) -> Any:
        from pyspark.sql import functions as F  # type: ignore

        return (
            df.withColumn("_ducta_reason", F.lit(reason))
            .withColumn("_ducta_batch_id", F.lit(batch_id).cast("long"))
            .withColumn("_ducta_run_id", F.lit(self.run_id).cast("string"))
            .withColumn("_ducta_quarantined_at", F.current_timestamp())
        )

    # ── quality ──────────────────────────────────────────────────────────────

    def _check(self, df: Any, batch_id: int, stats: Dict[str, Any]) -> Optional[str]:
        """Run the node's checks on *df*; the gate's rules when it blocks, else None."""
        from ducta.check import QualityChecksFailed
        from ducta.check.core import QualityConfigError, QualityEngineError, QualityGateBlocked

        runner = self._quality_runner()
        storage = _BufferedStorage(runner.storage)
        runner.storage = storage
        dq = dict(self.quality or {})
        dataset = dq.get("dataset_name") or self.node_name
        blocked: Optional[str] = None
        passed = False
        try:
            report = runner.run(
                dataset_name=dataset,
                df=df,
                config=dq,
                run_id=f"{self.run_id or 'stream'}-b{batch_id}",
                pipeline_name=self.pipeline_name,
            )
            passed = bool(getattr(report, "passed", True))
            stats["gate"] = "pass" if passed else "warn"
        except QualityGateBlocked as e:
            rules = getattr(getattr(e, "gate_result", None), "triggered_rules", None) or [str(e)]
            blocked = "; ".join(str(r) for r in rules)
            stats["gate"] = "block"
        except QualityChecksFailed as e:  # fail_fast with error-severity failures
            blocked = str(e)
            stats["gate"] = "block"
        except (QualityConfigError, QualityEngineError):
            # The checks could not run at all (`severity: warnig`, a broken gate, an
            # unknown profile): nothing was checked, so the batch must not be written
            # as if it passed — the query fails, as a batch node does.
            raise
        except Exception as e:
            # Same policy as a batch node: a check that cannot run fails the node
            # only with fail_fast; otherwise the batch goes on, said loudly.
            if dq.get("fail_fast", False):
                raise
            logger.error("Quality checks of '{}' batch {} could not run: {}", dataset, batch_id, e)
            stats["gate"] = "error"
        finally:
            runner.storage = storage._inner
        keep_report = (
            blocked is not None or not passed or self._batches_seen % self.report_every == 0
        )
        if keep_report:
            storage.flush()
        if blocked is not None:
            logger.warning(
                "Quality gate blocked '{}' batch {}: {} — the batch goes to quarantine",
                dataset,
                batch_id,
                blocked,
            )
        return blocked

    def _quality_runner(self) -> Any:
        if self._runner is None:
            from ducta.check import ValidationPhaseRunner
            from ducta.check.profiles import load_profiles

            gs = get_context_value(self.context, "global_config", {}) or {}
            gs = gs if isinstance(gs, dict) else {}
            try:
                profiles = load_profiles(gs)
            except Exception:
                profiles = {}
            self._runner = ValidationPhaseRunner(
                context=self.context,
                fail_fast=bool((self.quality or {}).get("fail_fast", False)),
                profiles=profiles,
                global_gate_config=(gs.get("quality") or {}).get("gate"),
            )
        return self._runner

    # ── writes ───────────────────────────────────────────────────────────────

    def _app_id_for(self, spark: Any) -> str:
        if self._app_id is None:
            query_id = None
            try:
                query_id = self._read_query_id(spark, self.checkpoint_location)
            except Exception as e:
                logger.debug("Could not read the query id of '{}': {}", self.node_name, e)
            if not query_id:
                query_id = "{}::{}".format(
                    CheckpointManager.sanitize_path_component(self.pipeline_name),
                    CheckpointManager.sanitize_path_component(self.node_name),
                )
                logger.warning(
                    "Stream node '{}': no query id in its checkpoint; idempotent writes use "
                    "'{}', so clear the sink's Delta history too if you clear the checkpoint",
                    self.node_name,
                    query_id,
                )
            self._app_id = f"ducta:{query_id}"
        return self._app_id

    def _append(self, df: Any, path: str, fmt: str, batch_id: int, suffix: str = "") -> None:
        if fmt != "delta":
            published = _FilePublisher.for_session(df.sparkSession)
            if published is not None:
                key = _sanitize_key(f"{self._app_id_for(df.sparkSession)}:{suffix or 'sink'}")
                published.publish(
                    lambda staging: self._writer(df, fmt, suffix).mode("overwrite").save(staging),
                    path,
                    key,
                    batch_id,
                )
                return
            if not self._warned_at_least_once:
                self._warned_at_least_once = True
                logger.warning(
                    "Stream node '{}': no JVM to publish {} files with (Spark Connect); a "
                    "re-run batch may be written twice",
                    self.node_name,
                    fmt,
                )
        writer = self._writer(df, fmt, suffix).mode("append")
        if fmt == "delta":
            app_id = self._app_id_for(df.sparkSession)
            writer = writer.option("txnAppId", f"{app_id}:{suffix}" if suffix else app_id)
            writer = writer.option("txnVersion", str(batch_id))
            if suffix:
                writer = writer.option("mergeSchema", "true")
        writer.save(path)

    def _writer(self, df: Any, fmt: str, suffix: str) -> Any:
        """The batch writer of *df* in *fmt*, with the sink's options and partitioning."""
        writer = df.write.format(fmt)
        for key, value in self.options.items() if not suffix else ():
            if value is not None and not (fmt != "delta" and str(key).startswith("delta.")):
                writer = writer.option(str(key), spark_option_value(value))
        if suffix and fmt == "csv":
            # A quarantine has no options of its own; without a header its columns
            # (the reason among them) had no names.
            writer = writer.option("header", "true")
        if self.partition_by and not suffix:
            parts = (
                self.partition_by if isinstance(self.partition_by, list) else [self.partition_by]
            )
            writer = writer.partitionBy(*parts)
        return writer

    def _merge(self, df: Any, batch_id: int) -> None:
        from ducta.gate.writers import DeltaMerge

        spec = dict(self.merge_spec)
        order_by = spec.pop("dedupe_order_by", None)
        if order_by:
            df = _latest_per_key(df, spec.get("keys") or [], order_by)
        spark = df.sparkSession
        app_id = self._app_id_for(spark)
        conf = spark.conf

        def unset_txn() -> None:
            # A conf left set would make Delta skip every later write of this
            # session as "already committed".
            for key in (_TXN_APP_ID_CONF, _TXN_VERSION_CONF):
                try:
                    conf.unset(key)
                except Exception:  # noqa: BLE001
                    pass

        def create() -> None:
            # The first batch creates the table: an append tagged by its options.
            unset_txn()
            self._append(df, self.path, "delta", batch_id)

        conf.set(_TXN_APP_ID_CONF, app_id)
        conf.set(_TXN_VERSION_CONF, str(batch_id))
        try:
            DeltaMerge(df, self.path, {"merge": spec}).run(create=create)
        finally:
            unset_txn()


#: Under a file sink's folder; Spark's readers skip names starting with "_".
STAGING_DIR = "_ducta_staging"
MARKERS_DIR = "_ducta_batches"


def _sanitize_key(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:120]


class _FilePublisher:
    """Exactly-once batch appends to a parquet/JSON/CSV folder.

    Spark runs a micro-batch again, with the same id, when the query failed before
    committing it — after the files were written. A plain append then wrote them a
    second time (Spark's own file sink avoids it with ``_spark_metadata``, which a
    ``foreachBatch`` does not get). Here a batch is written to a staging folder, its
    files are listed in a marker, moved into the sink under a name carrying the
    query's key and the batch id, and the marker is closed. Run again, a closed
    marker for the same batch means "already published" (skipped); an open one
    means "interrupted half-way": its files are removed and the batch is published
    again. One marker per key, overwritten by the next batch.
    """

    def __init__(self, gateway: Any, hadoop_conf: Any) -> None:
        self._gw = gateway
        self._conf = hadoop_conf

    @classmethod
    def for_session(cls, spark: Any) -> Optional["_FilePublisher"]:
        gateway, conf = jvm(spark), hadoop_configuration(spark)
        if gateway is None or conf is None:  # Spark Connect: no local JVM
            return None
        return cls(gateway, conf)

    def _path(self, text: str) -> Any:
        return self._gw.org.apache.hadoop.fs.Path(text)

    def _read_marker(self, fs: Any, marker: Any) -> Optional[Dict[str, Any]]:
        if not fs.exists(marker):
            return None
        stream = fs.open(marker)
        try:
            reader = self._gw.java.io.BufferedReader(
                self._gw.java.io.InputStreamReader(stream, "UTF-8")
            )
            text = reader.readLine()
        finally:
            stream.close()
        try:
            data = json.loads(text) if text else None
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _write_marker(self, fs: Any, marker: Any, data: Dict[str, Any]) -> None:
        out = fs.create(marker, True)
        try:
            out.write(bytearray(json.dumps(data).encode("utf-8")))
        finally:
            out.close()

    def publish(
        self, write_staging: Callable[[str], None], target: str, key: str, batch_id: int
    ) -> None:
        root = target.rstrip("/")
        marker = self._path(f"{root}/{MARKERS_DIR}/{key}.json")
        fs = marker.getFileSystem(self._conf)
        found = self._read_marker(fs, marker)
        if found and found.get("batch_id") == batch_id:
            if found.get("done"):
                logger.info("Batch {} of '{}' is already in {}: skipped", batch_id, key, root)
                return
            for name in found.get("files") or []:  # an interrupted publish: start over
                fs.delete(self._path(f"{root}/{name}"), False)

        staging_text = f"{root}/{STAGING_DIR}/{key}-b{batch_id}"
        staging = self._path(staging_text)
        write_staging(staging_text)
        base = fs.makeQualified(staging).toString().rstrip("/") + "/"
        moves = []
        listing = fs.listFiles(staging, True)
        while listing.hasNext():
            source = listing.next().getPath()
            name = source.getName()
            if name.startswith(("_", ".")):
                continue  # _SUCCESS, .crc
            relative = fs.makeQualified(source).toString()[len(base) :]
            folder, _, _ = relative.rpartition("/")
            renamed = f"{folder + '/' if folder else ''}ducta-{key}-b{batch_id}-{name}"
            moves.append((source, renamed))
        record = {"batch_id": batch_id, "files": [r for _, r in moves], "done": False}
        self._write_marker(fs, marker, record)
        for source, renamed in moves:
            destination = self._path(f"{root}/{renamed}")
            fs.mkdirs(destination.getParent())
            if not fs.rename(source, destination):
                raise IOError(f"Could not move {source} to {destination}")
        record["done"] = True
        self._write_marker(fs, marker, record)
        fs.delete(staging, True)


def default_quarantine_path(context: Any, pipeline_name: str, node_name: str) -> str:
    """``<output_path>/<environment>/quarantine/<pipeline>/<node>``: the storage convention."""
    output_path = get_context_value(context, "output_path", None) or (
        (get_context_value(context, "global_config", {}) or {}).get("output_path")
    )
    if not output_path:
        raise StreamingConfigurationError(
            f"Stream node '{node_name}' quarantines rows but no output_path is "
            "configured; set quarantine.path",
            config_section="quarantine.path",
        )
    return "{}/{}/quarantine/{}/{}".format(
        str(output_path).rstrip("/"),
        sanitize_env_for_path(get_active_env(context)),
        CheckpointManager.sanitize_path_component(pipeline_name),
        CheckpointManager.sanitize_path_component(node_name),
    )


def _latest_per_key(df: Any, keys: List[str], order_by: str) -> Any:
    """One row per merge key: the one with the highest *order_by*."""
    from pyspark.sql import Window  # type: ignore
    from pyspark.sql import functions as F  # type: ignore

    window = Window.partitionBy(*keys).orderBy(F.col(order_by).desc_nulls_last())
    return (
        df.withColumn("_ducta_rank", F.row_number().over(window))
        .where(F.col("_ducta_rank") == 1)
        .drop("_ducta_rank")
    )


def _query_id_from_checkpoint(spark: Any, checkpoint_location: str) -> Optional[str]:
    """The query id Spark keeps in ``<checkpoint>/metadata`` (any Hadoop filesystem)."""
    gateway, hadoop_conf = jvm(spark), hadoop_configuration(spark)
    if gateway is None or hadoop_conf is None:  # Spark Connect: no local JVM to read it with
        return None
    hadoop_path = gateway.org.apache.hadoop.fs.Path(f"{checkpoint_location.rstrip('/')}/metadata")
    fs = hadoop_path.getFileSystem(hadoop_conf)
    if not fs.exists(hadoop_path):
        return None
    stream = fs.open(hadoop_path)
    try:
        reader = gateway.java.io.BufferedReader(gateway.java.io.InputStreamReader(stream, "UTF-8"))
        line = reader.readLine()
    finally:
        stream.close()
    return str(json.loads(line).get("id")) if line else None
