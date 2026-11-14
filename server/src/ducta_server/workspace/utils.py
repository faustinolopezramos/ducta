"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

CONFIG_EXTENSIONS = (".yaml", ".yml", ".json", ".toml")


def resolve_module_path(workspace_root: Path, module_dotted: str) -> Path:
    """Convert a dotted module path to a ``.py`` file path inside *workspace_root*."""
    from ducta.project_store.fileops import safe_path

    parts = module_dotted.split(".")
    relative = Path(*parts).with_suffix(".py")
    return safe_path(workspace_root, str(relative))
