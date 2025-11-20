"""add prompt_hash to pending_operations

Revision ID: f5e26cb194bb
Revises: f37f338691aa
Create Date: 2025-10-31 17:58:42.450956

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f5e26cb194bb'
down_revision: str | Sequence[str] | None = 'f37f338691aa'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to add prompt_hash column."""
    # Check if the column already exists (for test environments)
    from alembic import op as alembic_op
    from sqlalchemy import inspect

    conn = alembic_op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('pending_operations')]

    if 'prompt_hash' not in columns:
        # Add prompt_hash column with a default value for existing rows
        # Using a placeholder hash for any existing pending operations
        # Note: We keep the server_default since SQLite doesn't support ALTER COLUMN
        op.add_column(
            'pending_operations',
            sa.Column('prompt_hash', sa.String(length=64), nullable=False, server_default='placeholder_hash')
        )


def downgrade() -> None:
    """Downgrade schema to remove prompt_hash column."""
    op.drop_column('pending_operations', 'prompt_hash')
