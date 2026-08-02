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
