"""The micro-batch path of a stream node (merge, quarantine, quality) on fakes.

What needs Spark columns (reject_when, the gate on real rows) is covered by
``tests/integration/test_streaming_micro_batch_live.py``.
"""

from __future__ import annotations

import pytest

from ducta.stream import micro_batch
from ducta.stream.exceptions import StreamingConfigurationError, StreamingValidationError
from ducta.stream.micro_batch import MicroBatchSink, _BufferedStorage, needs_micro_batch
from ducta.stream.plan import describe_node, describe_sink
from ducta.stream.validators import StreamingValidator

DELTA_MERGE = {
    "format": "delta",
    "path": "/lake/silver/orders",
    "mode": "merge",
    "merge": {"keys": ["order_id"]},
}


def _node(output=None, **extra):
    node = {
        "name": "orders",
        "input": {"format": "rate"},
        "output": output or {"format": "parquet", "path": "/lake/out"},
    }
    node.update(extra)
    return node


@pytest.fixture
def context(tmp_path):
    return {"global_config": {}, "output_path": str(tmp_path), "env": "dev"}


class _Writer:
    def __init__(self, log):
        self.log = log

    def format(self, fmt):
        self.log.append(("format", fmt))
        return self

    def mode(self, mode):
        self.log.append(("mode", mode))
        return self

    def option(self, key, value):
        self.log.append(("option", key, value))
        return self

    def partitionBy(self, *cols):
        self.log.append(("partitionBy", cols))
        return self

    def save(self, path):
        self.log.append(("save", path))


class _Conf:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value

    def unset(self, key):
        self.values.pop(key, None)


class _DF:
    def __init__(self):
        self.log = []
        self.sparkSession = type("S", (), {"conf": _Conf()})()

    @property
    def write(self):
        return _Writer(self.log)


def _options(log):
    return {entry[1]: entry[2] for entry in log if entry[0] == "option"}


class TestActivation:
    def test_plain_node_keeps_the_native_sink(self):
        assert not needs_micro_batch(_node())

    @pytest.mark.parametrize(
        "node",
        [
            _node(DELTA_MERGE),
            _node(quarantine={"reject_when": "amount < 0"}),
            _node(data_quality={"checks": {"row_count": {"min": 1}}}),
        ],
    )
    def test_merge_quarantine_or_quality_use_foreach_batch(self, node):
        assert needs_micro_batch(node)

    def test_disabled_quality_does_not(self):
        assert not needs_micro_batch(_node(data_quality={"enabled": False, "checks": {"x": {}}}))


class TestValidator:
    def _validate(self, node):
        StreamingValidator().validate_streaming_node_config(node)

    def test_merge_into_delta_is_valid(self):
        self._validate(_node(DELTA_MERGE))

    def test_merge_needs_a_delta_sink(self):
        with pytest.raises(StreamingValidationError, match="only a delta sink"):
            self._validate(_node({**DELTA_MERGE, "format": "parquet"}))

    def test_merge_needs_keys(self):
        with pytest.raises(StreamingValidationError, match="merge.keys"):
            self._validate(_node({**DELTA_MERGE, "merge": {}}))

    def test_merge_block_without_merge_mode(self):
        output = {"format": "delta", "path": "/x", "merge": {"keys": ["k"]}}
        with pytest.raises(StreamingValidationError, match="only valid with"):
            self._validate(_node(output))

    def test_quarantine_needs_a_batch_writable_sink(self):
        node = _node({"format": "console"}, quarantine={"reject_when": "amount < 0"})
        with pytest.raises(StreamingValidationError, match="need one of"):
            self._validate(node)

    def test_reject_when_must_be_a_plain_predicate(self):
        node = _node(quarantine={"reject_when": "1 = 1; DROP TABLE orders"})
        with pytest.raises(StreamingValidationError, match="reject_when"):
            self._validate(node)


