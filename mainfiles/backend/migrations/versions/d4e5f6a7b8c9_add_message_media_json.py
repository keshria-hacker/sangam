"""add_message_media_json

Revision ID: d4e5f6a7b8c9
Revises: 4977846c45a6
Create Date: 2026-10-08 21:00:00.000000

Adds messages.media_json — JSON list of MediaAttachment dicts (image/audio),
the persistence foundation for voice + image-generation integrations.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: str | Sequence[str] | None = '4977846c45a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('media_json', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'media_json')
