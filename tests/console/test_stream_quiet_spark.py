"""`ducta stream run` quiets four harmless Spark warnings, and nothing else."""

from __future__ import annotations

import argparse

import pytest

from ducta.console.cli import _wants_known_spark_noise_quieted
from ducta.setting.session import _KNOWN_NOISE_LOG4J2, _quiet_log4j_file


def _args(subcommand="stream", stream_command="run", verbose=False, log_level="INFO"):
    return argparse.Namespace(
        subcommand=subcommand, stream_command=stream_command, verbose=verbose, log_level=log_level
    )


class TestWhenItApplies:
    def test_a_stream_run_gets_it(self):
        assert _wants_known_spark_noise_quieted(_args()) is True

    @pytest.mark.parametrize(
        "sub,cmd",
        [
            ("stream", "status"),
            ("stream", "plan"),
            ("stream", "stop"),
            ("start", None),
            ("list", None),
        ],
    )
    def test_only_stream_run_does(self, sub, cmd):
        assert _wants_known_spark_noise_quieted(_args(sub, cmd)) is False

    def test_verbose_shows_everything_again(self):
        assert _wants_known_spark_noise_quieted(_args(verbose=True)) is False

    def test_debug_shows_everything_again(self):
        assert _wants_known_spark_noise_quieted(_args(log_level="debug")) is False


class TestTheLog4jFile:
    def test_known_mode_writes_a_file_that_lowers_exactly_the_four_noisy_loggers(self, monkeypatch):
        monkeypatch.setenv("DUCTA_SPARK_QUIET", "known")
        path = _quiet_log4j_file()
        text = path.read_text(encoding="utf-8")
        assert text == _KNOWN_NOISE_LOG4J2
        for logger_name in (
            "org.apache.spark.util.Utils",
            "org.apache.hadoop.util.NativeCodeLoader",
            "org.apache.spark.metrics.GarbageCollectionMetrics",
            "org.apache.spark.sql.execution.streaming.ResolveWriteToStream",
            "org.apache.spark.scheduler.FairSchedulableBuilder",
        ):
            assert f"= {logger_name}\n" in text
        assert text.count(".level = error") == 5

    def test_everything_else_stays_at_warn(self):
        # Equal root and Spark levels, so Spark does not print "Setting default log level".
        assert "rootLogger.level = warn" in _KNOWN_NOISE_LOG4J2
        assert "logger.spark.level = warn" in _KNOWN_NOISE_LOG4J2
        assert "fatal" not in _KNOWN_NOISE_LOG4J2

    def test_it_is_a_different_file_from_the_full_quiet_one(self, monkeypatch):
        monkeypatch.setenv("DUCTA_SPARK_QUIET", "known")
        known = _quiet_log4j_file()
        monkeypatch.setenv("DUCTA_SPARK_QUIET", "1")
        full = _quiet_log4j_file()
        assert known != full and "fatal" in full.read_text(encoding="utf-8")

    def test_without_the_variable_there_is_no_file(self, monkeypatch):
        monkeypatch.delenv("DUCTA_SPARK_QUIET", raising=False)
        assert _quiet_log4j_file() is None
        monkeypatch.setenv("DUCTA_SPARK_QUIET", "0")
        assert _quiet_log4j_file() is None
