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

``ducta init project`` — a new project with the recommended layout.

It is ``ducta template`` with the project type spelled for people (batch, ml,
streaming, hybrid) and the split layout as the default.
"""

from __future__ import annotations

#: What the user asks for → the template that builds it.
PROJECT_TYPES = {
    "batch": "medallion_basic",
    "ml": "ml_basic",
    "streaming": "streaming_basic",
    "hybrid": "hybrid_basic",
}


def handle_init_project(parsed_args) -> int:
    from ducta.console.template import TemplateCommand

    return TemplateCommand().handle_template_command(
        template_type=PROJECT_TYPES[getattr(parsed_args, "project_type", None) or "batch"],
        project_name=parsed_args.name,
        output_path=getattr(parsed_args, "path", None),
        config_format=getattr(parsed_args, "config_format", None) or "yaml",
        layout=getattr(parsed_args, "layout", None) or "split",
    )
