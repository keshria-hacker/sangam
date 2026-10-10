"""add artifacts tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'artifacts',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('type', sa.String(16), nullable=False, server_default='doc'),
        sa.Column('language', sa.String(32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'artifact_versions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('artifact_id', sa.String(32), sa.ForeignKey('artifacts.id', ondelete='CASCADE'), index=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('artifact_versions')
    op.drop_table('artifacts')
