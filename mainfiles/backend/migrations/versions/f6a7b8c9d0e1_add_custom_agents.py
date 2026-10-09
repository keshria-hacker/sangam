"""add custom_agents table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-09

Agent Hub (Phase 3): user-defined agent configurations.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f6a7b8c9d0e1'
down_revision: str | Sequence[str] | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'custom_agents',
        sa.Column('id', sa.String(length=12), nullable=False),
        sa.Column('user_id', sa.String(length=12), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('model_id', sa.String(length=128), nullable=True),
        sa.Column('tool_names', sa.Text(), nullable=True),
        sa.Column('max_steps', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_custom_agents_user_id', 'custom_agents', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_custom_agents_user_id', table_name='custom_agents')
    op.drop_table('custom_agents')
