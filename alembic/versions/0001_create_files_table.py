"""Crea la tabla de metadatos de archivos.

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("storage_key", name="uq_files_storage_key"),
    )
    op.create_index("ix_files_original_name", "files", ["original_name"])
    op.create_index("ix_files_content_type", "files", ["content_type"])
    op.create_index("ix_files_uploaded_at", "files", ["uploaded_at"])


def downgrade() -> None:
    op.drop_index("ix_files_uploaded_at", table_name="files")
    op.drop_index("ix_files_content_type", table_name="files")
    op.drop_index("ix_files_original_name", table_name="files")
    op.drop_table("files")
