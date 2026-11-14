"""SIGTERM (``docker stop``, systemd, Kubernetes) is handled like Ctrl+C.

Left to its default action it ended the process on the spot: no run certificate,
no orderly stop of the streams, semaphores left behind.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ducta.console import cli

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="SIGTERM is a POSIX signal; Windows terminates the process"
)

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")


def _wait_for(path: Path, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path.name} never appeared")
        time.sleep(0.05)


class TestHandlerLifecycle:
    def test_installed_for_the_run_and_restored_after(self):
        before = signal.getsignal(signal.SIGTERM)
        saved = cli._install_sigterm_handler()
        try:
            assert saved is not None
            assert signal.getsignal(signal.SIGTERM) is not before
        finally:
            cli._restore_sigterm_handler(saved)
        assert signal.getsignal(signal.SIGTERM) == before

    def test_not_installed_outside_the_main_thread(self):
        seen = {}

        def work():
            seen["saved"] = cli._install_sigterm_handler()

        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        assert seen["saved"] is None

    def test_termination_is_an_interrupt(self):
        # What lets every `except KeyboardInterrupt` that stops a stream in order
        # (and the facade's certificate for an interrupted run) apply to SIGTERM too.
        assert issubclass(cli.TerminationRequested, KeyboardInterrupt)


class TestRunEndedBySigterm:
    SCRIPT = textwrap.dedent(
        """
        import sys, time, argparse
        sys.path.insert(0, {src!r})
        from ducta.console import cli

        def parse(self, args):
            return argparse.Namespace(verbose=False)

        def dispatch(self, parsed):
            open({ready!r}, "w").close()
            try:
                time.sleep(60)
            except cli.TerminationRequested:
                open({stopped!r}, "w").close()
                raise

        cli.UnifiedCLI._parse_and_setup_logging = parse
        cli.UnifiedCLI._dispatch_subcommand = dispatch
        sys.exit(cli.UnifiedCLI().run([]))
        """
    )

    def test_exits_143_after_unwinding(self, tmp_path):
        ready, stopped = tmp_path / "ready", tmp_path / "stopped"
        script = self.SCRIPT.format(src=_REPO_SRC, ready=str(ready), stopped=str(stopped))
        proc = subprocess.Popen([sys.executable, "-c", script], stderr=subprocess.PIPE, text=True)
        try:
            _wait_for(ready)
            proc.send_signal(signal.SIGTERM)
            _, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
        assert proc.returncode == cli.EXIT_SIGTERM == 143
        assert stopped.exists(), "the run was not unwound: SIGTERM did not raise in it"
