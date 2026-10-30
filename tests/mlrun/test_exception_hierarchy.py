"""Regression tests: mlrun exception hierarchy must route through MLOpsException.

Previously ValidationError was a plain ValueError subclass — code catching
MLOpsException to handle "any Ducta error" uniformly silently missed it.
"""

from __future__ import annotations

import pytest

from ducta.mlrun.exceptions import MLOpsException
from ducta.mlrun.validators import PathValidator, ValidationError


class TestValidationErrorHierarchy:
    def test_is_mlops_exception(self):
        assert issubclass(ValidationError, MLOpsException)

    def test_raised_by_path_validator_is_catchable_as_mlops_exception(self, tmp_path):
        with pytest.raises(MLOpsException):
            PathValidator.validate_path("../escape", tmp_path)
