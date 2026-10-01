"""Configuration format 1 on disk, for the tests of ``ducta config migrate``.

Ducta reads format 1 only when migrating it. Templates render the engine's
documents as that layout and then convert it; stopping before the conversion
yields exactly what a format-1 project looks like.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from ducta.console.template import TemplateGenerator, TemplateType


def format1_project(root: Path, kind: str = "medallion_basic", name: str = "proj") -> Path:
    with mock.patch.object(TemplateGenerator, "_convert_to_format2", lambda *_: None):
        TemplateGenerator(root).generate_project(TemplateType(kind), name)
    return root
