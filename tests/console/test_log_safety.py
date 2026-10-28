"""The log file: always DEBUG, kept a week — so private, and without credentials."""

from __future__ import annotations

import os
import stat
import sys

import pytest
from loguru import logger

from ducta.console.core import LoggerManager
from ducta.console.ux.log_safety import redacting_filter


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "ducta.log"
    LoggerManager.setup(level="INFO", log_file=str(path), quiet=True)
    yield path
    logger.remove()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_log_file_is_readable_by_its_owner_only(log_file):
    logger.info("hello")
    logger.complete()
    assert stat.S_IMODE(os.stat(log_file).st_mode) == 0o600


def test_credentials_in_a_message_never_reach_the_file(log_file):
    logger.info("connecting to postgresql://app:S3cr3t-pw@db.corp/x password=hunter2")
    logger.info("Authorization: Bearer abc.def.ghi")
    logger.complete()
    text = log_file.read_text()
    assert "S3cr3t-pw" not in text and "hunter2" not in text and "abc.def.ghi" not in text
    assert "db.corp/x" in text  # the rest of the line is kept


def test_an_ordinary_message_is_not_touched():
    record = {"message": "node clean finished in 3.2s"}
    assert redacting_filter(record) is True
    assert record["message"] == "node clean finished in 3.2s"


def test_the_filter_never_drops_a_record_or_raises():
    assert redacting_filter({"message": None}) is True
    assert redacting_filter({}) is True


def test_a_traceback_never_writes_a_credential_to_the_file(log_file):
    try:
        raise RuntimeError("login failed for jdbc:postgresql://db/x?user=app&password=hunter2")
    except RuntimeError:
        logger.exception("could not read source")
    logger.complete()
    text = log_file.read_text()
    assert "hunter2" not in text
    assert "Traceback" in text and "RuntimeError" in text  # the traceback itself is kept


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_a_rotated_log_is_zipped_for_its_owner_only(tmp_path):
    import zipfile

    from ducta.console.ux.log_safety import private_zip

    old = tmp_path / "ducta.2026-10-27.log"
    old.write_text("line\n")
    private_zip(str(old))
    archive = tmp_path / "ducta.2026-10-27.log.zip"
    assert not old.exists()
    assert stat.S_IMODE(os.stat(archive).st_mode) == 0o600
    assert zipfile.ZipFile(archive).read(old.name) == b"line\n"
