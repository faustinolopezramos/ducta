"""Quality profiles kept in ``quality/profiles.yaml`` instead of ``ducta.yaml``."""

from pathlib import Path

import pytest

from ducta.setting.project_decompile import write_schemas
from ducta.setting.project_inspect import convert_project, explain
from ducta.setting.project_loader import ProjectConfigError, read_project, validate_project

PROFILES = """\
strict:
  checks:
    empty_dataset: {enabled: true}
lenient:
  checks:
    null_rate: {columns: [id], threshold: 0.5}
"""


def _project(root: Path, project_extra: str = "", profiles: str | None = PROFILES) -> Path:
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(
        "version: 2\nproject: p\npaths: {input: d, output: o}\n" + project_extra
    )
    (root / "catalog.yaml").write_text(
        "raw: {format: csv, path: x.csv}\nsilver.x.out: {format: delta}\n"
    )
    (root / "pipelines" / "p.yaml").write_text(
        "requires_dates: false\nnodes:\n  n:\n    run: m:f\n    inputs: [raw]\n    outputs: [silver.x.out]\n"
        "    quality: {profile: strict}\n"
    )
    if profiles is not None:
        (root / "quality").mkdir()
        (root / "quality" / "profiles.yaml").write_text(profiles)
    return root


def _profiles(project) -> set:
    return set(project.project.settings["quality"]["profiles"])


class TestMerging:
    def test_profiles_of_the_file_are_settings_quality_profiles(self, tmp_path):
        project = validate_project(_project(tmp_path))
        assert _profiles(project) == {"strict", "lenient"}

    def test_both_homes_can_hold_different_profiles(self, tmp_path):
        extra = (
            "settings:\n  quality:\n    profiles:\n      other: {checks: {empty_dataset: true}}\n"
        )
        project = validate_project(_project(tmp_path, extra))
        assert _profiles(project) == {"strict", "lenient", "other"}

    def test_the_same_profile_in_both_is_an_error(self, tmp_path):
        extra = (
            "settings:\n  quality:\n    profiles:\n      strict: {checks: {empty_dataset: true}}\n"
        )
        with pytest.raises(ProjectConfigError, match="profile 'strict' is also defined"):
            validate_project(_project(tmp_path, extra))

    def test_an_environment_can_override_a_profile_of_the_file(self, tmp_path):
        extra = (
            "environments:\n  prod:\n"
            "    settings.quality.profiles.lenient.checks.null_rate.threshold: 0.1\n"
        )
        project = validate_project(_project(tmp_path, extra), "prod")
        lenient = project.project.settings["quality"]["profiles"]["lenient"]
        assert lenient["checks"]["null_rate"]["threshold"] == 0.1

    def test_an_empty_file_is_not_an_error(self, tmp_path):
        validate_project(_project(tmp_path, profiles=""))

    def test_a_profiles_file_must_be_a_mapping(self, tmp_path):
        with pytest.raises(ProjectConfigError, match="maps profile names"):
            validate_project(_project(tmp_path, profiles="- a\n"))

    def test_two_formats_of_the_profiles_file_are_an_error(self, tmp_path):
        root = _project(tmp_path)
        (root / "quality" / "profiles.json").write_text("{}")
        with pytest.raises(ProjectConfigError, match="one profiles file"):
            validate_project(root)

    def test_it_is_what_a_node_resolves_its_profile_against(self, tmp_path):
        read = read_project(_project(tmp_path))
        assert set(read.file_profiles) == {"strict", "lenient"}


class TestInspection:
    def test_explain_cites_the_profiles_file(self, tmp_path):
        root = _project(tmp_path)
        text = str(explain(root, "settings.quality.profiles.strict", None))
        assert "quality/profiles.yaml" in text

    def test_convert_carries_the_file_over(self, tmp_path):
        root = _project(tmp_path / "src")
        written = convert_project(root, tmp_path / "out", "toml")
        assert any(p.name == "profiles.toml" for p in written)
        assert _profiles(validate_project(tmp_path / "out")) == {"strict", "lenient"}

    def test_an_editor_schema_is_written_for_it(self, tmp_path):
        write_schemas(tmp_path)
        assert (tmp_path / ".ducta" / "schema" / "profiles.json").is_file()
