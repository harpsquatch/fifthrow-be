"""add_customer_product_name

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("customer_product_name", sa.String(), nullable=False, server_default="unknown"),
    )
    op.alter_column("accounts", "customer_product_name", server_default=None)


def downgrade() -> None:
    op.drop_column("accounts", "customer_product_name")
