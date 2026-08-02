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

Align users.email with the ORM model (UserRow.email is a required str):
backfill any NULL emails with a deterministic placeholder, then enforce
NOT NULL at the schema level.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-30 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers used by Alembic
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_USERS = sa.table(
    "users",
    sa.column("id", sa.Text()),
    sa.column("username", sa.Text()),
    sa.column("email", sa.Text()),
)


def upgrade() -> None:
    conn = op.get_bind()
    # Deterministic placeholder so re-running against the same DB is idempotent
    # and doesn't collide with the unique constraint on email.
    conn.execute(
        _USERS.update()
        .where(_USERS.c.email.is_(None))
        # `+` compiles to the dialect's string-concat operator (||, CONCAT, ...).
        .values(email=_USERS.c.username + "@unknown.local")
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email", existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email", existing_type=sa.Text(), nullable=True)
