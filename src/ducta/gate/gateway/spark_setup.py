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
"""

from pathlib import Path
from typing import List, Optional

from loguru import logger  # type: ignore

DEFAULT_SOURCES_PATH = "config/sources.yaml"


def _default_lib_dir() -> Path:
    return Path.cwd() / "lib" / "jdbc"


def collect_jdbc_jars(
    sources_path: Optional[Path] = None,
    lib_dir: Optional[Path] = None,
    download: bool = True,
) -> List[str]:
    """Ensure JDBC drivers for the configured sources are present; return JAR paths."""
    lib_dir = Path(lib_dir) if lib_dir else _default_lib_dir()
    sources_path = Path(sources_path) if sources_path else Path(DEFAULT_SOURCES_PATH)

    if download and sources_path.exists():
        try:
            _download_drivers_for_sources(sources_path, lib_dir)
        except Exception as e:  # pragma: no cover - best-effort
            logger.debug("Could not pre-download JDBC drivers: {}", e)

    if not lib_dir.exists():
        return []
    return sorted(str(p) for p in lib_dir.glob("*.jar"))


def _download_drivers_for_sources(sources_path: Path, lib_dir: Path) -> None:
    """Download the driver JAR for each unique source type in ``sources.yaml``."""
    import yaml

    from .connector import JDBCConnector

    config = yaml.safe_load(sources_path.read_text()) or {}
    sources = config.get("sources", {}) or {}

    for source_name, cfg in sources.items():
        if not isinstance(cfg, dict):
            continue
        source_type = cfg.get("type")
        if not source_type:
            continue
        if source_type not in JDBCConnector.DRIVERS:
            logger.warning("Unknown JDBC source type '{}' in sources.yaml", source_type)
            continue
        try:
            driver = cfg.get("driver") if isinstance(cfg.get("driver"), dict) else None
            connector = JDBCConnector(
                source_type=source_type,
                host="localhost",
                port=JDBCConnector.DRIVERS[source_type]["default_port"],
                database="dummy",
                username="dummy",
                password="dummy",
                driver=driver,
            )
            connector.download_driver(lib_dir)
        except Exception as e:
            logger.warning("Failed to prepare JDBC driver for '{}': {}", source_name, e)