class TestProjectSchema:
    def test_merge_needs_delta_and_keys(self):
        from ducta.setting.project.schema import StreamOutput

        StreamOutput.model_validate(
            {**DELTA_MERGE, "merge": {"keys": ["k"], "dedupe_order_by": "ts"}}
        )
        with pytest.raises(ValueError, match="format: delta"):
            StreamOutput.model_validate({**DELTA_MERGE, "format": "parquet"})
        with pytest.raises(ValueError, match="needs output.merge"):
            StreamOutput.model_validate({"format": "delta", "mode": "merge"})

    def test_quarantine_predicate_is_validated(self):
        from ducta.setting.project.schema import StreamQuarantine

        StreamQuarantine.model_validate({"reject_when": "amount < 0"})
        with pytest.raises(ValueError):
            StreamQuarantine.model_validate({"reject_when": "amount < (SELECT max(x) FROM t)"})


class TestPlan:
    def test_merge_sink_names_its_keys(self):
        assert describe_sink(DELTA_MERGE) == "delta merge on [order_id] /lake/silver/orders"

    def test_quarantine_and_checks_are_shown(self, context, tmp_path):
        node = _node(
            quarantine={"reject_when": "amount < 0"},
            data_quality={"checks": {"row_count": {"min": 1}}, "quality_gate": {"max_errors": 0}},
        )
        plan = describe_node(node, context, "sales")
        assert plan.quality == "1 check, gate"
        assert plan.quarantine == f"{tmp_path}/dev/quarantine/sales/orders"


class TestBufferedStorage:
    def test_writes_wait_for_flush_reads_go_through(self):
        calls = []

        class Inner:
            def save_report(self, *a):
                calls.append(("save", a))

            def load_baseline(self, *a):
                return "baseline"

        storage = _BufferedStorage(Inner())
        storage.save_report("r", 1)
        assert storage.load_baseline("d") == "baseline"
        assert calls == []
        storage.flush()
        assert calls == [("save", ("r", 1))]


class TestWrites:
    def _sink(self, context, output, reader=lambda spark, cp: "q-123"):
        return MicroBatchSink(
            context, _node(output), "sales", "/ckpt/sales/orders", query_id_reader=reader
        )

    def test_delta_append_is_tagged_with_the_query_and_batch(self, context):
        sink = self._sink(context, {"format": "delta", "path": "/lake/t"})
        df = _DF()
        sink._append(df, "/lake/t", "delta", 7)
        opts = _options(df.log)
        assert opts["txnAppId"] == "ducta:q-123"
        assert opts["txnVersion"] == "7"
        assert opts["mergeSchema"] == "true"  # the native Delta writer's default
        assert ("save", "/lake/t") in df.log

    def test_without_a_query_id_the_node_names_the_app(self, context):
        sink = self._sink(context, {"format": "delta", "path": "/lake/t"}, reader=lambda s, c: None)
        df = _DF()
        sink._append(df, "/lake/t", "delta", 0)
        assert _options(df.log)["txnAppId"] == "ducta:sales::orders"

    def test_merge_sets_the_txn_confs_only_while_it_runs(self, context, monkeypatch):
        seen = {}

        class FakeMerge:
            def __init__(self, df, destination, config):
                seen["config"] = config
                seen["destination"] = destination
                self.df = df

            def run(self, create):
                seen["confs"] = dict(self.df.sparkSession.conf.values)

        monkeypatch.setattr("ducta.gate.writers.DeltaMerge", FakeMerge)
        sink = self._sink(context, DELTA_MERGE)
        df = _DF()
        sink._merge(df, 4)
        assert seen["destination"] == "/lake/silver/orders"
        assert seen["config"] == {"merge": {"keys": ["order_id"]}}
        assert seen["confs"] == {
            micro_batch._TXN_APP_ID_CONF: "ducta:q-123",
            micro_batch._TXN_VERSION_CONF: "4",
        }
        assert df.sparkSession.conf.values == {}

    def test_creating_the_table_drops_the_confs_first(self, context, monkeypatch):
        class FakeMerge:
            def __init__(self, df, destination, config):
                self.df = df

            def run(self, create):
                create()

        monkeypatch.setattr("ducta.gate.writers.DeltaMerge", FakeMerge)
        sink = self._sink(context, DELTA_MERGE)
        df = _DF()
        sink._merge(df, 0)
        assert _options(df.log)["txnVersion"] == "0"
        assert df.sparkSession.conf.values == {}

    def test_unsupported_sink_is_refused(self, context):
        with pytest.raises(StreamingConfigurationError, match="do not support"):
            self._sink(context, {"format": "console"})
