"""convert pending_operations to operations with status tracking

Revision ID: caf8a3b37206
Revises: 678450063de1
Create Date: 2025-11-03 13:51:21.437936

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'caf8a3b37206'
down_revision: str | Sequence[str] | None = '678450063de1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Step 1: Create new operations table with status tracking
    # Note: document_copy_id is nullable to preserve operations when copies are deleted
    op.create_table('operations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_copy_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'accepted', 'rejected', name='operationstatus'), nullable=False),
    sa.Column('suggested_directory_path', sa.String(length=255), nullable=False),
    sa.Column('suggested_filename', sa.String(length=255), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('prompt_hash', sa.String(length=64), nullable=False),
    sa.Column('document_content_hash', sa.String(length=64), nullable=True),
    sa.Column('model_name', sa.String(length=255), nullable=True),
    sa.Column('createdAt', sa.DateTime(), nullable=False),
    sa.CheckConstraint('confidence >= 0.0 AND confidence <= 1.0', name='ck_confidence_range'),
    sa.ForeignKeyConstraint(['document_copy_id'], ['document_copies.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_operations_document_copy_id'), 'operations', ['document_copy_id'], unique=False)
    op.create_index(op.f('ix_operations_prompt_hash'), 'operations', ['prompt_hash'], unique=False)
    op.create_index(op.f('ix_operations_status'), 'operations', ['status'], unique=False)

    # Create partial unique index: only one PENDING operation per document_copy_id
    # SQLite supports partial indexes with WHERE clause
    op.execute("""
        CREATE UNIQUE INDEX ix_operations_one_pending_per_copy
        ON operations (document_copy_id)
        WHERE status = 'pending' AND document_copy_id IS NOT NULL
    """)

    # Create composite index for few-shot prompting queries
    # This enables fast lookup of operations by status and prompt_hash
    op.create_index(
        'ix_operations_status_prompt_hash',
        'operations',
        ['status', 'prompt_hash'],
        unique=False
    )

    # Step 2: Migrate existing pending_operations data to operations table
    # All existing records get status='pending' (lowercase to match Python enum)
    op.execute("""
        INSERT INTO operations (
            document_copy_id, status, suggested_directory_path, suggested_filename,
            reason, confidence, prompt_hash, document_content_hash, model_name, createdAt
        )
        SELECT
            document_copy_id, 'pending', suggested_directory_path, suggested_filename,
            reason, confidence, prompt_hash, document_content_hash, model_name, createdAt
        FROM pending_operations
    """)

    # Step 3: Drop old pending_operations table
    op.drop_index(op.f('ix_pending_operations_document_copy_id'), table_name='pending_operations')
    op.drop_table('pending_operations')

    # Step 4: Add accepted_operation_id to document_copies
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('document_copies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('accepted_operation_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_document_copies_accepted_operation_id'), ['accepted_operation_id'], unique=False)
        batch_op.create_foreign_key('fk_document_copies_accepted_operation', 'operations', ['accepted_operation_id'], ['id'], ondelete='SET NULL')

    # Step 5: Create partial unique index for one PENDING operation per document_copy_id
    # SQLite doesn't support partial indexes in the same way as PostgreSQL, so we use a unique index
    # The application logic will enforce that only one PENDING operation exists per document_copy_id

    # Step 6: Fix documents table index (unrelated change detected by autogenerate)
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uix_content_hash'), type_='unique')
        batch_op.drop_index(batch_op.f('ix_documents_content_hash'))
        batch_op.create_index(batch_op.f('ix_documents_content_hash'), ['content_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema.

    NOTE: This downgrade will only preserve PENDING operations.
    ACCEPTED and REJECTED operations will be lost during downgrade.
    """
    # Step 1: Revert documents table index changes
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_content_hash'))
        batch_op.create_index(batch_op.f('ix_documents_content_hash'), ['content_hash'], unique=False)
        batch_op.create_unique_constraint(batch_op.f('uix_content_hash'), ['content_hash'])

    # Step 2: Remove accepted_operation_id from document_copies
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('document_copies', schema=None) as batch_op:
        batch_op.drop_constraint('fk_document_copies_accepted_operation', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_document_copies_accepted_operation_id'))
        batch_op.drop_column('accepted_operation_id')

    # Step 3: Recreate pending_operations table
    op.create_table('pending_operations',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('document_copy_id', sa.INTEGER(), nullable=False),
    sa.Column('suggested_directory_path', sa.VARCHAR(length=255), nullable=False),
    sa.Column('suggested_filename', sa.VARCHAR(length=255), nullable=False),
    sa.Column('reason', sa.TEXT(), nullable=False),
    sa.Column('confidence', sa.FLOAT(), nullable=False),
    sa.Column('createdAt', sa.DATETIME(), nullable=False),
    sa.Column('prompt_hash', sa.VARCHAR(length=64), server_default=sa.text("'placeholder_hash'"), nullable=False),
    sa.Column('document_content_hash', sa.VARCHAR(length=64), nullable=True),
    sa.Column('model_name', sa.VARCHAR(length=255), nullable=True),
    sa.CheckConstraint('confidence >= 0.0 AND confidence <= 1.0', name=op.f('ck_confidence_range')),
    sa.ForeignKeyConstraint(['document_copy_id'], ['document_copies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_copy_id', name=op.f('uix_pending_op_copy'))
    )
    op.create_index(op.f('ix_pending_operations_document_copy_id'), 'pending_operations', ['document_copy_id'], unique=False)

    # Step 4: Migrate PENDING operations back to pending_operations table
    # WARNING: ACCEPTED and REJECTED operations will be lost!
    op.execute("""
        INSERT INTO pending_operations (
            document_copy_id, suggested_directory_path, suggested_filename,
            reason, confidence, prompt_hash, document_content_hash, model_name, createdAt
        )
        SELECT
            document_copy_id, suggested_directory_path, suggested_filename,
            reason, confidence, prompt_hash, document_content_hash, model_name, createdAt
        FROM operations
        WHERE status = 'pending'
    """)

    # Step 5: Drop operations table and its indexes
    op.drop_index('ix_operations_status_prompt_hash', table_name='operations')
    op.execute("DROP INDEX IF EXISTS ix_operations_one_pending_per_copy")
    op.drop_index(op.f('ix_operations_status'), table_name='operations')
    op.drop_index(op.f('ix_operations_prompt_hash'), table_name='operations')
    op.drop_index(op.f('ix_operations_document_copy_id'), table_name='operations')
    op.drop_table('operations')
