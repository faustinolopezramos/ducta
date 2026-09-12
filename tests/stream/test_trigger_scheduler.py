"""Unit tests for ducta.stream.trigger_scheduler.TriggerScheduler.

There was previously no dedicated test file for this collaborator (extracted
from StreamingQueryManager) — these tests focus on the "adaptive" trigger and
on global_config resolution across both dict- and object-style contexts.
"""

from __future__ import annotations

from ducta.stream.trigger_scheduler import TriggerScheduler
from ducta.stream.validators import StreamingValidator


def _scheduler(context, progress_sink=None):
    return TriggerScheduler(context, StreamingValidator(), progress_sink=progress_sink)


class TestGlobalSettingContextSupport:
    def test_reads_global_setting_from_dict_context(self, dict_context):
        # Regression: _global_setting must resolve global_config from a plain
        # dict context, not only from an attribute-based object.
        dict_context = dict(dict_context)
        dict_context["global_config"] = {
            **dict_context["global_config"],
            "streaming_adaptive_base_interval": "7 seconds",
        }
        scheduler = _scheduler(dict_context)
        trigger = scheduler.configure_trigger({"type": "adaptive"})
        assert trigger == {"processingTime": "7 seconds"}

    def test_reads_global_setting_from_object_context(self, obj_context):
        obj_context.global_config["streaming_adaptive_base_interval"] = "7 seconds"
        scheduler = _scheduler(obj_context)
        trigger = scheduler.configure_trigger({"type": "adaptive"})
        assert trigger == {"processingTime": "7 seconds"}

    def test_default_when_context_has_no_global_config(self):
        scheduler = _scheduler({})
        assert scheduler._global_setting("streaming_adaptive_max_interval_seconds", 60.0) == 60.0


class TestAdaptiveTrigger:
    def test_falls_back_to_base_interval_without_history(self, obj_context):
        scheduler = _scheduler(obj_context, progress_sink=None)
        trigger = scheduler.configure_trigger({"type": "adaptive"}, query_name="q1")
        assert trigger == {"processingTime": "5 seconds"}

    def test_uses_progress_sink_history_when_available(self, obj_context):
        class _FakeSink:
            def avg_trigger_ms(self, query_name):
                return 2000.0  # 2s average trigger execution

        scheduler = _scheduler(obj_context, progress_sink=_FakeSink())
        trigger = scheduler.configure_trigger({"type": "adaptive"}, query_name="q1")
        # 2s * 1.5 = 3s target.
        assert trigger == {"processingTime": "3.000 seconds"}

    def test_clamps_to_configured_ceiling(self, obj_context):
        obj_context.global_config["streaming_adaptive_max_interval_seconds"] = 4.0

        class _FakeSink:
            def avg_trigger_ms(self, query_name):
                return 100_000.0  # would target 150s without clamping

        scheduler = _scheduler(obj_context, progress_sink=_FakeSink())
        trigger = scheduler.configure_trigger({"type": "adaptive"}, query_name="q1")
        assert trigger == {"processingTime": "4.000 seconds"}


class TestProcessingTimeTrigger:
    def test_default_interval(self, obj_context):
        scheduler = _scheduler(obj_context)
        assert scheduler.configure_trigger({}) == {"processingTime": "10 seconds"}

    def test_explicit_interval(self, obj_context):
        scheduler = _scheduler(obj_context)
        trigger = scheduler.configure_trigger({"type": "processing_time", "interval": "30 seconds"})
        assert trigger == {"processingTime": "30 seconds"}
