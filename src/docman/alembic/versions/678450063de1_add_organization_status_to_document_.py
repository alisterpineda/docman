"""add organization status to document copies

Revision ID: 678450063de1
Revises: ad30f6583811
Create Date: 2025-11-02 22:15:28.704661

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '678450063de1'
down_revision: Union[str, Sequence[str], None] = 'ad30f6583811'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add organization_status column to document_copies
    op.add_column('document_copies', sa.Column('organization_status', sa.Enum('UNORGANIZED', 'ORGANIZED', 'IGNORED', name='organizationstatus'), nullable=False, server_default='UNORGANIZED'))
    op.create_index(op.f('ix_document_copies_organization_status'), 'document_copies', ['organization_status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove organization_status column from document_copies
    op.drop_index(op.f('ix_document_copies_organization_status'), table_name='document_copies')
    op.drop_column('document_copies', 'organization_status')
