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

Which class builds which template.
"""

from typing import Any, Dict, List

from ducta.console.core import ConfigFormat
from ducta.console.templates.base import TemplateError, TemplateType
from ducta.console.templates.hybrid_basic import HybridBasicTemplate
from ducta.console.templates.medallion_basic import MedallionBasicTemplate
from ducta.console.templates.ml_basic import MLBasicTemplate
from ducta.console.templates.ml_scoring import MLScoringTemplate
from ducta.console.templates.streaming_basic import StreamingBasicTemplate


class TemplateFactory:
    """Factory for creating template instances."""

    #: One place naming every template. The registry and the listing are derived
    #: from it, so adding a template cannot leave `--list-templates` behind.
    @staticmethod
    def _registry() -> Dict[TemplateType, Any]:
        return {
            TemplateType.MEDALLION_BASIC: MedallionBasicTemplate,
            TemplateType.STREAMING_BASIC: StreamingBasicTemplate,
            TemplateType.ML_BASIC: MLBasicTemplate,
            TemplateType.ML_SCORING: MLScoringTemplate,
            TemplateType.HYBRID_BASIC: HybridBasicTemplate,
        }

    @staticmethod
    def create_template(
        template_type: TemplateType,
        project_name: str,
        config_format: ConfigFormat = ConfigFormat.YAML,
    ) -> Any:
        """Create a template instance based on the given type."""
        template_class = TemplateFactory._registry().get(template_type)
        if template_class is None:
            raise TemplateError(f"Unknown template type: {template_type}")
        return template_class(project_name, config_format)

    @staticmethod
    def list_available_templates() -> List[Dict[str, str]]:
        """List all available templates with their metadata."""
        return [
            {
                "type": template_type.value,
                "name": template_class.TEMPLATE_NAME,
                "description": template_class.TEMPLATE_DESCRIPTION,
            }
            for template_type, template_class in TemplateFactory._registry().items()
        ]
