"""separate documents and copies schema

Revision ID: 4e81d9d2857f
Revises: 6e165e275682
Create Date: 2025-10-30 15:17:09.268542

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4e81d9d2857f'
down_revision: str | Sequence[str] | None = '6e165e275682'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to separate documents and copies."""
    # Drop old documents table (pre-production, no data migration needed)
    op.drop_table('documents')

    # Create new documents table with content_hash
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('createdAt', sa.DateTime(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('content_hash', name='uix_content_hash')
    )
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])

    # Create document_copies table
    op.create_table(
        'document_copies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('repository_path', sa.String(), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('createdAt', sa.DateTime(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.UniqueConstraint('repository_path', 'file_path', name='uix_repo_file')
    )
    op.create_index('ix_document_copies_document_id', 'document_copies', ['document_id'])


def downgrade() -> None:
    """Downgrade schema to original single documents table."""
    # Drop new tables
    op.drop_index('ix_document_copies_document_id', 'document_copies')
    op.drop_table('document_copies')

    op.drop_index('ix_documents_content_hash', 'documents')
    op.drop_table('documents')

    # Recreate old documents table
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('createdAt', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
