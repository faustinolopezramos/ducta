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

from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, List, Literal, Optional

from loguru import logger  # type: ignore
from pydantic import Field, field_validator, model_validator  # type: ignore
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore

#: The only environment names `is_production()` / `is_development()` understand.
_VALID_ENVIRONMENTS = frozenset({"development", "staging", "production"})


class Settings(BaseSettings):
    """API Settings read from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Ducta API", description="Human-readable application name")
    debug: bool = Field(default=False, description="Enable debug mode (verbose logging, reload)")
    environment: str = Field(
        default="development",
        description="Runtime environment: development | staging | production",
    )

    @field_validator("environment", mode="before")
    @classmethod
    def _normalise_environment(cls, value: Any) -> Any:
        """Fold case/whitespace, then reject anything outside the three known values."""
        if not isinstance(value, str):
            return value
        normalised = value.strip().lower()
        if normalised not in _VALID_ENVIRONMENTS:
            raise ValueError(
                f"Invalid environment {value!r}. Must be one of: "
                f"{', '.join(sorted(_VALID_ENVIRONMENTS))}. Note that an "
                "unrecognised value would otherwise disable every production "
                "safety check."
            )
        return normalised

    host: str = Field(
        default="127.0.0.1",
        description=(
            "Bind host for uvicorn. Defaults to loopback only; set HOST=0.0.0.0 "
            "explicitly to expose the API on all interfaces."
        ),
    )
    port: int = Field(default=8000, description="Bind port for uvicorn")
    workers: int = Field(default=1, description="Number of uvicorn worker processes (prod)")
    reload: bool = Field(default=False, description="Enable auto-reload (dev only)")

    cors_origins: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        description=(
            "Allowed CORS origins. Keep this an explicit allow-list: setting it to "
            "'*' forces credentials off, because wildcard-with-credentials lets any "
            "website read authenticated responses from your local server."
        ),
    )
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: List[str] = Field(default=["*"])
    cors_allow_headers: List[str] = Field(default=["*"])

    rate_limit_enabled: bool = Field(default=False, description="Enable rate limiting middleware")
    rate_limit_requests: int = Field(default=100, description="Max requests per minute per IP")
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        description="Rate limit sliding window in seconds",
    )
    rate_limit_max_keys: int = Field(
        default=10_000,
        ge=100,
        description="Maximum number of distinct in-memory rate limit keys",
    )
    rate_limit_cleanup_interval_seconds: int = Field(
        default=300,
        ge=5,
        description="Interval for periodic rate limit key cleanup",
    )
    rate_limit_redis_url: Optional[str] = Field(
        default=None,
        description=(
            "Redis URL (e.g. redis://localhost:6379/0) for a shared rate-limit "
            "counter across multiple worker processes. Requires the optional "
            "'redis' extra. When unset, each worker enforces its own in-memory "
            "limit, so the effective limit scales with WORKERS."
        ),
    )

    revocation_redis_url: Optional[str] = Field(
        default=None,
        description=(
            "Redis URL for the logout/refresh token-revocation list, shared across "
            "workers and surviving restarts. Falls back to RATE_LIMIT_REDIS_URL, then "
            "to a per-process in-memory list."
        ),
    )

    max_executions_in_memory: int = Field(
        default=500,
        ge=50,
        description="Maximum execution records to keep in memory",
    )
    max_concurrent_executions: int = Field(
        default=5,
        ge=1,
        description="Maximum concurrent pipeline executions",
    )
    max_sweep_size: int = Field(
        default=50,
        ge=1,
        description=(
            "Maximum number of parameter combinations a single sweep may expand "
            "to. Guards against a large grid search enqueuing hundreds of "
            "executions (and their log buffers) at once."
        ),
    )
    execution_log_buffer_size: int = Field(
        default=100_000,
        ge=1_000,
        description="Maximum log lines per execution buffer",
    )
    execution_timeout_seconds: int = Field(
        default=3600,
        ge=60,
        description="Default timeout for a pipeline execution",
    )
    execution_retention_seconds: int = Field(
        default=21_600,
        ge=300,
        description="Retention for completed execution metadata in memory",
    )
    execution_maintenance_interval_seconds: int = Field(
        default=300,
        ge=30,
        description="Interval for periodic in-memory execution maintenance",
    )
    execution_log_db_batch_size: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Log lines to accumulate before a single DB INSERT batch",
    )
    runs_dir: str = Field(
        default="~/.ducta/runs",
        description=(
            "Directory for the file-based run store (meta.json + logs.jsonl per run). "
            "This makes the optional SQLite store disposable: runs stay inspectable on "
            "disk regardless of DATABASE_URL. Set to empty to disable file persistence."
        ),
    )

    max_git_log: int = Field(
        default=500, description="Maximum commits to return in git log endpoints"
    )
    config_cache_ttl_seconds: int = Field(
        default=300, description="TTL for in-memory config cache (5 min)"
    )

    git_clone_allowed_hosts: List[str] = Field(
        default_factory=list,
        description=(
            "Allow-list of hostnames permitted as Git clone sources (e.g. "
            "['github.com', 'dev.azure.com']). Left empty, it defaults to the "
            "well-known public forges outside development, and to 'any host' in "
            "development — see `_default_git_clone_hosts`. Set it explicitly in "
            "any networked deployment that clones from somewhere else."
        ),
    )

    jwt_secret_key: str = Field(
        default="change-me-in-production",
        description="Secret key for JWT signing. MUST be overridden in production.",
    )

    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = Field(default="HS256")
    jwt_expiration_hours: int = Field(default=24)
    auth_enabled: bool = Field(
        default=False, description="Enable JWT authentication (basic login required)"
    )

    # ── Editor: language server ─────────────────────────────────────────────────
    lsp_command: str = Field(
        default="",
        description=(
            "Python language server for the code editor, run per open editor over stdio. "
            "Empty = the first found of basedpyright-langserver, pyright-langserver, pylsp. "
            "'off' disables it."
        ),
    )
    lsp_max_processes: int = Field(
        default=4, ge=1, description="Language-server processes running at once"
    )

    # ── SLA watch ───────────────────────────────────────────────────────────────
    sla_check_minutes: int = Field(
        default=0,
        ge=0,
        description="Check every project's metadata.sla this often and send its sla_miss "
        "alerts (one per late streak). 0 = off; POST .../alerts/check still works.",
    )
    sla_check_env: str = Field(default="prod", description="Environment the SLA watch checks")

    # ── Database persistence ────────────────────────────────────────────────────
    database_url: str = Field(
        default="",
        description=(
            "SQLAlchemy async database URL.  Empty = in-memory mode (default).\n"
            "  SQLite (local):   sqlite+aiosqlite:///./data/ducta.db\n"
            "  PostgreSQL:       postgresql+asyncpg://user:pass@host:5432/ducta"
        ),
    )

    log_level: str = Field(default="INFO", description="Log level: DEBUG | INFO | WARNING | ERROR")
    log_format: str = Field(
        default="json", description="Log format: json | text (text for local dev)"
    )

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        """Validate production settings."""
        if self.environment == "production":
            if self.jwt_secret_key == "change-me-in-production":
                raise ValueError(
                    "jwt_secret_key must be overridden in production. "
                    "Set the JWT_SECRET_KEY environment variable."
                )
            if not self.auth_enabled:
                raise ValueError(
                    "auth_enabled must be True in production. "
                    "Set the AUTH_ENABLED=true environment variable."
                )
            if self.debug:
                raise ValueError(
                    "debug must be False in production — it makes Starlette return "
                    "full tracebacks (source, file paths, local variables) on any "
                    "unhandled exception. Unset DEBUG or set it to false."
                )
        # Warn (but don't block) when SQLite is used with multiple workers
        if self.database_url.strip().startswith("sqlite") and self.workers > 1:
            import warnings

            warnings.warn(
                "SQLite does not support multiple concurrent writers. "
                "Set workers=1 or switch to PostgreSQL (DATABASE_URL=postgresql+asyncpg://...).",
                stacklevel=2,
            )

        if self.auth_enabled and not self.rate_limit_enabled:
            import warnings

            if "rate_limit_enabled" in self.model_fields_set:
                warnings.warn(
                    "auth_enabled=True with rate_limit_enabled explicitly set to False: "
                    "login and other authenticated endpoints have no protection against "
                    "brute-force/credential-stuffing attempts.",
                    stacklevel=2,
                )
            else:
                self.rate_limit_enabled = True
                warnings.warn(
                    "auth_enabled=True: automatically enabling rate_limit_enabled "
                    "(was left at its default) to protect login and other "
                    "authenticated endpoints from brute-force attempts. Set "
                    "RATE_LIMIT_ENABLED=false explicitly to opt out.",
                    stacklevel=2,
                )
        return self

    @model_validator(mode="after")
    def _expand_runs_dir(self) -> "Settings":
        """Expand `~` in runs_dir so consumers get a usable absolute path."""
        if self.runs_dir and self.runs_dir.strip():
            self.runs_dir = str(Path(self.runs_dir.strip()).expanduser())
        return self

    #: Forges assumed safe when no allow-list is configured outside development.
    DEFAULT_GIT_CLONE_HOSTS: ClassVar[List[str]] = [
        "github.com",
        "www.github.com",
        "gitlab.com",
        "dev.azure.com",
        "ssh.dev.azure.com",
        "bitbucket.org",
    ]

    @model_validator(mode="after")
    def _default_git_clone_hosts(self) -> "Settings":
        """Close the clone allow-list by default outside development."""
        if self.git_clone_allowed_hosts or self.is_development():
            return self

        self.git_clone_allowed_hosts = list(self.DEFAULT_GIT_CLONE_HOSTS)
        logger.info(
            "GIT_CLONE_ALLOWED_HOSTS is unset in environment={env}; defaulting to "
            "{hosts}. Set it explicitly to clone from anywhere else.",
            env=self.environment,
            hosts=", ".join(self.DEFAULT_GIT_CLONE_HOSTS),
        )
        return self

    def is_production(self) -> bool:
        return self.environment == "production"

    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
