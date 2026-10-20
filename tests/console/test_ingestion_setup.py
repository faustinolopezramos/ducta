"""Regression: `ducta init ingestion setup` always called
`create_connection(spec, overwrite=True)` — silently replacing an existing
connection's credentials with no warning or confirmation at all.
"""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import MagicMock, patch

from ducta.console.commands.ingestion_setup import IngestionSetupCommands
from ducta.console.core import ExitCode


class TestIngestionSetupWarnsBeforeOverwrite:
    def test_declining_overwrite_aborts_before_creating_connection(self):
        mock_service = MagicMock()
        mock_service.get_connection.return_value = {"type": "postgresql", "host": "old-host"}

        # Step 1 (db type) -> "2" (postgresql), Step 2 (name) -> "existing_db",
        # then decline the overwrite prompt.
        inputs = iter(["2", "existing_db", "n"])

        with patch(
            "ducta.console.commands.ingestion_setup.IngestionService",
            return_value=mock_service,
        ):
            with patch("builtins.input", side_effect=lambda *_: next(inputs)):
                result = IngestionSetupCommands._setup(Namespace())

        assert result == ExitCode.SUCCESS.value
        mock_service.create_connection.assert_not_called()

    def test_accepting_overwrite_proceeds_with_setup(self):
        mock_service = MagicMock()
        mock_service.get_connection.return_value = {"type": "postgresql", "host": "old-host"}
        mock_service.test_spec.return_value = True

        inputs = iter(
            [
                "2",  # db type: postgresql
                "existing_db",  # name
                "y",  # confirm overwrite
                "localhost",  # host
                "",  # port (default)
                "mydb",  # database
                "myuser",  # username
            ]
        )

        with patch(
            "ducta.console.commands.ingestion_setup.IngestionService",
            return_value=mock_service,
        ):
            with patch("builtins.input", side_effect=lambda *_: next(inputs)):
                with patch("getpass.getpass", return_value="mypassword"):
                    result = IngestionSetupCommands._setup(Namespace())

        assert result == ExitCode.SUCCESS.value
        mock_service.create_connection.assert_called_once()

    def test_no_existing_connection_skips_the_prompt(self):
        mock_service = MagicMock()
        from ducta.gate.gateway import IngestionServiceError

        mock_service.get_connection.side_effect = IngestionServiceError("not found")
        mock_service.test_spec.return_value = True

        inputs = iter(
            [
                "2",  # db type
                "new_db",  # name
                "localhost",  # host
                "",  # port
                "mydb",  # database
                "myuser",  # username
            ]
        )

        with patch(
            "ducta.console.commands.ingestion_setup.IngestionService",
            return_value=mock_service,
        ):
            with patch("builtins.input", side_effect=lambda *_: next(inputs)):
                with patch("getpass.getpass", return_value="mypassword"):
                    result = IngestionSetupCommands._setup(Namespace())

        assert result == ExitCode.SUCCESS.value
        mock_service.create_connection.assert_called_once()


class TestIngestionSetupNextStepsMessage:
    """Regression: the "Next Steps" output told the user to manually edit
    .env with "the actual password" — but _write_credentials already wrote
    the real password captured via getpass. The instruction was misleading
    at best (it implies the password isn't there yet) and could lead a user
    to believe the file lacks the real secret when it doesn't."""

    def test_does_not_ask_the_user_to_manually_add_the_password(self, capsys):
        mock_service = MagicMock()
        from ducta.gate.gateway import IngestionServiceError

        mock_service.get_connection.side_effect = IngestionServiceError("not found")
        mock_service.test_spec.return_value = True
        mock_service.env_path = "/project/.env"

        inputs = iter(["2", "new_db", "localhost", "", "mydb", "myuser"])

        with patch(
            "ducta.console.commands.ingestion_setup.IngestionService",
            return_value=mock_service,
        ):
            with patch("builtins.input", side_effect=lambda *_: next(inputs)):
                with patch("getpass.getpass", return_value="mypassword"):
                    IngestionSetupCommands._setup(Namespace())

        out = capsys.readouterr().out
        assert "your_actual_password" not in out
        assert "nano .env" not in out
        assert "/project/.env" in out
        assert "already saved" in out


class TestConnectionTestIsHonest:
    """Regression: with no Spark session (always, from the CLI) the connector
    skipped the test and returned True, and `ducta init ingestion test` printed
    "✓ Connection successful!" with exit 0 for a host nobody had contacted. A
    real failure returned False and was reported as "inconclusive", also exit 0."""

    def _test(self, verified):
        service = MagicMock()
        service.test_connection.return_value = verified
        with patch("ducta.console.commands.ingestion_setup.IngestionService", return_value=service):
            return IngestionSetupCommands._test(Namespace(source="db"))

    def test_untested_is_not_a_pass(self):
        assert self._test(None) == ExitCode.DEPENDENCY_ERROR.value

    def test_failed_is_a_failure(self):
        assert self._test(False) == ExitCode.EXECUTION_ERROR.value

    def test_verified_passes(self):
        assert self._test(True) == ExitCode.SUCCESS.value

    def test_setup_asks_before_saving_a_connection_that_failed(self):
        from ducta.gate.gateway import IngestionServiceError

        service = MagicMock()
        service.get_connection.side_effect = IngestionServiceError("not found")
        service.test_spec.return_value = False
        inputs = iter(["2", "new_db", "localhost", "", "mydb", "myuser", "n"])

        with patch("ducta.console.commands.ingestion_setup.IngestionService", return_value=service):
            with patch("builtins.input", side_effect=lambda *_: next(inputs)):
                with patch("getpass.getpass", return_value="pw"):
                    result = IngestionSetupCommands._setup(Namespace())

        assert result == ExitCode.EXECUTION_ERROR.value
        service.create_connection.assert_not_called()

    def test_setup_saves_an_untested_connection_without_claiming_it_works(self, capsys):
        from ducta.gate.gateway import IngestionServiceError

        service = MagicMock()
        service.get_connection.side_effect = IngestionServiceError("not found")
        service.test_spec.return_value = None
        inputs = iter(["2", "new_db", "localhost", "", "mydb", "myuser"])

        with patch("ducta.console.commands.ingestion_setup.IngestionService", return_value=service):
            with patch("ducta.console.commands.ingestion_setup.logger") as log:
                with patch("builtins.input", side_effect=lambda *_: next(inputs)):
                    with patch("getpass.getpass", return_value="pw"):
                        result = IngestionSetupCommands._setup(Namespace())

        assert result == ExitCode.SUCCESS.value
        service.create_connection.assert_called_once()
        logged = " ".join(str(c.args[0]) for c in log.mock_calls if c.args)
        text = logged + capsys.readouterr().out
        assert "Not verified" in text
        assert "successful" not in text.lower()
        assert "nodes.yml" not in text  # format-1 layout, no longer read
        assert "kind: ingest" in text
