"""
UploadedDataSource — DataSource implementation backed by in-memory parsed data.

Stores up to three buckets: events, accounts, notes.
Each bucket is populated by the upload endpoint based on detected type.
Multiple uploads to the same session append to the relevant bucket.

All DataSource methods run as Python aggregations over the in-memory lists.
Plan filtering on events is best-effort: works if the event row has a `plan`
field, or if uploaded accounts are present (joined by company_id).
"""
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services.datasource import DataSource


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: object) -> datetime:
    """Lenient ISO datetime parser."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fall back to a very old date so the row gets filtered out
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso_day(dt: datetime) -> str:
    return dt.date().isoformat()


def _iso_week(dt: datetime) -> str:
    # Start of ISO week (Monday)
    d = dt.date()
    return (d - timedelta(days=d.weekday())).isoformat()


class UploadedDataSource(DataSource):

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.accounts: list[dict] = []
        self.notes: list[dict] = []

        # company_id → plan (populated from uploaded accounts)
        self._plan_index: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Bucket loaders
    # ------------------------------------------------------------------

    def add_events(self, rows: list[dict]) -> None:
        for row in rows:
            # Normalise required fields
            row.setdefault("event_id", str(uuid.uuid4()))
            row.setdefault("distinct_id", "unknown")
            row.setdefault("company_id", "")
            row.setdefault("properties", {})
            self.events.append(row)

    def add_accounts(self, rows: list[dict]) -> None:
        for row in rows:
            row.setdefault("company_id", str(uuid.uuid4()))
            self.accounts.append(row)
            cid = str(row.get("company_id", ""))
            plan = str(row.get("plan", "")).lower()
            if cid and plan:
                self._plan_index[cid] = plan

    def add_notes(self, rows: list[dict]) -> None:
        for row in rows:
            row.setdefault("note_id", str(uuid.uuid4()))
            row.setdefault("author", "uploaded")
            row.setdefault("tags", [])
            self.notes.append(row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _plan_for_event(self, event: dict) -> Optional[str]:
        """Best-effort plan resolution."""
        if "plan" in event:
            return str(event["plan"]).lower()
        cid = str(event.get("company_id", ""))
        return self._plan_index.get(cid)

    def _filter_events(
        self,
        event_name: Optional[str],
        since: datetime,
        plan: Optional[str],
        company_id: Optional[str],
    ) -> list[dict]:
        out = []
        for e in self.events:
            if event_name and e.get("event_name") != event_name:
                continue
            if _parse_dt(e.get("timestamp", "")) < since:
                continue
            if company_id and str(e.get("company_id", "")) != company_id:
                continue
            if plan:
                ep = self._plan_for_event(e)
                if ep and ep != plan.lower():
                    continue
            out.append(e)
        return out

    # ------------------------------------------------------------------
    # DataSource interface
    # ------------------------------------------------------------------

    async def feature_trend(
        self,
        feature: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        since = _utc_now() - timedelta(days=days)
        by_day: dict[str, int] = defaultdict(int)
        for e in self._filter_events(feature, since, plan, None):
            by_day[_iso_day(_parse_dt(e["timestamp"]))] += 1
        return [{"day": d, "count": c} for d, c in sorted(by_day.items())]

    async def feature_distribution(
        self,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        since = _utc_now() - timedelta(days=days)
        by_feature: dict[str, int] = defaultdict(int)
        for e in self._filter_events(None, since, plan, None):
            fn = e.get("event_name", "unknown")
            by_feature[fn] += 1
        return sorted(
            [{"feature": f, "count": c} for f, c in by_feature.items()],
            key=lambda r: -r["count"],
        )

    async def compare_features(
        self,
        features: list[str],
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        since = _utc_now() - timedelta(days=days)
        by_key: dict[tuple[str, str], int] = defaultdict(int)
        for e in self._filter_events(None, since, plan, None):
            fn = e.get("event_name", "")
            if fn not in features:
                continue
            week = _iso_week(_parse_dt(e["timestamp"]))
            by_key[(week, fn)] += 1
        return sorted(
            [{"week": w, "feature": f, "count": c} for (w, f), c in by_key.items()]
        )

    async def account_list(
        self,
        plan: Optional[str] = None,
        industry: Optional[str] = None,
    ) -> list[dict]:
        out = []
        for a in self.accounts:
            if plan and str(a.get("plan", "")).lower() != plan.lower():
                continue
            if industry and str(a.get("industry", "")).lower() != industry.lower():
                continue
            out.append({
                "company_id": str(a.get("company_id", "")),
                "company_name": str(a.get("company_name", "")),
                "plan": str(a.get("plan", "")),
                "industry": str(a.get("industry", "")),
                "seats": int(a.get("seats", 0)),
                "mrr": float(a.get("mrr", 0.0)),
                "joined_date": str(a.get("joined_date", "")),
            })
        return sorted(out, key=lambda r: -r["mrr"])

    async def event_sample(
        self,
        event_name: str,
        days: int = 7,
        company_id: Optional[str] = None,
        plan: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        since = _utc_now() - timedelta(days=days)
        rows = self._filter_events(event_name, since, plan, company_id)
        rows.sort(key=lambda e: str(e.get("timestamp", "")), reverse=True)
        return [
            {
                "event_id": str(e.get("event_id", "")),
                "timestamp": str(e.get("timestamp", "")),
                "distinct_id": str(e.get("distinct_id", "")),
                "company_id": str(e.get("company_id", "")),
                "properties": e.get("properties", {}),
            }
            for e in rows[:limit]
        ]

    async def activation_trend(
        self,
        event_name: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        since = _utc_now() - timedelta(days=days)
        by_key: dict[tuple[str, str], int] = defaultdict(int)
        for e in self._filter_events(event_name, since, plan, None):
            day = _iso_day(_parse_dt(e["timestamp"]))
            tier = self._plan_for_event(e) or "unknown"
            by_key[(day, tier)] += 1
        return sorted(
            [{"day": d, "plan": p, "count": c} for (d, p), c in by_key.items()]
        )

    async def notes_list(
        self,
        tags: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[dict]:
        rows = [
            {
                "note_id": str(n.get("note_id", "")),
                "timestamp": str(n.get("timestamp", "")),
                "author": str(n.get("author", "")),
                "content": str(n.get("content", "")),
                "tags": list(n.get("tags", [])),
            }
            for n in self.notes
        ]
        if tags:
            tag_set = set(tags)
            rows = [r for r in rows if tag_set.intersection(r["tags"])]
        rows.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return rows[:limit]
