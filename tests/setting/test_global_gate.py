"""`settings.quality.gate`, the project-wide gate, is written like a node's gate.

It used to be read with the engine's spelling (`behavior`) and to accept any key, so
`on_fail: stop_all` there was silently ignored: the gate stayed `skip_downstream`.
"""

import textwrap
from pathlib import Path

import pytest

from ducta.setting.project.loader import ProjectConfigError, load_project_v2


def _project(root: Path, gate: str) -> Path:
    (root / "pipelines").mkdir(parents=True)
    (root / "catalog.yaml").write_text("{}\n", encoding="utf-8")
    (root / "ducta.yaml").write_text(
        textwrap.dedent(
            f"""
            version: 2
            project: shop
            paths: {{input: data, output: data}}
            settings:
              quality:
                gate: {gate}
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return root


def test_on_fail_applies_to_the_project_wide_gate(tmp_path):
    root = _project(tmp_path / "shop", "{on_fail: stop_all, max_errors: 0}")

    gate = load_project_v2(root, "dev").global_config["quality"]["gate"]

    assert gate["behavior"] == "stop_all"
    assert gate["max_errors"] == 0


@pytest.mark.parametrize(
    "gate", ["{on_fail: block}", "{behaviour: stop_all}", "{block_threshold: 0.9}"]
)
def test_a_key_or_value_it_does_not_know_is_refused(tmp_path, gate):
    root = _project(tmp_path / "shop", gate)

    with pytest.raises(ProjectConfigError):
        load_project_v2(root, "dev")


def test_a_key_valid_elsewhere_is_not_suggested_as_itself(tmp_path):
    """`inputs` on a pipeline (a node's key) used to read "did you mean 'inputs'?"."""
    root = _project(tmp_path / "shop", "{max_errors: 0}")
    (root / "pipelines" / "etl.yaml").write_text(
        "inputs: [a]\nnodes:\n  n:\n    run: m:f\n    outputs: [b]\n", encoding="utf-8"
    )

    with pytest.raises(ProjectConfigError) as raised:
        load_project_v2(root, "dev")

    text = str(raised.value)
    assert "'inputs' is not valid at this level" in text
    assert "did you mean 'inputs'" not in text
