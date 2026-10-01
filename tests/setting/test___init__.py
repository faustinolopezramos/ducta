import importlib

import pytest

import ducta.setting as setting


@pytest.mark.parametrize("name", setting.__all__)
def test_every_public_name_is_importable(name):
    assert getattr(importlib.import_module("ducta.setting"), name) is not None


@pytest.mark.parametrize(
    "name",
    [
        "ContextLoader",
        "FlexibleConfigResolver",
        "LayeredProjectDetector",
        "LayerConfig",
        "LayerContextBuilder",
        "detect_and_prepare_layered_execution",
    ],
)
def test_the_format_1_loaders_are_gone(name):
    """The loaders for the old layered/flexible layouts no longer exist."""
    assert not hasattr(setting, name)
