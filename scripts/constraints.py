#!/usr/bin/env python3
"""Split ``poetry export`` output into one pip constraints file per Python version.

pip ignores ``poetry.lock``; a release ships these files so that
``pip install "ducta[all]==X.Y.Z" -c constraints-py3.13.txt`` installs exactly
what was tested. ``poetry export`` alone is not usable for that: when the lock
holds two versions of one package (numpy 1.26.4 for every Python, numpy 2.5.4
for 3.13+), it writes both, their markers overlap, and pip refuses the file on
3.13. Here each file keeps the lines that apply to its Python and, where two
versions of a package both apply, the newest one — the one Poetry installs there.
Platform markers (``sys_platform``…) are kept for pip to evaluate.

Usage:
    poetry export --extras all --without-hashes -o exported.txt
    python scripts/constraints.py exported.txt 3.11 3.12 3.13 3.14   # writes constraints-py3.X.txt
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.version import Version

#: The platforms a marker is tried on: a line is kept when it applies to any of them.
_PLATFORMS = [
    {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"},
    {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix"},
    {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt"},
]


def _applies(marker: Marker | None, python: str) -> bool:
    if marker is None:
        return True
    env = {"python_version": python, "python_full_version": f"{python}.0"}
    return any(marker.evaluate({**platform, **env}) for platform in _PLATFORMS)


def constraints_for(lines: List[str], python: str) -> List[str]:
    """The constraint lines of *lines* that apply to *python*, one version per package."""
    chosen: Dict[str, Tuple[Version, str]] = {}
    for line in lines:
        text = line.strip()
        if not text or text.startswith(("#", "-")):
            continue
        requirement = Requirement(text)
        if not _applies(requirement.marker, python):
            continue
        [pin] = list(requirement.specifier)  # poetry export writes name==version
        version = Version(pin.version)
        name = requirement.name.lower()
        if name not in chosen or version > chosen[name][0]:
            chosen[name] = (version, text)
    return [chosen[name][1] for name in sorted(chosen)]


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    lines = Path(argv[1]).read_text(encoding="utf-8").splitlines()
    for python in argv[2:]:
        out = Path(f"constraints-py{python}.txt")
        out.write_text("\n".join(constraints_for(lines, python)) + "\n", encoding="utf-8")
        print(f"{out}: {len(out.read_text().splitlines())} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
