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


class TestAFailedGenerationLeavesNothingBehind:
    @staticmethod
    def _failing_generator(output_dir):
        from unittest.mock import MagicMock

        generator = MagicMock()

        def generate(*_args, **_kwargs):
            (output_dir / "pipelines").mkdir(parents=True)
            (output_dir / "ducta.yaml").write_text("half")
            raise OSError("disk full")

        generator.generate_project.side_effect = generate
        return generator

    def test_a_new_folder_is_removed_so_the_command_can_be_run_again(self, tmp_path):
        from unittest.mock import patch

        target = tmp_path / "proj"
        with patch("ducta.console.template.TemplateGenerator") as make:
            make.return_value = self._failing_generator(target)
            code = TemplateCommand()._generate_template(
                "medallion_basic", "proj", str(target), True
            )
        assert code == ExitCode.GENERAL_ERROR.value
        assert not target.exists()

    def test_an_empty_folder_that_was_there_is_kept_but_emptied(self, tmp_path):
        from unittest.mock import patch

        target = tmp_path / "proj"
        target.mkdir()
        with patch("ducta.console.template.TemplateGenerator") as make:
            make.return_value = self._failing_generator(target)
            TemplateCommand()._generate_template("medallion_basic", "proj", str(target), True)
        assert target.is_dir() and list(target.iterdir()) == []


class TestListTemplatesIsPlainStdout:
    """`--list-templates` went through the logger: every line carried the
    `Ducta: [hh:mm] INFO` prefix and long descriptions were wrapped."""

    def test_list_is_printed_without_log_prefix(self, capsys):
        assert TemplateCommand().handle_template_command(list_templates=True) == 0
        out = capsys.readouterr().out
        assert "medallion_basic" in out
        assert "INFO" not in out
        line = next(ln for ln in out.splitlines() if "bronze/silver/gold" in ln)
        assert "block on real defects" in line
