def test_version_is_exposed():
    from ducta import __version__

    assert isinstance(__version__, str)
    assert __version__


def test_python_dash_m_ducta_is_the_ducta_command():
    import subprocess
    import sys
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[1] / "src")
    done = subprocess.run(
        [sys.executable, "-m", "ducta", "--version"],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": src},
        timeout=60,
    )
    assert done.returncode == 0 and done.stdout.startswith("ducta ")
