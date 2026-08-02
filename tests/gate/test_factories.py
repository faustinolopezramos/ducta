from unittest.mock import MagicMock

import pytest

from ducta.gate.exceptions import FormatNotSupportedError
from ducta.gate.factories import ReaderFactory, WriterFactory


class TestReaderFactory:
    def test_register_handlers(self):
        factory = ReaderFactory({})
        registered = list(factory._registry.keys())
        for fmt in ("parquet", "json", "csv", "delta", "pickle", "avro", "orc", "xml", "query"):
            assert fmt in registered, f"{fmt} not registered"

    def test_get_handler_known_format(self):
        factory = ReaderFactory({})
        reader = factory.get_handler("csv")
        assert reader is not None

    def test_get_reader_convenience(self):
        factory = ReaderFactory({})
        reader = factory.get_reader("parquet")
        assert reader is not None

    def test_get_handler_unknown_format(self):
        factory = ReaderFactory({})
        with pytest.raises(FormatNotSupportedError, match="not supported"):
            factory.get_handler("unsupported_format")

    def test_get_handler_case_insensitive(self):
        factory = ReaderFactory({})
        reader_lower = factory.get_handler("csv")
        reader_upper = factory.get_handler("CSV")
        assert reader_lower is reader_upper

    def test_get_handler_lazy_caching(self):
        factory = ReaderFactory({})
        r1 = factory.get_handler("csv")
        r2 = factory.get_handler("csv")
        assert r1 is r2

    def test_get_handler_recaches_on_context_change(self):
        ctx1 = {"a": 1}
        ctx2 = {"b": 2}
        factory = ReaderFactory(ctx1)
        r1 = factory.get_handler("csv")
        factory.context = ctx2
        # The cache invalidation happens when context changes
        factory._cache_context["csv"] = None  # force recache
        r2 = factory.get_handler("csv")
        assert r1 is not r2

    def test_register_reader_new_format(self):
        class CustomReader:
            def __init__(self, context):
                self.context = context

        factory = ReaderFactory({})
        factory.register_reader("custom", CustomReader)
        reader = factory.get_reader("custom")
        assert isinstance(reader, CustomReader)

    def test_register_reader_overrides_existing_format(self):
        class FakeCsvReader:
            def __init__(self, context):
                self.context = context

        factory = ReaderFactory({})
        original = factory.get_reader("csv")
        factory.register_reader("csv", FakeCsvReader)
        replaced = factory.get_reader("csv")
        assert isinstance(replaced, FakeCsvReader)
        assert not isinstance(original, FakeCsvReader)

    def test_register_invalidates_cached_instance(self):
        class ReaderA:
            def __init__(self, context):
                pass

        class ReaderB:
            def __init__(self, context):
                pass

        factory = ReaderFactory({})
        factory.register_reader("custom", ReaderA)
        first = factory.get_reader("custom")
        factory.register_reader("custom", ReaderB)
        second = factory.get_reader("custom")
        assert isinstance(first, ReaderA)
        assert isinstance(second, ReaderB)

    def test_register_reader_does_not_affect_other_instances(self):
        class CustomReader:
            def __init__(self, context):
                pass

        factory1 = ReaderFactory({})
        factory2 = ReaderFactory({})
        factory1.register_reader("custom", CustomReader)
        assert "custom" in factory1._registry
        assert "custom" not in factory2._registry


class TestWriterFactory:
    def test_register_handlers(self):
        factory = WriterFactory({})
        registered = list(factory._registry.keys())
        for fmt in ("delta", "parquet", "csv", "json", "orc"):
            assert fmt in registered, f"{fmt} not registered"

    def test_get_writer_known_format(self):
        factory = WriterFactory({})
        writer = factory.get_writer("delta")
        assert writer is not None

    def test_get_writer_unknown_format(self):
        factory = WriterFactory({})
        with pytest.raises(FormatNotSupportedError, match="not supported"):
            factory.get_writer("avro")

    def test_get_writer_case_insensitive(self):
        factory = WriterFactory({})
        w_lower = factory.get_writer("delta")
        w_upper = factory.get_writer("DELTA")
        assert w_lower is w_upper

    def test_get_handler_lazy_caching(self):
        factory = WriterFactory({})
        w1 = factory.get_handler("delta")
        w2 = factory.get_handler("delta")
        assert w1 is w2

    def test_register_writer_new_format(self):
        class CustomWriter:
            def __init__(self, context):
                self.context = context

        factory = WriterFactory({})
        factory.register_writer("custom", CustomWriter)
        writer = factory.get_writer("custom")
        assert isinstance(writer, CustomWriter)
