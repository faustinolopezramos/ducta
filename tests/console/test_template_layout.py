"""The split layout: catalog/<layer>.* and quality/profiles.*, the same project as one file."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.console.template import ConfigFormat, TemplateError, TemplateGenerator, TemplateType
from ducta.console.template_layout import extract_profiles, layer_of, split_catalog
from ducta.setting.project_loader import compile_project, validate_project

_KINDS = ["medallion_basic", "streaming_basic", "ml_basic", "hybrid_basic"]


def _generate(root: Path, kind: str, fmt: ConfigFormat, layout: str) -> Path:
    TemplateGenerator(root, fmt, layout).generate_project(TemplateType(kind), "p")
    return root


@pytest.mark.parametrize("fmt", [ConfigFormat.YAML, ConfigFormat.TOML, ConfigFormat.JSON])
@pytest.mark.parametrize("kind", _KINDS)
def test_split_is_the_same_project_as_single(tmp_path, kind, fmt):
    single = _generate(tmp_path / "a", kind, fmt, "single")
    split = _generate(tmp_path / "b", kind, fmt, "split")
    for env in (None, "dev", "prod"):
        assert compile_project(validate_project(split, env)) == compile_project(
            validate_project(single, env)
        )


def test_split_writes_the_recommended_files(tmp_path):
    root = _generate(tmp_path, "medallion_basic", ConfigFormat.YAML, "split")
    assert not (root / "catalog.yaml").exists()
    assert {p.name for p in (root / "catalog").iterdir()} == {
        "sources.yaml",
        "bronze.yaml",
        "silver.yaml",
        "gold.yaml",
    }
    assert (root / "quality" / "profiles.yaml").is_file()
    assert "profiles:" not in (root / "ducta.yaml").read_text().replace("quality/profiles", "")
    assert (root / ".ducta" / "schema" / "profiles.json").is_file()


def test_split_files_point_at_the_schema_from_their_folder(tmp_path):
    root = _generate(tmp_path, "medallion_basic", ConfigFormat.YAML, "split")
    for f in (root / "catalog").iterdir():
        assert f.read_text().startswith(
            "# yaml-language-server: $schema=../.ducta/schema/catalog.json"
        )
    head = (root / "quality" / "profiles.yaml").read_text()
    assert "$schema=../.ducta/schema/profiles.json" in head


def test_the_comments_of_a_dataset_travel_with_it(tmp_path):
    root = _generate(tmp_path, "medallion_basic", ConfigFormat.YAML, "split")
    bronze = (root / "catalog" / "bronze.yaml").read_text()
    assert "defaults.catalog" in bronze and "bronze.etl.raw_data" in bronze
    sources = (root / "catalog" / "sources.yaml").read_text()
    assert "A contract" in sources


def test_an_empty_catalog_still_gets_a_file(tmp_path):
    root = _generate(tmp_path, "streaming_basic", ConfigFormat.YAML, "split")
    assert (root / "catalog" / "sources.yaml").is_file()
    validate_project(root)


def test_the_docs_point_at_the_folder(tmp_path):
    root = _generate(tmp_path, "medallion_basic", ConfigFormat.YAML, "split")
    assert "catalog.yaml" not in (root / "README.md").read_text()
    assert "catalog.yaml" not in (root / "ducta.yaml").read_text()


def test_unknown_layout_is_refused(tmp_path):
    with pytest.raises(TemplateError, match="Unknown layout"):
        TemplateGenerator(tmp_path, ConfigFormat.YAML, "nested")


class TestSplitCatalog:
    TEXT = """\
# yaml-language-server: $schema=x
# What this is.

raw: {format: csv, path: a}

# About bronze.
bronze.a.b:
  description: one
  # inner comment
  format: csv

silver.a.c: {format: delta}
"""

    def test_layers_in_order_of_appearance(self):
        assert list(split_catalog(self.TEXT)) == ["sources", "bronze", "silver"]

    def test_the_preface_goes_with_the_first_dataset_only(self):
        parts = split_catalog(self.TEXT)
        assert "What this is." in parts["sources"]
        assert "What this is." not in parts["bronze"]

    def test_comments_above_and_inside_a_dataset_stay_with_it(self):
        bronze = split_catalog(self.TEXT)["bronze"]
        assert bronze.startswith("# About bronze.\nbronze.a.b:")
        assert "# inner comment" in bronze

    def test_nothing_to_split(self):
        assert split_catalog("# only a comment\n{}\n") is None

    def test_layer_of(self):
        assert layer_of("silver.sales.orders") == "silver"
        assert layer_of("raw_sales") == "sources"


class TestExtractProfiles:
    TEXT = """\
settings:
  mode: local
  quality:
    # Modules with your own checks.
    profiles:
      default:
        checks:
          empty_dataset: {enabled: true}
  other: 1
environments: {}
"""

    def test_the_block_is_dedented_into_its_own_file(self):
        _, profiles = extract_profiles(self.TEXT)
        assert profiles == "default:\n  checks:\n    empty_dataset: {enabled: true}\n"

    def test_quality_is_never_left_empty(self):
        rest, _ = extract_profiles(self.TEXT)
        assert "profiles:" not in rest
        assert "quality/profiles.yaml" in rest
        assert "quality:\n" not in rest
        assert "other: 1" in rest

    def test_no_profiles_no_change(self):
        text = "settings:\n  mode: local\n"
        assert extract_profiles(text) == (text, None)
