"""add pending operations table

Revision ID: f37f338691aa
Revises: 4e81d9d2857f
Create Date: 2025-10-30 17:21:30.386965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f37f338691aa'
down_revision: Union[str, Sequence[str], None] = '4e81d9d2857f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add pending_operations table."""
    # Create pending_operations table
    op.create_table(
        'pending_operations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_copy_id', sa.Integer(), nullable=False),
        sa.Column('suggested_directory_path', sa.String(length=255), nullable=False),
        sa.Column('suggested_filename', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('createdAt', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['document_copy_id'], ['document_copies.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('document_copy_id', name='uix_pending_op_copy'),
        sa.CheckConstraint('confidence >= 0.0 AND confidence <= 1.0', name='ck_confidence_range')
    )
    op.create_index('ix_pending_operations_document_copy_id', 'pending_operations', ['document_copy_id'])


def downgrade() -> None:
    """Downgrade schema to remove pending_operations table."""
    op.drop_index('ix_pending_operations_document_copy_id', 'pending_operations')
    op.drop_table('pending_operations')
