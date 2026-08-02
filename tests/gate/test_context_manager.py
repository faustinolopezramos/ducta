import pytest

from ducta.gate.context_manager import ContextManager
from ducta.gate.exceptions import ConfigurationError


class TestContextManagerInit:
    def test_with_dict(self):
        cm = ContextManager({"key": "val"})
        assert cm._is_dict_context is True

    def test_with_object(self):
        class Obj:
            key = "val"

        cm = ContextManager(Obj())
        assert cm._is_dict_context is False

    def test_with_none_raises(self):
        with pytest.raises(ConfigurationError, match="Context cannot be None"):
            ContextManager(None)


class TestContextManagerGet:
    def test_get_existing_dict_key(self):
        cm = ContextManager({"a": 1, "b": 2})
        assert cm.get("a") == 1

    def test_get_missing_dict_key(self):
        cm = ContextManager({"a": 1})
        assert cm.get("missing") is None

    def test_get_missing_dict_key_with_default(self):
        cm = ContextManager({"a": 1})
        assert cm.get("missing", "default") == "default"

    def test_get_existing_obj_attr(self):
        class Obj:
            val = 42

        cm = ContextManager(Obj())
        assert cm.get("val") == 42

    def test_get_missing_obj_attr(self):
        class Obj:
            pass

        cm = ContextManager(Obj())
        assert cm.get("missing") is None

    def test_get_missing_obj_attr_with_default(self):
        class Obj:
            pass

        cm = ContextManager(Obj())
        assert cm.get("missing", "fallback") == "fallback"

    def test_get_with_exception(self):
        class BadObj:
            def __getattr__(self, name):
                raise RuntimeError("boom")

        cm = ContextManager(BadObj())
        assert cm.get("anything") is None


class TestContextManagerGetSpark:
    def test_spark_present_dict(self):
        spark = object()
        cm = ContextManager({"spark": spark})
        assert cm.get_spark() is spark

    def test_spark_absent_dict(self):
        cm = ContextManager({"a": 1})
        assert cm.get_spark() is None


class TestContextManagerExecutionMode:
    def test_local_from_string(self):
        cm = ContextManager({"execution_mode": "local"})
        assert cm.get_execution_mode() == "local"

    def test_distributed_from_string(self):
        cm = ContextManager({"execution_mode": "distributed"})
        assert cm.get_execution_mode() == "distributed"

    def test_databricks_normalized(self):
        cm = ContextManager({"execution_mode": "databricks"})
        assert cm.get_execution_mode() == "distributed"

    def test_none_mode(self):
        cm = ContextManager({"a": 1})
        assert cm.get_execution_mode() is None

    def test_empty_mode(self):
        cm = ContextManager({"execution_mode": ""})
        assert cm.get_execution_mode() is None

    def test_mode_from_enum(self):
        from ducta.gate.constants import ExecutionMode

        cm = ContextManager({"execution_mode": ExecutionMode.LOCAL})
        assert cm.get_execution_mode() == "local"

    def test_case_insensitive(self):
        cm = ContextManager({"execution_mode": "LOCAL"})
        assert cm.get_execution_mode() == "local"


class TestContextManagerIsLocal:
    def test_local(self):
        cm = ContextManager({"execution_mode": "local"})
        assert cm.is_local_mode() is True

    def test_distributed(self):
        cm = ContextManager({"execution_mode": "distributed"})
        assert cm.is_local_mode() is False

    def test_none(self):
        cm = ContextManager({})
        assert cm.is_local_mode() is False


class TestContextManagerIsSparkAvailable:
    def test_available(self):
        cm = ContextManager({"spark": object()})
        assert cm.is_spark_available() is True

    def test_not_available(self):
        cm = ContextManager({})
        assert cm.is_spark_available() is False

    def test_none_spark(self):
        cm = ContextManager({"spark": None})
        assert cm.is_spark_available() is False


class TestContextManagerGetNested:
    def test_dict_in_dict(self):
        cm = ContextManager({"global_settings": {"fingerprint_mode": "fast"}})
        assert cm.get_nested("global_settings.fingerprint_mode") == "fast"

    def test_object_in_dict(self):
        class Settings:
            fingerprint_mode = "thorough"

        cm = ContextManager({"global_settings": Settings()})
        assert cm.get_nested("global_settings.fingerprint_mode") == "thorough"

    def test_dict_in_object(self):
        class Ctx:
            global_settings = {"fingerprint_mode": "fast"}

        cm = ContextManager(Ctx())
        assert cm.get_nested("global_settings.fingerprint_mode") == "fast"

    def test_object_in_object(self):
        class Settings:
            fingerprint_mode = "thorough"

        class Ctx:
            global_settings = Settings()

        cm = ContextManager(Ctx())
        assert cm.get_nested("global_settings.fingerprint_mode") == "thorough"

    def test_missing_intermediate_returns_default(self):
        cm = ContextManager({})
        assert cm.get_nested("global_settings.fingerprint_mode", "fast") == "fast"

    def test_none_intermediate_returns_default(self):
        cm = ContextManager({"global_settings": None})
        assert cm.get_nested("global_settings.fingerprint_mode", "fast") == "fast"

    def test_intermediate_raises_returns_default(self):
        class BadSettings:
            def __getattr__(self, name):
                raise RuntimeError("boom")

        cm = ContextManager({"global_settings": BadSettings()})
        assert cm.get_nested("global_settings.fingerprint_mode", "fast") == "fast"

    def test_single_segment_path(self):
        cm = ContextManager({"spark": "session"})
        assert cm.get_nested("spark") == "session"


class TestContextManagerSet:
    def test_set_on_dict(self):
        context = {}
        cm = ContextManager(context)
        assert cm.set("key", "value") is True
        assert context["key"] == "value"

    def test_set_on_object_with_dict(self):
        class Ctx:
            pass

        ctx = Ctx()
        cm = ContextManager(ctx)
        assert cm.set("key", "value") is True
        assert ctx.key == "value"

    def test_set_on_object_with_slots_rejects(self):
        class SlottedCtx:
            __slots__ = ("existing",)

            def __init__(self):
                self.existing = 1

        ctx = SlottedCtx()
        cm = ContextManager(ctx)
        assert cm.set("new_key", "value") is False


class TestContextManagerGetOrCreateDict:
    def test_creates_when_absent(self):
        context = {}
        cm = ContextManager(context)
        result = cm.get_or_create_dict("_input_fingerprints")
        assert result == {}
        assert context["_input_fingerprints"] is result

    def test_returns_existing_same_object(self):
        existing = {"a": 1}
        context = {"_input_fingerprints": existing}
        cm = ContextManager(context)
        result = cm.get_or_create_dict("_input_fingerprints")
        assert result is existing

    def test_persists_across_calls(self):
        context = {}
        cm = ContextManager(context)
        first = cm.get_or_create_dict("_input_fingerprints")
        first["key"] = "value"
        second = cm.get_or_create_dict("_input_fingerprints")
        assert second is first
        assert second == {"key": "value"}

    def test_none_when_context_rejects_write(self):
        class SlottedCtx:
            __slots__ = ()

        cm = ContextManager(SlottedCtx())
        assert cm.get_or_create_dict("_input_fingerprints") is None
