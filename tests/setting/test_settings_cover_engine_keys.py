"""Every setting the engine reads can be written in ``ducta.yaml``.

``settings:`` rejects unknown keys, so a key the engine reads from
``global_config`` but the schema does not declare cannot be configured at all:
the streaming engine read ``checkpoints_base`` and five ``streaming_*`` keys
that ``ducta config validate`` refused. This scans the engine for the keys it
reads and checks the schema declares them.
"""

from __future__ import annotations

import re
from pathlib import Path

from ducta.setting.schemas import _RUNTIME_GLOBAL_CONFIG_KEYS, GlobalConfigSchema

SRC = Path(__file__).resolve().parents[2] / "src" / "ducta"
ENGINE = ("core", "gate", "stream", "check", "mlrun", "setting")

_READS = [
    re.compile(r'(?:global_config|\bgs|\b_gs|\bgc)\s*\)?\s*\.get\(\s*"([a-z_]+)"'),
    re.compile(r'_ctx_get\("global_config",\s*\{\}\)\.get\("([a-z_]+)"'),
    re.compile(r'_global_setting\(\s*"([a-z_]+)"'),
]
#: Names the patterns catch that are not global settings: keys of a nested
#: block read through a variable of the same name, or of other documents.
_NOT_SETTINGS = {"env_hash", "token", "volume_name", "workspace_url", "into"}


def _engine_reads() -> dict:
    found: dict = {}
    for package in ENGINE:
        for path in (SRC / package).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for pattern in _READS:
                for match in pattern.finditer(text):
                    found.setdefault(match.group(1), set()).add(path.name)
    return found


def test_the_scan_finds_the_engine_settings():
    reads = _engine_reads()
    assert {"max_parallel_nodes", "checkpoints_base", "fingerprint_mode"} <= set(reads)


def test_every_setting_the_engine_reads_is_declared():
    declared = set(GlobalConfigSchema.model_fields) | set(_RUNTIME_GLOBAL_CONFIG_KEYS)
    missing = {
        key: sorted(files)
        for key, files in _engine_reads().items()
        if key not in declared and key not in _NOT_SETTINGS
    }
    assert not missing, f"read by the engine but rejected in settings: {missing}"
