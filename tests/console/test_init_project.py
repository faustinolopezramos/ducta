"""``ducta init project`` creates a project with the recommended layout."""

from __future__ import annotations

import os

import pytest

from ducta.console.cli import UnifiedCLI
from ducta.console.core import ExitCode
from ducta.setting.project_inspect import diff_trees, resolved_tree
from ducta.setting.project_loader import compile_project, validate_project


def _run(cwd, *argv):
    previous = os.getcwd()
    os.chdir(cwd)
    try:
        return UnifiedCLI().run(["init", "project", *argv])
    finally:
        os.chdir(previous)


@pytest.mark.parametrize("kind", ["batch", "ml", "streaming", "hybrid"])
def test_every_type_creates_a_valid_split_project(tmp_path, kind):
    target = tmp_path / "demo"
    assert _run(tmp_path, "--name", "demo", "--type", kind, "--path", str(target)) == 0
    assert (target / "catalog").is_dir() and not (target / "catalog.yaml").exists()
    for env in (None, "dev", "prod"):
        compile_project(validate_project(target, env))


def test_default_is_a_batch_project_in_a_folder_named_after_it(tmp_path):
    assert _run(tmp_path, "--name", "sales") == 0
    assert (tmp_path / "sales" / "pipelines" / "etl.yaml").is_file()
    assert (tmp_path / "sales" / "quality" / "profiles.yaml").is_file()


def test_it_leaves_no_logs_dir_in_the_cwd(tmp_path):
    _run(tmp_path, "--name", "sales")
    assert not (tmp_path / "logs").exists()


def test_toml_is_the_same_project_as_yaml(tmp_path):
    _run(tmp_path, "--name", "a", "--type", "ml", "--path", str(tmp_path / "y"))
    _run(tmp_path, "--name", "a", "--type", "ml", "--format", "toml", "--path", str(tmp_path / "t"))
    assert not diff_trees(resolved_tree(tmp_path / "y", None), resolved_tree(tmp_path / "t", None))


def test_single_layout_keeps_one_catalog_file(tmp_path):
    assert _run(tmp_path, "--name", "a", "--layout", "single", "--path", str(tmp_path / "a")) == 0
    assert (tmp_path / "a" / "catalog.yaml").is_file()
    assert not (tmp_path / "a" / "catalog").exists()


def test_a_non_empty_directory_is_refused_untouched(tmp_path):
    target = tmp_path / "busy"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    assert (
        _run(tmp_path, "--name", "busy", "--path", str(target)) == ExitCode.VALIDATION_ERROR.value
    )
    assert [p.name for p in target.iterdir()] == ["keep.txt"]


def test_a_bad_name_is_refused(tmp_path):
    assert _run(tmp_path, "--name", "no spaces!") == ExitCode.VALIDATION_ERROR.value
