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

import os
import re
import stat
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.core.errors import DuctaError as EngineError
from ducta.core.errors import ExecutionError as EngineExecutionError
from ducta.setting.environments import (
    DEFAULT_ENVIRONMENTS,  # noqa: F401
    ENV_ALIASES,  # noqa: F401
    FALLBACK_CHAINS,  # noqa: F401
    CanonicalEnvironment,  # noqa: F401
    allowed_environments,  # noqa: F401
    get_base_environment,  # noqa: F401
    get_fallback_chain,  # noqa: F401
    get_sandbox_developer,  # noqa: F401
    is_allowed_environment,  # noqa: F401
    is_sandbox_environment,  # noqa: F401
    is_valid_environment,  # noqa: F401
    normalize_environment,  # noqa: F401
)

try:
    from ducta.console.ux.rich_logger import RichLoggerManager

    _USE_RICH = True
except ImportError:
    _USE_RICH = False
    logger.debug("Rich not available, using basic logging")


class ConfigFormat(Enum):
    """Supported configuration file formats."""

    YAML = "yaml"
    JSON = "json"
    TOML = "toml"  # Supported by AppConfigManager, ConfigDiscovery, and template generation
    DSL = "dsl"  # Domain-specific language format


class LogLevel(Enum):
    """Available logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ExitCode(Enum):
    """Standard application exit codes."""

    SUCCESS = 0
    GENERAL_ERROR = 1
    CONFIGURATION_ERROR = 2
    VALIDATION_ERROR = 3
    EXECUTION_ERROR = 4
    DEPENDENCY_ERROR = 5
    SECURITY_ERROR = 6


class DuctaError(EngineError):
    """Base exception for errors raised by the console itself."""

    def __init__(self, message: str, exit_code: ExitCode = ExitCode.GENERAL_ERROR):
        super().__init__(message)
        self.exit_code = exit_code.value if isinstance(exit_code, ExitCode) else int(exit_code)


class ConfigurationError(DuctaError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str):
        super().__init__(message, ExitCode.CONFIGURATION_ERROR)


class ValidationError(DuctaError):
    """Raised when input validation fails."""

    def __init__(self, message: str):
        super().__init__(message, ExitCode.VALIDATION_ERROR)


ExecutionError = EngineExecutionError


class SecurityError(DuctaError):
    """Raised when security validation fails."""

    def __init__(self, message: str):
        super().__init__(message, ExitCode.SECURITY_ERROR)


@dataclass
class CLIConfig:
    """Configuration object for CLI arguments."""

    env: str
    pipeline: str
    node: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    base_path: Optional[Path] = None
    layer_name: Optional[str] = None
    use_case_name: Optional[str] = None
    config_type: Optional[str] = None
    interactive: bool = False
    list_configs: bool = False
    list_pipelines: bool = False
    pipeline_info: Optional[str] = None
    clear_cache: bool = False
    log_level: str = "INFO"
    log_file: Optional[Path] = None
    validate_only: bool = False
    dry_run: bool = False
    sanity_only: bool = False
    verbose: bool = False
    quiet: bool = False
    template: Optional[str] = None
    project_name: Optional[str] = None
    output_path: Optional[Path] = None
    format: str = "yaml"
    no_sample_code: bool = False
    list_templates: bool = False
    model_version: Optional[str] = None
    hyperparams: Optional[str] = None
    sweep: Optional[str] = None
    search: bool = False
    search_metric: Optional[str] = None
    search_trials: Optional[int] = None
    sweep_reuse_upstream: bool = True
    sweep_parallel: int = 1
    max_sweep_size: int = 50
    execution_mode: str = "async"
    reuse_upstream: bool = False
    rerun_all: bool = False


VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SecurityValidator:
    SENSITIVE_DIRS: Tuple[Path, ...]

    if os.name == "posix":
        SENSITIVE_DIRS = (
            Path("/etc"),
            Path("/proc"),
            Path("/sys"),
            Path("/var/run"),
            Path("/root"),
            Path.home() / ".ssh",
        )
    elif os.name == "nt":
        SENSITIVE_DIRS = (
            Path("C:/Windows"),
            Path("C:/Program Files"),
            Path("C:/Program Files (x86)"),
            Path("C:/Users/Administrator"),
        )
    else:
        SENSITIVE_DIRS = ()

    @staticmethod
    def _is_permissive() -> bool:
        val = os.getenv("Ducta_PERMISSIVE_PATH_VALIDATION") or os.getenv(
            "DUCTA_PERMISSIVE_PATH_VALIDATION", "0"
        )
        return val in ("1", "true", "True", "yes", "YES")

    @staticmethod
    def validate_path(base_path: Path, target_path: Path) -> Path:
        """Ensure target path is within base path boundaries and safe."""
        permissive = SecurityValidator._is_permissive()
        try:
            resolved_base = base_path.resolve()
            resolved_target = target_path.resolve()

            SecurityValidator._check_relative_to_base(resolved_base, resolved_target)
            SecurityValidator._check_sensitive_dirs(resolved_target)
            SecurityValidator._check_hidden_parts(resolved_base, resolved_target)
            SecurityValidator._check_file_permissions(resolved_target, permissive=permissive)

            return resolved_target
        except Exception as e:
            if isinstance(e, SecurityError):
                raise
            raise SecurityError(f"Path validation failed: {e}") from e

    @staticmethod
    def _check_relative_to_base(resolved_base: Path, resolved_target: Path) -> None:
        """Check if target is within base path."""
        try:
            resolved_target.relative_to(resolved_base)
        except ValueError:
            raise SecurityError(f"Path traversal attempt blocked: {resolved_target}")

    @staticmethod
    def _check_sensitive_dirs(resolved_target: Path) -> None:
        for sensitive_dir in SecurityValidator.SENSITIVE_DIRS:
            try:
                resolved_target.relative_to(sensitive_dir)
                raise SecurityError(f"Access to sensitive directory '{sensitive_dir}' denied")
            except ValueError:
                pass

    @staticmethod
    def _check_hidden_parts(resolved_base: Path, resolved_target: Path) -> None:
        """Reject paths whose *target-relative-to-base* components are hidden."""
        relative_parts = resolved_target.relative_to(resolved_base).parts
        for part in relative_parts:
            if part.startswith(".") and part not in (".", ".."):
                raise SecurityError(f"Access to hidden path denied: {resolved_target}")

    @staticmethod
    def _check_file_permissions(resolved_target: Path, permissive: bool = False) -> None:
        """Check file permissions and ownership.

        In permissive mode ownership and some permission checks are skipped.
        """
        if not resolved_target.exists():
            return
        try:
            stat_info = os.stat(resolved_target)
            if os.name == "posix":
                SecurityValidator._check_posix_permissions(resolved_target, stat_info, permissive)
        except OSError:
            pass

    @staticmethod
    def _check_posix_permissions(
        resolved_target: Path, stat_info: os.stat_result, permissive: bool = False
    ) -> None:
        """Check POSIX-specific file permissions and ownership."""
        if hasattr(stat, "S_IWOTH") and (stat_info.st_mode & stat.S_IWOTH):
            raise SecurityError(f"World-writable file detected: {resolved_target}")
        if not permissive and hasattr(os, "getuid") and stat_info.st_uid != os.getuid():
            raise SecurityError(f"File not owned by current user: {resolved_target}")


class ConfigCache:
    _EXPIRATION_SECONDS = 300
    _cache: Dict[str, Dict[str, Any]] = {}
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def get(cls, key: str) -> Optional[List[Tuple[Path, str]]]:
        with cls._lock:
            entry = cls._cache.get(key)
            if entry is None:
                return None
            if time.time() - entry["timestamp"] >= cls._EXPIRATION_SECONDS:
                del cls._cache[key]
                return None
            return entry["configs"]

    @classmethod
    def set(cls, key: str, configs: List[Tuple[Path, str]]) -> None:
        with cls._lock:
            cls._cache[key] = {"configs": configs, "timestamp": time.time()}

    @classmethod
    def invalidate(cls, key: str) -> None:
        with cls._lock:
            cls._cache.pop(key, None)

    @classmethod
    def invalidate_all(cls, pattern: Optional[str] = None) -> None:
        import re

        with cls._lock:
            if pattern is None:
                cls._cache.clear()
            else:
                for key in [k for k in cls._cache if re.search(pattern, k)]:
                    del cls._cache[key]

    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        with cls._lock:
            now = time.time()
            entries = list(cls._cache.keys())
            ages = [now - cls._cache[k]["timestamp"] for k in entries]
            return {
                "total_entries": len(entries),
                "entries": entries,
                "oldest_age_seconds": max(ages) if ages else 0,
                "newest_age_seconds": min(ages) if ages else 0,
                "expiration_seconds": cls._EXPIRATION_SECONDS,
            }


class LoggerManager:
    @staticmethod
    def setup(
        level: str = "INFO",
        log_file: Optional[str] = None,
        verbose: bool = False,
        quiet: bool = False,
    ) -> None:
        if _USE_RICH:
            RichLoggerManager.setup(
                level=level,
                log_file=log_file,
                verbose=verbose,
                quiet=quiet,
                show_time=True,
                show_path=verbose,
                enable_rich_tracebacks=True,
            )
        else:
            logger.remove()
            console_level = "ERROR" if quiet else ("DEBUG" if verbose else level.upper())
            logger.add(
                sys.stderr,
                format="{time:HH:mm:ss} | {level: <8} | {message}",
                colorize=True,
                level=console_level,
            )
            log_path = Path(log_file) if log_file else Path("logs/log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logger.add(
                log_path,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
                rotation="10 MB",
                retention="7 days",
                level="DEBUG",
            )


class PathManager:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir
        self.added_paths: List[str] = []
        self.original_cwd = Path.cwd()

    def setup_import_paths(self) -> None:
        if not self.config_dir:
            return
        try:
            validated_dir = SecurityValidator.validate_path(self.original_cwd, self.config_dir)
            for path in [
                validated_dir,
                validated_dir / "src",
                validated_dir / "lib",
                validated_dir.parent,
                validated_dir.parent / "src",
            ]:
                if path.exists() and path.is_dir():
                    self._add_to_path(str(path))
        except SecurityError as e:
            logger.error("Security violation in path setup: {}", e)

    def _add_to_path(self, path_str: str) -> None:
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            self.added_paths.append(path_str)

    def cleanup(self) -> None:
        for path in self.added_paths:
            while path in sys.path:
                sys.path.remove(path)
        self.added_paths.clear()

    def __enter__(self) -> "PathManager":
        self.setup_import_paths()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()


def parse_iso_date(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as e:
        raise ValidationError(f"Invalid date format '{date_str}'. Use YYYY-MM-DD") from e


def validate_date_range(start_date: Optional[str], end_date: Optional[str]) -> None:
    if start_date and end_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise ValidationError("Dates must be in YYYY-MM-DD format")
        if sd > ed:
            raise ValidationError(f"Start date {start_date} must be <= end date {end_date}")
