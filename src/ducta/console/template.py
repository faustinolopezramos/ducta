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

The ``ducta template`` command: generate a project from one of the templates.
"""

from pathlib import Path
from typing import List, Optional, cast

from loguru import logger

from ducta import state
from ducta.console.core import VALID_NAME_RE as _VALID_NAME_RE
from ducta.console.core import ConfigFormat, ExitCode
from ducta.console.templates import (
    BaseTemplate,
    TemplateError,
    TemplateFactory,
    TemplateGenerator,
    TemplateType,
)

_TEMPLATE_CANCELLED_MSG = "Template generation cancelled"


class TemplateCommand:
    """Handles the --template command functionality."""

    def __init__(self):
        self.generator = None

    def handle_template_command(
        self,
        template_type: Optional[str] = None,
        project_name: Optional[str] = None,
        output_path: Optional[str] = None,
        create_sample_code: bool = True,
        list_templates: bool = False,
        sandbox_developers: Optional[List[str]] = None,
        evidence_level: str = "record",
        config_format: str = "yaml",
        layout: str = "single",
    ) -> int:
        """Handle template generation command."""
        try:
            if list_templates:
                return self._list_templates()

            validation_error = self._validate_inputs(template_type, project_name)
            if validation_error:
                return validation_error

            validation_error = self._validate_sandbox_developers(sandbox_developers)
            if validation_error:
                return validation_error

            return self._generate_template(
                cast(str, template_type),  # _validate_inputs refused a missing one
                cast(str, project_name),
                output_path,
                create_sample_code,
                sandbox_developers,
                evidence_level,
                config_format,
                layout,
            )

        except TemplateError as e:
            logger.error("Template error: {}", e)
            return e.exit_code
        except Exception as e:
            logger.error("Unexpected error: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _list_templates(self) -> int:
        """List all available templates."""
        templates = TemplateFactory.list_available_templates()

        # Data for the user, not log records: plain stdout, so lines keep
        # their width (the logger prefixed and wrapped every one) and the
        # list can be piped.
        lines = ["Available template types:", ""]
        for template in templates:
            lines.append(f"  {template['type']:20} {template['name']}")
            lines.append(f"  {'':20} {template['description']}")
            lines.append("")
        lines += [
            "Usage:",
            "  ducta template --template <type> --project-name <name> [options]",
            "",
            "Examples:",
            "  ducta template --template medallion_basic --project-name my_pipeline",
            "  ducta template --template streaming_basic --project-name events --evidence-level signed",
        ]
        print("\n".join(lines))

        return ExitCode.SUCCESS.value

    def _validate_inputs(
        self, template_type: Optional[str], project_name: Optional[str]
    ) -> Optional[int]:
        """Validate required command-line inputs."""
        if not template_type or not project_name:
            logger.error("Template type and project name are required")
            logger.info("Use --list-templates to see available templates")
            return ExitCode.VALIDATION_ERROR.value

        error = self._validate_project_name(project_name)
        if error:
            return error

        return None

    def _validate_project_name(self, project_name: str) -> Optional[int]:
        """Validate project name."""
        if not project_name:
            logger.error("Project name cannot be empty")
            return ExitCode.VALIDATION_ERROR.value
        if not _VALID_NAME_RE.match(project_name):
            logger.error(
                "Invalid project name '{}'. Use only letters, numbers, underscores, and hyphens.",
                project_name,
            )
            return ExitCode.VALIDATION_ERROR.value
        return None

    def _validate_sandbox_developers(
        self, sandbox_developers: Optional[List[str]]
    ) -> Optional[int]:
        """Validate --sandbox-developers entries (each becomes a directory name)."""
        for dev in sandbox_developers or []:
            if not dev or not _VALID_NAME_RE.match(dev):
                logger.error(
                    "Invalid sandbox developer name '{}'. Use only letters, numbers, "
                    "underscores, and hyphens.",
                    dev,
                )
                return ExitCode.VALIDATION_ERROR.value
        return None

    @staticmethod
    def _parse_enum_or_error(enum_cls, value: str, label: str, available_label: str):
        """Parse *value* as *enum_cls*, or log the invalid value and its
        allowed options under *label*/*available_label* and return ``None``."""
        try:
            return enum_cls(value)
        except ValueError:
            available = [member.value for member in enum_cls]
            logger.error("Invalid {}: {}", label, value)
            logger.info("Available {}: {}", available_label, ", ".join(available))
            return None

    def _generate_template(
        self,
        template_type: str,
        project_name: str,
        output_path: Optional[str],
        create_sample_code: bool,
        sandbox_developers: Optional[List[str]] = None,
        evidence_level: str = "record",
        config_format: str = "yaml",
        layout: str = "single",
    ) -> int:
        """Generate template with specified parameters."""
        try:
            template_enum = self._parse_enum_or_error(
                TemplateType, template_type, "template type", "types"
            )
            if template_enum is None:
                return ExitCode.VALIDATION_ERROR.value

            if not output_path:
                output_path = f"./{project_name}"

            output_dir = Path(output_path)

            if output_dir.exists() and any(output_dir.iterdir()):
                logger.warning("Directory {} already exists and is not empty", output_dir)
                logger.info(_TEMPLATE_CANCELLED_MSG)
                return ExitCode.VALIDATION_ERROR.value

            self.generator = TemplateGenerator(output_dir, ConfigFormat(config_format), layout)
            # Missing or empty up to here (checked above): whatever is inside afterwards is
            # what this run wrote.
            existed = output_dir.exists()
            try:
                self.generator.generate_project(
                    template_enum,
                    project_name,
                    create_sample_code,
                    sandbox_developers,
                    evidence_level=evidence_level,
                )
            except BaseException:
                self._discard_partial_project(output_dir, keep_folder=existed)
                raise

            self._show_success_message(project_name, output_dir, self.generator.template)

            return ExitCode.SUCCESS.value

        except Exception as e:
            logger.error("Template generation failed: {}", e)
            return ExitCode.GENERAL_ERROR.value

    @staticmethod
    def _discard_partial_project(output_dir: Path, keep_folder: bool) -> None:
        """Remove what a failed generation wrote, so the same command can be run again.

        Left behind, the half-written folder made the retry answer "already exists and is
        not empty".
        """
        import shutil

        try:
            if not keep_folder:
                shutil.rmtree(output_dir, ignore_errors=True)
                return
            for child in output_dir.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Could not clean up the partial project in {}: {}", output_dir, e)
        else:
            logger.info("Removed the partial project in {}", output_dir)

    def _show_success_message(
        self, project_name: str, output_dir: Path, template: "BaseTemplate"
    ) -> None:
        """Show success message with next steps, tailored to *template*'s
        module path, default pipeline and run command — these differ between
        a batch template (``ducta start``) and a streaming one (``ducta
        stream run``)."""
        ext = self.generator.config_format.value if self.generator else "yaml"
        split = bool(self.generator and self.generator.layout == "split")
        logger.debug("Project '{}' created at {}", project_name, output_dir.absolute())

        from ducta.console.ux.view import console, display_path, is_compact

        if not is_compact():
            logger.success("Project '{}' created at {}", project_name, output_dir.absolute())

        from rich.text import Text

        out = console()
        head = Text()
        head.append("✓ ", style="bold green")
        head.append(f"Created {project_name}", style="bold")
        head.append(f" in {display_path(output_dir)}/", style="dim")
        out.print(head, soft_wrap=True)

        generated = [
            (f"ducta.{ext}", "project, paths, settings, per-environment overrides"),
            ("catalog/" if split else f"catalog.{ext}", "every dataset, once"),
        ]
        if split:
            generated.append(("quality/", f"reusable quality profiles (profiles.{ext})"))
        generated += [
            ("pipelines/", "one file per pipeline, plus the Python it runs"),
            (f"{state.SCHEMA_DIR}/", "JSON Schemas: editor autocompletion and inline errors"),
        ]
        width = max(len(name) for name, _ in generated) + 3
        out.print()
        for name, what in generated:
            line = Text("  ")
            line.append(name.ljust(width), style="cyan")
            line.append(what, style="dim")
            out.print(line, soft_wrap=True)

        out.print()
        out.print(Text("Next:", style="bold"))
        for step in (f"cd {display_path(output_dir)}", "pip install -r requirements.txt", ""):
            out.print(Text(f"  {step}" if step else ""), soft_wrap=True)
        for step_line in template.quick_start():
            style = "dim" if step_line.startswith("#") else ""
            out.print(Text(f"  {step_line}" if step_line else "", style=style), soft_wrap=True)
        out.print()
        tip = Text("  ")
        tip.append("Then point ", style="dim")
        tip.append("catalog/" if split else f"catalog.{ext}", style="cyan")
        tip.append(" at your data and edit ", style="dim")
        tip.append(
            f"{'/'.join(template.SAMPLE_MODULE_PATH)}",
            style="cyan",
        )
        tip.append(". README.md walks through it.", style="dim")
        out.print(tip, soft_wrap=True)


def handle_template_command(parsed_args) -> int:
    """Handle template command execution from CLI."""
    template_cmd = TemplateCommand()

    return template_cmd.handle_template_command(
        template_type=parsed_args.template,
        project_name=parsed_args.project_name,
        output_path=parsed_args.output_path,
        create_sample_code=not parsed_args.no_sample_code,
        list_templates=parsed_args.list_templates,
        sandbox_developers=getattr(parsed_args, "sandbox_developers", None),
        evidence_level=getattr(parsed_args, "evidence_level", None) or "record",
        config_format=getattr(parsed_args, "config_format", None) or "yaml",
        layout=getattr(parsed_args, "layout", None) or "single",
    )
