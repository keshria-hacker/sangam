"""add user settings json

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-09

Adds a generic JSON settings column to user_preferences for the
typed settings schema (Phase 2 studio shell).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: str | Sequence[str] | None = 'd4e5f6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('user_preferences', sa.Column('settings_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_preferences', 'settings_json')
