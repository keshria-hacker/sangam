"""add arena_results table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd4e5f6a7b8c9'
down_revision: str | Sequence[str] | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'arena_results',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('prompt', sa.String(500), nullable=False),
        sa.Column('winner_model', sa.String(200), nullable=False),
        sa.Column('loser_model', sa.String(200), nullable=False),
        sa.Column('models_compared', sa.String(500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('arena_results')
