"""add agent runs table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('model', sa.String(128), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='done'),
        sa.Column('tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('steps_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('agent_runs')
