"""A name ending in a newline is not a name: `$` matches before a final `\\n`."""

from __future__ import annotations

import pytest

from ducta.console.core import VALID_NAME_RE
from ducta.setting.connections import (
    ConnectionSpec,
    IngestionServiceError,
    validate_connection_name,
)


def test_console_names_refuse_a_trailing_newline():
    assert VALID_NAME_RE.match("run_1-a")
    assert VALID_NAME_RE.match("run1\n") is None


def test_a_connection_name_with_a_newline_would_have_broken_the_env_file():
    with pytest.raises(IngestionServiceError):
        validate_connection_name("db\n")
    with pytest.raises(IngestionServiceError):
        ConnectionSpec("db\n", "postgresql", "localhost", 5432, "d", "u", "p").validate()
    validate_connection_name("db_1")


@pytest.mark.parametrize(
    "module, name, good",
    [
        ("ducta_server.utils.validators", "_PROJECT_NAME_RE", "my_project"),
        ("ducta_server.utils.validators", "_ENV_NAME_RE", "dev-1"),
        ("ducta_server.routes.nodes", "_NODE_NAME_RE", "clean.orders"),
        ("ducta_server.routes.nodes", "_PY_IDENTIFIER_RE", "clean_orders"),
        ("ducta.check.storage", "_SAFE_RUN_ID_RE", "run-1"),
        ("ducta.ai.drafts", "DRAFT_ID", "abc-123"),
        ("ducta_server.routes.ai", "_JOB_ID", "0123456789ab"),
        ("ducta.mlrun.validators", "VALID_NAME_PATTERN", "model.v1"),
    ],
)
def test_the_other_name_patterns_refuse_it_too(module, name, good):
    import importlib

    pattern = getattr(importlib.import_module(module), name)
    assert pattern.match(good)
    assert pattern.match(good + "\n") is None
