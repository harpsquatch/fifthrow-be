"""
PostgresDataSource — concrete DataSource backed by the async SQLAlchemy session.

All queries return plain dicts. No ORM objects escape this file.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import cast, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Account, Event, Note, Plan
from app.services.datasource import DataSource


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _since(days: int) -> datetime:
    return _utc_now() - timedelta(days=days)


def _plan_enum(plan: Optional[str]) -> Optional[Plan]:
    if plan is None:
        return None
    try:
        return Plan(plan.lower())
    except ValueError:
        raise ValueError(f"Unknown plan '{plan}'. Valid values: starter, growth, enterprise.")


class PostgresDataSource(DataSource):
    """
    Takes an AsyncSession at construction time.
    Designed to be created per-request (or per-tool-call) by the tool layer.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ------------------------------------------------------------------
    # feature_trend
    # ------------------------------------------------------------------

    async def feature_trend(
        self,
        feature: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        plan_enum = _plan_enum(plan)
        since = _since(days)

        day_col = func.date_trunc("day", Event.timestamp).label("day")
        q = (
            select(day_col, func.count().label("count"))
            .where(Event.event_name == feature, Event.timestamp >= since)
        )

        if plan_enum is not None:
            q = q.join(Account, Account.company_id == Event.company_id).where(
                Account.plan == plan_enum
            )

        q = q.group_by(day_col).order_by(day_col)
        rows = (await self._s.execute(q)).all()

        return [
            {"day": row.day.date().isoformat(), "count": row.count}
            for row in rows
        ]

    # ------------------------------------------------------------------
    # feature_distribution
    # ------------------------------------------------------------------

    async def feature_distribution(
        self,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        plan_enum = _plan_enum(plan)
        since = _since(days)

        q = (
            select(Event.event_name.label("feature"), func.count().label("count"))
            .where(Event.timestamp >= since)
        )

        if plan_enum is not None:
            q = q.join(Account, Account.company_id == Event.company_id).where(
                Account.plan == plan_enum
            )

        q = q.group_by(Event.event_name).order_by(text("count DESC"))
        rows = (await self._s.execute(q)).all()

        return [{"feature": row.feature, "count": row.count} for row in rows]

    # ------------------------------------------------------------------
    # compare_features
    # ------------------------------------------------------------------

    async def compare_features(
        self,
        features: list[str],
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        if not features:
            return []

        plan_enum = _plan_enum(plan)
        since = _since(days)

        week_col = func.date_trunc("week", Event.timestamp).label("week")
        q = (
            select(week_col, Event.event_name.label("feature"), func.count().label("count"))
            .where(Event.event_name.in_(features), Event.timestamp >= since)
        )

        if plan_enum is not None:
            q = q.join(Account, Account.company_id == Event.company_id).where(
                Account.plan == plan_enum
            )

        q = q.group_by(week_col, Event.event_name).order_by(week_col, Event.event_name)
        rows = (await self._s.execute(q)).all()

        return [
            {
                "week": row.week.date().isoformat(),
                "feature": row.feature,
                "count": row.count,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # account_list
    # ------------------------------------------------------------------

    async def account_list(
        self,
        plan: Optional[str] = None,
        industry: Optional[str] = None,
    ) -> list[dict]:
        plan_enum = _plan_enum(plan)

        q = select(Account).order_by(Account.plan, Account.mrr.desc())

        if plan_enum is not None:
            q = q.where(Account.plan == plan_enum)
        if industry is not None:
            q = q.where(Account.industry == industry.lower())

        rows = (await self._s.execute(q)).scalars().all()

        return [
            {
                "company_id": str(a.company_id),
                "company_name": a.company_name,
                "plan": a.plan.value,
                "industry": a.industry,
                "seats": a.seats,
                "mrr": a.mrr,
                "joined_date": a.joined_date.isoformat(),
            }
            for a in rows
        ]

    # ------------------------------------------------------------------
    # event_sample
    # ------------------------------------------------------------------

    async def event_sample(
        self,
        event_name: str,
        days: int = 7,
        company_id: Optional[str] = None,
        plan: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        plan_enum = _plan_enum(plan)
        since = _since(days)

        q = (
            select(Event)
            .where(Event.event_name == event_name, Event.timestamp >= since)
            .order_by(Event.timestamp.desc())
            .limit(limit)
        )

        if company_id is not None:
            q = q.where(Event.company_id == company_id)

        if plan_enum is not None:
            q = q.join(Account, Account.company_id == Event.company_id).where(
                Account.plan == plan_enum
            )

        rows = (await self._s.execute(q)).scalars().all()

        return [
            {
                "event_id": str(e.event_id),
                "timestamp": e.timestamp.isoformat(),
                "distinct_id": e.distinct_id,
                "company_id": str(e.company_id),
                "properties": e.properties,
            }
            for e in rows
        ]

    # ------------------------------------------------------------------
    # activation_trend
    # ------------------------------------------------------------------

    async def activation_trend(
        self,
        event_name: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        plan_enum = _plan_enum(plan)
        since = _since(days)

        day_col = func.date_trunc("day", Event.timestamp).label("day")
        q = (
            select(day_col, Account.plan.label("plan"), func.count().label("count"))
            .join(Account, Account.company_id == Event.company_id)
            .where(Event.event_name == event_name, Event.timestamp >= since)
        )

        if plan_enum is not None:
            q = q.where(Account.plan == plan_enum)

        q = q.group_by(day_col, Account.plan).order_by(day_col, Account.plan)
        rows = (await self._s.execute(q)).all()

        return [
            {
                "day": row.day.date().isoformat(),
                "plan": row.plan.value,
                "count": row.count,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # notes_list
    # ------------------------------------------------------------------

    async def notes_list(
        self,
        tags: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[dict]:
        q = select(Note).order_by(Note.timestamp.desc()).limit(limit)

        if tags:
            # Match notes whose tags JSONB array overlaps with the requested tags.
            # cast tags list to JSONB and use the ?| (has any key) operator via @> overlap.
            # Simplest cross-version approach: filter in Python after fetching (small table).
            pass  # applied below after fetch

        rows = (await self._s.execute(q)).scalars().all()

        results = [
            {
                "note_id": str(n.note_id),
                "timestamp": n.timestamp.isoformat(),
                "author": n.author,
                "content": n.content,
                "tags": n.tags,
            }
            for n in rows
        ]

        if tags:
            tag_set = set(tags)
            results = [r for r in results if tag_set.intersection(r["tags"])]

        return results
