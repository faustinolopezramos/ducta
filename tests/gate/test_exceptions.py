import pytest

from ducta.gate.exceptions import (
    ConfigurationError,
    DataValidationError,
    FormatNotSupportedError,
    IOManagerError,
    MissingDependencyError,
    ReadOperationError,
    WriteOperationError,
)


class TestExceptionHierarchy:
    def test_io_manager_error_is_base(self):
        assert issubclass(ConfigurationError, IOManagerError)
        assert issubclass(DataValidationError, IOManagerError)
        assert issubclass(FormatNotSupportedError, IOManagerError)
        assert issubclass(ReadOperationError, IOManagerError)
        assert issubclass(WriteOperationError, IOManagerError)

    def test_missing_dependency_is_read_error(self):
        assert issubclass(MissingDependencyError, ReadOperationError)

    def test_all_exceptions_are_exception_subclasses(self):
        for exc in [
            IOManagerError,
            ConfigurationError,
            DataValidationError,
            FormatNotSupportedError,
            ReadOperationError,
            WriteOperationError,
            MissingDependencyError,
        ]:
            assert issubclass(exc, Exception)

    def test_exception_messages(self):
        assert str(ConfigurationError("bad config")) == "bad config"
        assert str(DataValidationError("invalid data")) == "invalid data"
        assert str(FormatNotSupportedError("bad format")) == "bad format"
        assert str(ReadOperationError("read failed")) == "read failed"
        assert str(WriteOperationError("write failed")) == "write failed"
        assert str(MissingDependencyError("missing dep")) == "missing dep"

    def test_raise_and_catch_io_manager(self):
        with pytest.raises(IOManagerError):
            raise ConfigurationError("test")

    def test_raise_and_catch_read_error(self):
        with pytest.raises(ReadOperationError):
            raise MissingDependencyError("test")
