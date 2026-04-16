"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column(
            "plan",
            sa.Enum("starter", "growth", "enterprise", name="plan"),
            nullable=False,
        ),
        sa.Column("industry", sa.String(), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("mrr", sa.Float(), nullable=False),
        sa.Column("joined_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("company_id"),
    )

    op.create_table(
        "events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("distinct_id", sa.String(), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["accounts.company_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_events_event_name", "events", ["event_name"])
    op.create_index("ix_events_timestamp", "events", ["timestamp"])
    op.create_index("ix_events_distinct_id", "events", ["distinct_id"])
    op.create_index("ix_events_company_id", "events", ["company_id"])

    op.create_table(
        "notes",
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("note_id"),
    )


def downgrade() -> None:
    op.drop_table("notes")
    op.drop_index("ix_events_company_id", table_name="events")
    op.drop_index("ix_events_distinct_id", table_name="events")
    op.drop_index("ix_events_timestamp", table_name="events")
    op.drop_index("ix_events_event_name", table_name="events")
    op.drop_table("events")
    op.drop_table("accounts")
    op.execute("DROP TYPE IF EXISTS plan")
