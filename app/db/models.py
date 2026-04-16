import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Plan(str, enum.Enum):
    starter = "starter"
    growth = "growth"
    enterprise = "enterprise"


class ProductContext(Base):
    __tablename__ = "product_context"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    product_description: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    default_currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")


class Account(Base):
    __tablename__ = "accounts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    customer_product_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    plan: Mapped[Plan] = mapped_column(Enum(Plan), nullable=False)
    industry: Mapped[str] = mapped_column(String, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mrr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    joined_date: Mapped[date] = mapped_column(Date, nullable=False)

    events: Mapped[list["Event"]] = relationship("Event", back_populates="account")


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    distinct_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.company_id"), nullable=False, index=True
    )
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    account: Mapped["Account"] = relationship("Account", back_populates="events")


class Note(Base):
    __tablename__ = "notes"

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
