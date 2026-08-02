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

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, Text, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ducta.api.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionRow(Base):
    """Persistent record of a single pipeline execution."""

    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    pipeline_name: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    env: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_secs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sweep_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    sweep_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    logs: Mapped[List["ExecutionLogRow"]] = relationship(
        "ExecutionLogRow",
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    __table_args__ = (Index("ix_executions_pipeline_env", "pipeline_name", "env"),)


# ---------------------------------------------------------------------------
# Execution logs
# ---------------------------------------------------------------------------


class ExecutionLogRow(Base):
    """One log line emitted during a pipeline execution."""

    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(
        Text, ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(nullable=False, index=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON stored as text for SQLite/PostgreSQL compatibility
    _extra_json: Mapped[Optional[str]] = mapped_column("extra", Text, nullable=True)

    execution: Mapped["ExecutionRow"] = relationship("ExecutionRow", back_populates="logs")

    @property
    def extra(self) -> Dict[str, Any]:
        if self._extra_json:
            try:
                return json.loads(self._extra_json)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    @extra.setter
    def extra(self, value: Dict[str, Any]) -> None:
        self._extra_json = json.dumps(value) if value else None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserRow(Base):
    """Application user account stored in the database."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Roles stored as JSON text array for SQLite+PostgreSQL compatibility
    _roles_json: Mapped[str] = mapped_column("roles", Text, nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    @property
    def roles(self) -> List[str]:
        try:
            return json.loads(self._roles_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @roles.setter
    def roles(self, value: List[str]) -> None:
        self._roles_json = json.dumps(value)


@event.listens_for(UserRow, "before_insert")
def _set_user_created_at(_mapper, _connection, target: UserRow) -> None:  # noqa: ARG001
    if target.created_at is None:
        target.created_at = _utcnow()
    if target.updated_at is None:
        target.updated_at = _utcnow()
