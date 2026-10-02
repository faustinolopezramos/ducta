"""A catalog split by layer: ``catalog/<layer>.yaml`` instead of one ``catalog.yaml``."""

from pathlib import Path

import pytest

from ducta.setting.project_loader import (
    ProjectConfigError,
    catalog_location,
    compile_project,
    read_project,
    validate_project,
)

PROJECT = "version: 2\nproject: p\npaths: {input: d, output: o}\n"
PIPELINE = """\
requires_dates: false
nodes:
  clean:
    run: m:clean
    inputs: {raw: bronze.x.raw}
    outputs: [silver.x.clean]
"""


def _split(root: Path) -> Path:
    (root / "catalog").mkdir(parents=True)
    (root / "pipelines").mkdir()
    (root / "ducta.yaml").write_text(PROJECT)
    (root / "catalog" / "bronze.yaml").write_text("bronze.x.raw: {format: csv, path: in.csv}\n")
    (root / "catalog" / "silver.yaml").write_text("silver.x.clean: {format: delta}\n")
    (root / "pipelines" / "p.yaml").write_text(PIPELINE)
    return root


class TestReading:
    def test_every_file_of_the_folder_joins_one_catalog(self, tmp_path):
        project = validate_project(_split(tmp_path))
        assert set(project.catalog) == {"bronze.x.raw", "silver.x.clean"}

    def test_it_compiles_like_the_single_file(self, tmp_path):
        split = compile_project(validate_project(_split(tmp_path / "a")))
        single = tmp_path / "b"
        (single / "pipelines").mkdir(parents=True)
        (single / "ducta.yaml").write_text(PROJECT)
        (single / "catalog.yaml").write_text(
            "bronze.x.raw: {format: csv, path: in.csv}\nsilver.x.clean: {format: delta}\n"
        )
        (single / "pipelines" / "p.yaml").write_text(PIPELINE)
        assert compile_project(validate_project(single)) == split

    def test_each_dataset_remembers_its_file(self, tmp_path):
        located = read_project(_split(tmp_path))
        assert located.catalog_files["silver.x.clean"].name == "silver.yaml"

    def test_nested_folders_are_read(self, tmp_path):
        root = _split(tmp_path)
        (root / "catalog" / "gold").mkdir()
        (root / "catalog" / "gold" / "kpi.yaml").write_text("gold.x.kpi: {format: delta}\n")
        assert "gold.x.kpi" in validate_project(root).catalog

    def test_an_empty_file_is_not_an_error(self, tmp_path):
        root = _split(tmp_path)
        (root / "catalog" / "gold.yaml").write_text("")
        validate_project(root)

    def test_the_location_is_the_folder(self, tmp_path):
        root = _split(tmp_path)
        assert catalog_location(root) == root / "catalog"


class TestMistakes:
    def test_a_dataset_declared_twice_names_both_files(self, tmp_path):
        root = _split(tmp_path)
        (root / "catalog" / "extra.yaml").write_text("silver.x.clean: {format: csv}\n")
        with pytest.raises(ProjectConfigError) as exc:
            validate_project(root)
        text = str(exc.value)
        assert "silver.x.clean" in text and "silver.yaml" in text and "extra.yaml" in text

    def test_catalog_file_and_folder_together_are_an_error(self, tmp_path):
        root = _split(tmp_path)
        (root / "catalog.yaml").write_text("{}\n")
        with pytest.raises(ProjectConfigError, match="not both"):
            validate_project(root)

    def test_errors_cite_the_file_in_the_folder(self, tmp_path):
        root = _split(tmp_path)
        (root / "catalog" / "silver.yaml").write_text(
            "silver.x.clean:\n  format: delta\n  frmat: x\n"
        )
        with pytest.raises(
            ProjectConfigError, match=r"catalog/silver\.yaml:\d+ catalog\.silver\.x\.clean"
        ):
            validate_project(root)

    def test_a_catalog_file_must_be_a_mapping(self, tmp_path):
        root = _split(tmp_path)
        (root / "catalog" / "bad.yaml").write_text("- a\n- b\n")
        with pytest.raises(ProjectConfigError, match="maps dataset names"):
            validate_project(root)
