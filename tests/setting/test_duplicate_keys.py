"""A key written twice in one mapping is refused, not silently overwritten.

PyYAML (and `json`) keep the last value: a second `quality:` under `settings`
replaced the first one and Ducta said nothing. TOML already refuses it.
"""

import textwrap
from pathlib import Path

import pytest

from ducta.setting.project.files import load_yaml, parse
from ducta.setting.project.loader import ProjectConfigError, load_project_v2


def test_yaml_refuses_a_key_written_twice_and_names_both_lines():
    with pytest.raises(
        ValueError, match=r"duplicate key 'quality' \(line 3; first written on line 2\)"
    ):
        parse(Path("ducta.yaml"), "settings:\n  quality: {}\n  quality: {}\n")


def test_json_refuses_a_key_written_twice():
    with pytest.raises(ValueError, match="duplicate key 'a'"):
        parse(Path("ducta.json"), '{"a": 1, "a": 2}')


def test_the_same_key_in_different_mappings_is_fine():
    assert parse(Path("x.yaml"), "a: {k: 1}\nb: {k: 2}\n") == {"a": {"k": 1}, "b": {"k": 2}}


def test_a_yaml_merge_may_still_be_overridden():
    text = "base: &b {k: 1, j: 2}\nchild:\n  <<: *b\n  k: 3\n"
    assert load_yaml(text)["child"] == {"k": 3, "j": 2}


def test_a_project_with_a_duplicated_setting_does_not_load(tmp_path):
    root = tmp_path / "shop"
    (root / "pipelines").mkdir(parents=True)
    (root / "catalog.yaml").write_text("{}\n", encoding="utf-8")
    (root / "ducta.yaml").write_text(
        textwrap.dedent(
            """
            version: 2
            project: shop
            paths: {input: data, output: data}
            settings:
              quality: {gate: {on_fail: stop_all}}
              max_parallel_nodes: 2
              quality: {extensions: []}
            """
        ).lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="duplicate key 'quality'"):
        load_project_v2(root, "dev")


def test_an_unhashable_key_is_still_a_yaml_error():
    # `{{x}}` makes a mapping the key of a mapping: the loader must not trip over it
    # while looking for duplicates, but let PyYAML report it as invalid YAML.
    import yaml

    with pytest.raises(yaml.YAMLError, match="unhashable"):
        load_yaml("{{invalid}}")
