"""`ducta template` must not create a `logs/` directory in the caller's cwd.

The default log sink is project-relative on purpose: `ducta template` scaffolds a
`logs/` directory into generated projects and gitignores it, so a run inside a
project leaves its log beside the data it produced. That only makes sense for
commands that operate on a project. `template` runs before one exists, so it
created `./logs/ducta.log` in whatever directory the user was standing in — and
then `validate_template_arguments` saw that directory as "not empty" and refused
`--output-path .`, in a directory that had been empty a moment earlier.
"""

from __future__ import annotations

import os

from ducta.console.cli import _PROJECTLESS_SUBCOMMANDS, UnifiedCLI


def _run_in(tmp_path, argv):
    previous = os.getcwd()
    os.chdir(tmp_path)
    try:
        return UnifiedCLI().run(argv)
    finally:
        os.chdir(previous)


def test_template_is_marked_projectless():
    assert "template" in _PROJECTLESS_SUBCOMMANDS


def test_template_leaves_no_logs_dir_in_the_cwd(tmp_path):
    _run_in(
        tmp_path,
        [
            "template",
            "--template",
            "medallion_basic",
            "--project-name",
            "demo",
            "--output-path",
            str(tmp_path / "demo"),
        ],
    )
    assert not (tmp_path / "logs").exists()


def test_template_into_an_empty_cwd_succeeds(tmp_path):
    """The user-visible symptom: this failed in a directory that *was* empty."""
    rc = _run_in(
        tmp_path,
        [
            "template",
            "--template",
            "medallion_basic",
            "--project-name",
            "demo",
            "--output-path",
            ".",
        ],
    )
    assert rc == 0, "scaffolding into an empty directory must not report it as non-empty"
    assert (tmp_path / "environment.yaml").exists()


def test_an_explicit_log_file_is_still_honoured(tmp_path):
    """file_logging=False suppresses only the *default* sink.

    Exercised against `LoggerManager` directly: `--log-file` is declared on the
    `start` subcommand only, so no `template` invocation can carry one. The
    guard still matters — an explicit destination names a path the caller chose,
    which is never the accidental-cwd case this flag exists to prevent.
    """
    from ducta.console.core import LoggerManager

    target = tmp_path / "custom" / "run.log"
    LoggerManager.setup(log_file=str(target), file_logging=False)
    try:
        from loguru import logger

        logger.enable("ducta")
        logger.info("marker")
    finally:
        LoggerManager.setup()
    assert target.exists()


def test_default_sink_is_suppressed_when_file_logging_is_off(tmp_path):
    from ducta.console.core import LoggerManager

    previous = os.getcwd()
    os.chdir(tmp_path)
    try:
        LoggerManager.setup(file_logging=False)
        assert not (tmp_path / "logs").exists()
        LoggerManager.setup(file_logging=True)
        assert (tmp_path / "logs").exists(), "the default sink must still work when enabled"
    finally:
        LoggerManager.setup()
        os.chdir(previous)
