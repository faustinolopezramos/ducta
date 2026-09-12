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

from ducta.api.exceptions import PipelineNotFoundError
from ducta.api.repositories._yaml_record_repository import YamlRecordRepository


class PipelineRepository(YamlRecordRepository):
    """Reads and writes base pipeline records for a workspace root."""

    _config_key = "pipelines"
    _not_found_error = PipelineNotFoundError
    _config_label = "Pipelines"
    _action_label = "pipeline"

    def __init__(self, root: Path) -> None:
        self._root = root
