"""Regression tests: mlrun exception hierarchy must route through MLOpsException.

Previously ValidationError/TransactionError/RollbackError were plain
ValueError/Exception subclasses, and OptimisticLock.check_version raised a
bare ValueError — code catching MLOpsException to handle "any Ducta error"
uniformly silently missed all of them.
"""

from __future__ import annotations

import pytest

from ducta.mlrun.concurrency import ConcurrencyError, OptimisticLock, TransactionError
from ducta.mlrun.exceptions import MLOpsException
from ducta.mlrun.validators import PathValidator, ValidationError


class TestValidationErrorHierarchy:
    def test_is_mlops_exception(self):
        assert issubclass(ValidationError, MLOpsException)

    def test_still_a_value_error_for_backward_compat(self):
        assert issubclass(ValidationError, ValueError)

    def test_raised_by_path_validator_is_catchable_as_mlops_exception(self, tmp_path):
        with pytest.raises(MLOpsException):
            PathValidator.validate_path("../escape", tmp_path)


class TestTransactionErrorHierarchy:
    def test_is_mlops_exception(self):
        assert issubclass(TransactionError, MLOpsException)


class TestOptimisticLockConcurrencyError:
    def test_version_mismatch_raises_concurrency_error(self):
        lock = OptimisticLock(initial_version=1)
        with pytest.raises(ConcurrencyError):
            lock.check_version(expected_version=2)

    def test_concurrency_error_is_mlops_exception(self):
        lock = OptimisticLock(initial_version=1)
        with pytest.raises(MLOpsException):
            lock.check_version(expected_version=2)
