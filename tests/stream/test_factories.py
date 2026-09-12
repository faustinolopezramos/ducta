"""Unit tests for ducta.stream.factories.StreamingHandlerFactory (the shared
lazy-instantiating, cache-on-first-use base used by the reader/writer
factories)."""

from __future__ import annotations

import pytest

from ducta.stream.exceptions import StreamingError, StreamingFormatNotSupportedError
from ducta.stream.factories import StreamingHandlerFactory


class _BaseHandler:
    def __init__(self, context, *extra_args, **extra_kwargs):
        self.context = context
        self.extra_args = extra_args
        self.extra_kwargs = extra_kwargs


class _JsonHandler(_BaseHandler):
    pass


class _CsvHandler(_BaseHandler):
    pass


class _NotAHandler:
    def __init__(self, context):
        self.context = context


class _BrokenHandler(_BaseHandler):
    def __init__(self, context):
        raise RuntimeError("cannot construct")


class _TestFactory(StreamingHandlerFactory):
    _KIND = "handler"
    _BASE_CLASS = _BaseHandler

    def _register_builtin_classes(self):
        self._classes = {
            "json": (_JsonHandler, (), {}),
            "csv": (_CsvHandler, (), {}),
        }


class TestLazyInstantiationAndCaching:
    def test_get_instantiates_lazily(self):
        factory = _TestFactory(context="ctx")
        handler = factory.get("json")
        assert isinstance(handler, _JsonHandler)
        assert handler.context == "ctx"

    def test_get_is_cached(self):
        factory = _TestFactory(context="ctx")
        first = factory.get("json")
        second = factory.get("json")
        assert first is second

    def test_format_is_case_insensitive(self):
        factory = _TestFactory(context="ctx")
        assert factory.get("JSON") is factory.get("json")


class TestUnsupportedOrInvalidFormat:
    def test_unsupported_format_raises(self):
        factory = _TestFactory(context="ctx")
        with pytest.raises(StreamingFormatNotSupportedError):
            factory.get("xml")

    def test_empty_format_name_raises(self):
        factory = _TestFactory(context="ctx")
        with pytest.raises(StreamingError):
            factory.get("")

    def test_non_string_format_name_raises(self):
        factory = _TestFactory(context="ctx")
        with pytest.raises(StreamingError):
            factory.get(None)


class TestRegisterCustom:
    def test_register_custom_adds_new_format(self):
        factory = _TestFactory(context="ctx")

        class _XmlHandler(_BaseHandler):
            pass

        factory.register_custom("xml", _XmlHandler)
        handler = factory.get("xml")
        assert isinstance(handler, _XmlHandler)

    def test_register_custom_rejects_wrong_base_class(self):
        factory = _TestFactory(context="ctx")
        with pytest.raises(StreamingError):
            factory.register_custom("bad", _NotAHandler)

    def test_register_custom_invalidates_cached_instance(self):
        factory = _TestFactory(context="ctx")
        original = factory.get("json")

        class _ReplacementJsonHandler(_BaseHandler):
            pass

        factory.register_custom("json", _ReplacementJsonHandler)
        replaced = factory.get("json")
        assert replaced is not original
        assert isinstance(replaced, _ReplacementJsonHandler)

    def test_register_custom_forwards_extra_args(self):
        factory = _TestFactory(context="ctx")
        factory.register_custom("custom", _BaseHandler, "extra_positional", key="value")
        handler = factory.get("custom")
        assert handler.extra_args == ("extra_positional",)
        assert handler.extra_kwargs == {"key": "value"}


class TestListSupportedFormats:
    def test_list_supported_formats(self):
        factory = _TestFactory(context="ctx")
        assert sorted(factory.list_supported_formats()) == ["csv", "json"]


class TestInstantiationFailure:
    def test_constructor_failure_wraps_as_streaming_error(self):
        factory = _TestFactory(context="ctx")
        factory.register_custom("broken", _BrokenHandler)
        with pytest.raises(StreamingError) as exc_info:
            factory.get("broken")
        assert exc_info.value.cause is not None
        assert isinstance(exc_info.value.cause, RuntimeError)
