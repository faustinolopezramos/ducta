"""Regression tests for `TemplateCommand`'s `--project-name`/`--sandbox-developers` validation.

`_validate_project_name` only checked for an empty string; `sandbox_developers`
had no validation at all. `project_name` becomes the default output directory
name (`./{project_name}`) and each `sandbox_developers` entry becomes a
`config/sandbox_<dev>` directory name, both via `Path.joinpath` +
`mkdir(parents=True)` — so `--project-name ../../etc` or
`--sandbox-developers ../../tmp/evil` escaped the intended output directory.
"""

from __future__ import annotations

from ducta.console.core import ExitCode
from ducta.console.template import TemplateCommand


class TestValidateProjectName:
    def test_valid_name_passes(self):
        cmd = TemplateCommand()
        assert cmd._validate_project_name("my_project-1") is None

    def test_empty_name_rejected(self):
        cmd = TemplateCommand()
        assert cmd._validate_project_name("") == ExitCode.VALIDATION_ERROR.value

    def test_path_traversal_rejected(self):
        cmd = TemplateCommand()
        assert cmd._validate_project_name("../../etc") == ExitCode.VALIDATION_ERROR.value

    def test_path_separator_rejected(self):
        cmd = TemplateCommand()
        assert cmd._validate_project_name("foo/bar") == ExitCode.VALIDATION_ERROR.value

    def test_absolute_path_rejected(self):
        cmd = TemplateCommand()
        assert cmd._validate_project_name("/etc/passwd") == ExitCode.VALIDATION_ERROR.value


class TestValidateSandboxDevelopers:
    def test_none_is_allowed(self):
        cmd = TemplateCommand()
        assert cmd._validate_sandbox_developers(None) is None

    def test_valid_names_pass(self):
        cmd = TemplateCommand()
        assert cmd._validate_sandbox_developers(["alice", "bob-2"]) is None

    def test_path_traversal_entry_rejected(self):
        cmd = TemplateCommand()
        result = cmd._validate_sandbox_developers(["alice", "../../tmp/evil"])
        assert result == ExitCode.VALIDATION_ERROR.value

    def test_absolute_path_entry_rejected(self):
        cmd = TemplateCommand()
        result = cmd._validate_sandbox_developers(["/etc/passwd"])
        assert result == ExitCode.VALIDATION_ERROR.value


class TestHandleTemplateCommandRejectsBadInputBeforeGenerating(object):
    def test_traversal_project_name_short_circuits(self, monkeypatch):
        cmd = TemplateCommand()
        called = {"generate": False}

        def _fake_generate(*args, **kwargs):
            called["generate"] = True
            return ExitCode.SUCCESS.value

        monkeypatch.setattr(cmd, "_generate_template", _fake_generate)

        result = cmd.handle_template_command(
            template_type="medallion_basic",
            project_name="../../etc",
        )

        assert result == ExitCode.VALIDATION_ERROR.value
        assert called["generate"] is False

    def test_traversal_sandbox_developer_short_circuits(self, monkeypatch):
        cmd = TemplateCommand()
        called = {"generate": False}

        def _fake_generate(*args, **kwargs):
            called["generate"] = True
            return ExitCode.SUCCESS.value

        monkeypatch.setattr(cmd, "_generate_template", _fake_generate)

        result = cmd.handle_template_command(
            template_type="medallion_basic",
            project_name="my_project",
            sandbox_developers=["../../tmp/evil"],
        )

        assert result == ExitCode.VALIDATION_ERROR.value
        assert called["generate"] is False
