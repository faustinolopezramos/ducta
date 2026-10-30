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

The project templates ``ducta template`` and the web app generate.

One module per template; :mod:`.base` holds what they share, :mod:`.factory` which
class builds which template, :mod:`.generator` the writing of a project folder.
"""

from ducta.console.templates.base import BaseTemplate, TemplateError, TemplateType
from ducta.console.templates.factory import TemplateFactory
from ducta.console.templates.generator import TemplateGenerator
from ducta.console.templates.hybrid_basic import HybridBasicTemplate
from ducta.console.templates.medallion_basic import MedallionBasicTemplate
from ducta.console.templates.ml_basic import MLBasicTemplate
from ducta.console.templates.ml_scoring import MLScoringTemplate
from ducta.console.templates.streaming_basic import StreamingBasicTemplate

__all__ = [
    "BaseTemplate",
    "HybridBasicTemplate",
    "MLBasicTemplate",
    "MLScoringTemplate",
    "MedallionBasicTemplate",
    "StreamingBasicTemplate",
    "TemplateError",
    "TemplateFactory",
    "TemplateGenerator",
    "TemplateType",
]
