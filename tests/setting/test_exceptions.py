import pytest

from ducta.setting.exceptions import (
    ActiveConfigNotFound,
    ConfigLoadError,
    ConfigRepositoryError,
    ConfigurationError,
    ConfigValidationError,
    PipelineValidationError,
)


class TestExceptionHierarchy:
    def test_configuration_error_is_base(self):
        assert issubclass(ConfigLoadError, ConfigurationError)
        assert issubclass(ConfigValidationError, ConfigurationError)
        assert issubclass(PipelineValidationError, ConfigurationError)
        assert issubclass(ConfigRepositoryError, ConfigurationError)
        assert issubclass(ActiveConfigNotFound, ConfigurationError)

    def test_all_are_exception_subclasses(self):
        for exc in [
            ConfigurationError,
            ConfigLoadError,
            ConfigValidationError,
            PipelineValidationError,
            ConfigRepositoryError,
            ActiveConfigNotFound,
        ]:
            assert issubclass(exc, Exception)

    def test_exception_messages(self):
        assert str(ConfigLoadError("load failed")) == "load failed"
        assert str(ConfigValidationError("invalid")) == "invalid"
        assert str(PipelineValidationError("pipeline err")) == "pipeline err"
        assert str(ConfigRepositoryError("repo err")) == "repo err"
        assert str(ActiveConfigNotFound("not found")) == "not found"

    def test_raise_and_catch_base(self):
        with pytest.raises(ConfigurationError):
            raise ConfigLoadError("test")
