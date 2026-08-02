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

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from loguru import logger  # type: ignore

try:
    from watchdog.events import FileSystemEventHandler  # type: ignore

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning(
        "watchdog not installed - file watching disabled. Install via: pip install watchdog  (or: pip install ducta[api])"
    )

    class FileSystemEventHandler:
        pass


class ConfigFileWatcher(FileSystemEventHandler):
    """Monitors config directory for YAML/JSON/TOML changes."""

    MONITORED_EXTENSIONS = {".yaml", ".yml", ".json", ".toml", ".py"}
    IGNORE_PATTERNS = {".pyc", ".pyo", "__pycache__", ".git", ".DS_Store"}

    def __init__(
        self,
        workspace_root: Path,
        on_config_change: Callable[[Path], None],
        debounce_seconds: float = 0.2,
    ):
        self.workspace_root = Path(workspace_root)
        self.on_config_change = on_config_change
        self.debounce_seconds = debounce_seconds
        self._debounce_timers: dict[str, threading.Timer] = {}
        self._timer_lock = threading.RLock()

    def _should_monitor(self, path: Path) -> bool:
        if path.suffix.lower() not in self.MONITORED_EXTENSIONS:
            return False
        path_str = str(path).lower()
        return not any(pattern in path_str for pattern in self.IGNORE_PATTERNS)

    def _debounce_change(self, path: Path) -> None:
        path_str = str(path)
        with self._timer_lock:
            if path_str in self._debounce_timers:
                self._debounce_timers[path_str].cancel()
            timer = threading.Timer(
                self.debounce_seconds,
                self._fire_callback,
                args=(path,),
            )
            timer.daemon = True
            self._debounce_timers[path_str] = timer
            timer.start()

    def _fire_callback(self, path: Path) -> None:
        try:
            path_str = str(path)
            with self._timer_lock:
                self._debounce_timers.pop(path_str, None)
            logger.debug("Config change detected: {path}", path=path)
            self.on_config_change(path)
        except Exception as e:
            logger.error("Error in config change callback: {e}", e=e, exc_info=True)

    def _handle_event(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._should_monitor(path):
            return
        self._debounce_change(path)

    def on_modified(self, event):
        self._handle_event(event)

    def on_created(self, event):
        self._handle_event(event)

    def on_deleted(self, event):
        self._handle_event(event)

    def cleanup(self) -> None:
        with self._timer_lock:
            for timer in self._debounce_timers.values():
                timer.cancel()
            self._debounce_timers.clear()
