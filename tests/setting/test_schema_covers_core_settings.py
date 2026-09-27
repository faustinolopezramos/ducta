"""Every global_config key CoreSettings reads must be declared in GlobalConfigSchema.

An undeclared key still works — the schema keeps extras — but it triggers the
"Unknown key … Ducta does not read it" warning, which then lies to the user
about a key Ducta does read. `max_streaming_pipelines`, written by the
streaming template itself, used to warn on the first run of a fresh project.
"""

from __future__ import annotations

import re
from pathlib import Path

from ducta.core import settings as core_settings
from ducta.setting.schemas import _RUNTIME_GLOBAL_CONFIG_KEYS, GlobalConfigSchema


def test_every_key_core_settings_reads_is_declared():
    source = Path(core_settings.__file__).read_text(encoding="utf-8")
    read = set(re.findall(r'gs\.get\("([a-z_]+)"', source))
    declared = set(GlobalConfigSchema.model_fields) | _RUNTIME_GLOBAL_CONFIG_KEYS

    assert read, "the pattern stopped matching — update this test"
    assert read - declared == set()
