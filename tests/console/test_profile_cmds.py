"""Tests for `ducta profile`: the standalone assay command.

Standalone is the point of this command — it has to work on a bare file with no
project, no DAG and no Spark session, because it exists to be useful before
anyone has adopted the framework. These tests therefore drive it the way a user
would, through a real file on disk.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from ducta.console.commands.profile_cmds import ProfileCommands
from ducta.console.core import ExitCode


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "ventas.csv"
    pd.DataFrame(
        {
            "order_id": range(1, 51),
            "category": ["a", "b"] * 25,
            "amount": [float(i) for i in range(50)],
        }
    ).to_csv(path, index=False)
    return path


def _args(**overrides):
    defaults = {
        "input": None,
        "format": "csv",
        "output": None,
        "strictness": "balanced",
        "sample_rows": None,
        "dataset_name": None,
        "output_format": "rich",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestHappyPath:
    def test_it_succeeds_on_a_plain_csv(self, csv_file):
        assert ProfileCommands.handle(_args(input=str(csv_file))) == ExitCode.SUCCESS.value

    def test_it_writes_the_spec_where_asked(self, csv_file, tmp_path):
        out = tmp_path / "specs" / "ventas.yaml"

        result = ProfileCommands.handle(_args(input=str(csv_file), output=str(out)))

        assert result == ExitCode.SUCCESS.value
        assert out.exists()

    def test_it_creates_the_parent_directory(self, csv_file, tmp_path):
        out = tmp_path / "a" / "b" / "c.yaml"

        ProfileCommands.handle(_args(input=str(csv_file), output=str(out)))

        assert out.exists()

    def test_the_written_spec_is_valid_yaml_with_checks(self, csv_file, tmp_path):
        import yaml

        out = tmp_path / "spec.yaml"
        ProfileCommands.handle(_args(input=str(csv_file), output=str(out)))

        assert "checks" in yaml.safe_load(out.read_text())

    def test_the_written_spec_runs_against_the_file_it_came_from(self, csv_file, tmp_path):
        # The command tells the user to run exactly this; it has to work.
        import yaml

        from ducta.check.engine import ValidationPhaseRunner

        out = tmp_path / "spec.yaml"
        ProfileCommands.handle(_args(input=str(csv_file), output=str(out)))

        report = ValidationPhaseRunner(workspace_path=str(tmp_path)).run(
            dataset_name="ventas",
            df=pd.read_csv(csv_file),
            config=yaml.safe_load(out.read_text()),
        )

        assert report.passed

    def test_json_output_is_emitted(self, csv_file, capsys):
        import json

        ProfileCommands.handle(_args(input=str(csv_file), output_format="json"))

        payload = json.loads(capsys.readouterr().out.split("\n\n")[0])
        assert payload["profile"]["row_count"] == 50

    def test_the_dataset_name_can_be_overridden(self, csv_file, tmp_path):
        out = tmp_path / "spec.yaml"

        ProfileCommands.handle(_args(input=str(csv_file), output=str(out), dataset_name="pedidos"))

        assert "pedidos" in out.read_text()

    def test_it_prints_the_spec_when_no_output_is_given(self, csv_file, capsys):
        ProfileCommands.handle(_args(input=str(csv_file)))

        assert "checks:" in capsys.readouterr().out


class TestFailures:
    def test_a_missing_file_is_a_validation_error_not_a_crash(self, tmp_path):
        result = ProfileCommands.handle(_args(input=str(tmp_path / "nope.csv")))

        assert result == ExitCode.VALIDATION_ERROR.value

    def test_an_unsupported_format_is_a_validation_error(self, csv_file):
        result = ProfileCommands.handle(_args(input=str(csv_file), format="avro"))

        assert result == ExitCode.VALIDATION_ERROR.value

    def test_an_unwritable_destination_is_reported_not_raised(self, csv_file, tmp_path):
        blocker = tmp_path / "blocked"
        blocker.write_text("I am a file, not a directory")

        result = ProfileCommands.handle(
            _args(input=str(csv_file), output=str(blocker / "spec.yaml"))
        )

        assert result == ExitCode.GENERAL_ERROR.value


class TestArgumentValidation:
    def test_a_bad_strictness_is_rejected(self):
        from ducta.console.cli import validate_profile_arguments
        from ducta.console.core import ValidationError

        with pytest.raises(ValidationError):
            validate_profile_arguments(_args(input="x.csv", strictness="whatever"))

    def test_a_bad_format_is_rejected(self):
        from ducta.console.cli import validate_profile_arguments
        from ducta.console.core import ValidationError

        with pytest.raises(ValidationError):
            validate_profile_arguments(_args(input="x.csv", format="avro"))

    def test_a_negative_sample_size_is_rejected(self):
        from ducta.console.cli import validate_profile_arguments
        from ducta.console.core import ValidationError

        with pytest.raises(ValidationError):
            validate_profile_arguments(_args(input="x.csv", sample_rows=-5))

    def test_valid_arguments_pass(self):
        from ducta.console.cli import validate_profile_arguments

        validate_profile_arguments(_args(input="x.csv", sample_rows=1000))


class TestTheParserWiring:
    def test_profile_is_a_registered_subcommand(self):
        from ducta.console.parser import UnifiedArgumentParser

        args = UnifiedArgumentParser.create().parse_args(
            ["profile", "--input", "x.csv", "--format", "csv"]
        )

        assert args.subcommand == "profile"
        assert args.input == "x.csv"

    def test_the_dispatch_table_routes_profile(self):
        from ducta.console.cli import UnifiedCLI

        validator, handler = UnifiedCLI()._build_dispatch_table()["profile"]

        assert validator is not None and handler is not None
