"""Add original_file_path and original_repository_path to operations for context preservation

Revision ID: ff7089ab2955
Revises: eda12c183552
Create Date: 2025-11-08 15:18:04.277821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff7089ab2955'
down_revision: Union[str, Sequence[str], None] = 'eda12c183552'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add denormalized path fields for historical preservation.

    These fields preserve context when document_copy_id becomes NULL (orphaned operations).
    This enables few-shot prompting and proper display of historical operations.
    """
    # Add new columns as nullable first, then populate them, then make them NOT NULL
    # This is necessary because SQLite doesn't support adding NOT NULL columns directly
    with op.batch_alter_table('operations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('original_file_path', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('original_repository_path', sa.String(length=500), nullable=True))

    # Populate the new fields from existing document_copies
    # For operations that still have a valid document_copy_id, copy the paths
    op.execute("""
        UPDATE operations
        SET
            original_file_path = (
                SELECT file_path FROM document_copies
                WHERE document_copies.id = operations.document_copy_id
            ),
            original_repository_path = (
                SELECT repository_path FROM document_copies
                WHERE document_copies.id = operations.document_copy_id
            )
        WHERE document_copy_id IS NOT NULL
    """)

    # Set empty strings for orphaned operations (where document_copy_id is already NULL)
    op.execute("""
        UPDATE operations
        SET
            original_file_path = '',
            original_repository_path = ''
        WHERE document_copy_id IS NULL
    """)

    # Now make the columns NOT NULL using batch alter (SQLite requirement)
    with op.batch_alter_table('operations', schema=None) as batch_op:
        batch_op.alter_column('original_file_path', nullable=False)
        batch_op.alter_column('original_repository_path', nullable=False)


def downgrade() -> None:
    """Downgrade schema by removing denormalized path fields."""
    with op.batch_alter_table('operations', schema=None) as batch_op:
        batch_op.drop_column('original_repository_path')
        batch_op.drop_column('original_file_path')
