"""remove confidence from operations

Revision ID: eda12c183552
Revises: caf8a3b37206
Create Date: 2025-11-07 18:22:46.333975

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eda12c183552'
down_revision: Union[str, Sequence[str], None] = 'caf8a3b37206'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Remove confidence column and constraint from operations table."""
    # SQLite doesn't support DROP COLUMN directly, so we use batch mode
    # which recreates the table without the confidence column
    with op.batch_alter_table('operations', schema=None) as batch_op:
        # Drop the check constraint first
        batch_op.drop_constraint('ck_confidence_range', type_='check')
        # Then drop the confidence column
        batch_op.drop_column('confidence')


def downgrade() -> None:
    """Downgrade schema - Add confidence column back to operations table."""
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('operations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confidence', sa.FLOAT(), nullable=False, server_default='0.0'))
