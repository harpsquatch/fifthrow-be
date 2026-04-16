import asyncio
import random
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from app.db.base import AsyncSessionLocal
from app.db.models import Account, Event, Note, Plan


FEATURES: list[str] = [
    "dashboard",
    "funnel_analysis",
    "retention_chart",
    "user_segments",
    "event_explorer",
    "ai_assistant",
    "data_export",
]


@dataclass(frozen=True)
class AccountSeed:
    company_name: str
    plan: Plan
    industry: str
    seats: int
    mrr: float
    joined_date: date


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _trend_multiplier(feature: str, day_idx: int, days: int) -> float:
    """
    day_idx: 0..days-1
    """
    t = day_idx / max(1, days - 1)

    if feature == "funnel_analysis":
        # Down ~40% over 30 days.
        return _lerp(1.0, 0.6, t)
    if feature == "ai_assistant":
        # Up ~200% over 30 days (i.e., ~3x).
        return _lerp(1.0, 3.0, t)
    if feature == "dashboard":
        # Stable, slight decline.
        return _lerp(1.0, 0.9, t)
    if feature == "user_segments":
        # Slight growth.
        return _lerp(1.0, 1.2, t)
    # Flat features.
    return 1.0


def _activation_drop_multiplier(feature: str, plan: Plan, days_ago: int) -> float:
    # 14 days ago, event_explorer usage among starter accounts drops sharply.
    if feature == "event_explorer" and plan == Plan.starter and days_ago <= 14:
        return 0.25
    return 1.0


def _base_daily_events(plan: Plan, feature: str) -> int:
    # Keep numbers small but readable in the DB.
    if plan == Plan.enterprise:
        base = 20
    elif plan == Plan.growth:
        base = 10
    else:
        base = 5

    if feature == "dashboard":
        return base * 2
    if feature == "ai_assistant":
        return max(1, base // 2)
    if feature == "data_export":
        return max(1, base // 3)
    return base


def _random_action(rng: random.Random, feature: str) -> str:
    if feature == "data_export":
        return rng.choice(["export_csv", "export_parquet", "export_xlsx"])
    if feature == "ai_assistant":
        return rng.choice(["open", "ask", "copy_answer", "retry"])
    if feature == "funnel_analysis":
        return rng.choice(["open", "set_steps", "apply_filter", "run"])
    if feature == "event_explorer":
        return rng.choice(["open", "search", "filter", "inspect_event"])
    return rng.choice(["open", "click", "view"])


def _screen_for_feature(feature: str) -> str:
    return {
        "dashboard": "Home/Dashboard",
        "funnel_analysis": "Analyze/Funnels",
        "retention_chart": "Analyze/Retention",
        "user_segments": "Analyze/Segments",
        "event_explorer": "Explore/Events",
        "ai_assistant": "AI/Assistant",
        "data_export": "Export/Data",
    }[feature]


def _distinct_id(rng: random.Random, company_id: uuid.UUID) -> str:
    # Stable-ish per company, but plenty of variety.
    return f"user_{company_id.hex[:6]}_{rng.randint(1, 200):03d}"


async def seed() -> None:
    rng = random.Random(42)

    today = _utc_now().date()
    days = 30
    start_day = today - timedelta(days=days - 1)

    account_seeds: list[AccountSeed] = [
        # Enterprise (fintech/healthtech), ~$5-15k MRR
        AccountSeed("Acme Corp", Plan.enterprise, "fintech", seats=120, mrr=12500.0, joined_date=today - timedelta(days=420)),
        AccountSeed("Glacier Tech", Plan.enterprise, "fintech", seats=80, mrr=8200.0, joined_date=today - timedelta(days=260)),
        AccountSeed("Bluebird Inc", Plan.enterprise, "healthtech", seats=150, mrr=15200.0, joined_date=today - timedelta(days=610)),
        # Growth (saas/ecommerce/healthtech), ~$1-3k MRR
        AccountSeed("Cascade AI", Plan.growth, "saas", seats=35, mrr=2400.0, joined_date=today - timedelta(days=180)),
        AccountSeed("Drift Labs", Plan.growth, "ecommerce", seats=28, mrr=1650.0, joined_date=today - timedelta(days=140)),
        AccountSeed("Harbor Cloud", Plan.growth, "healthtech", seats=40, mrr=2950.0, joined_date=today - timedelta(days=210)),
        # Starter (logistics/saas), ~$200-500 MRR
        AccountSeed("Echo Systems", Plan.starter, "logistics", seats=5, mrr=350.0, joined_date=today - timedelta(days=60)),
        AccountSeed("Falcon Analytics", Plan.starter, "saas", seats=8, mrr=450.0, joined_date=today - timedelta(days=75)),
    ]

    notes_seed: list[tuple[str, list[str]]] = [
        ("Funnel drop linked to v2.3.0 UI redesign", ["funnel_analysis", "release", "v2.3.0"]),
        ("Activation drop linked to new onboarding step friction", ["activation", "onboarding", "starter"]),
        ("AI assistant adoption strong among enterprise, low discoverability on starter", ["ai_assistant", "enterprise", "starter"]),
        ("Retention chart perf improvement shipped", ["retention_chart", "performance", "release"]),
        ("Cohort analysis potentially cannibalised by segments", ["user_segments", "cohorts", "product"]),
    ]

    async with AsyncSessionLocal() as session:
        # Idempotent-ish: wipe data we own (keep alembic_version).
        await session.execute(delete(Event))
        await session.execute(delete(Account))
        await session.execute(delete(Note))
        await session.commit()

        accounts: list[Account] = []
        for s in account_seeds:
            accounts.append(
                Account(
                    company_name=s.company_name,
                    plan=s.plan,
                    industry=s.industry,
                    seats=s.seats,
                    mrr=s.mrr,
                    joined_date=s.joined_date,
                )
            )

        session.add_all(accounts)
        await session.flush()  # populate company_id PKs

        # Notes (global, not per-account in schema).
        notes: list[Note] = []
        base_note_time = _utc_now() - timedelta(days=20)
        for i, (content, tags) in enumerate(notes_seed):
            notes.append(
                Note(
                    timestamp=base_note_time + timedelta(days=i * 3),
                    author=rng.choice(["pm@fifthrow", "analyst@fifthrow", "eng@fifthrow"]),
                    content=content,
                    tags=tags,
                )
            )
        session.add_all(notes)

        events: list[Event] = []

        for day_offset in range(days):
            day = start_day + timedelta(days=day_offset)
            day_start = _day_start_utc(day)
            days_ago = (today - day).days

            for acct in accounts:
                for feature in FEATURES:
                    base = _base_daily_events(acct.plan, feature)
                    mult = _trend_multiplier(feature, day_offset, days)
                    mult *= _activation_drop_multiplier(feature, acct.plan, days_ago)

                    # Add per-company variance.
                    company_jitter = rng.uniform(0.85, 1.15)
                    expected = base * mult * company_jitter

                    # Convert to an integer count with some noise.
                    count = max(0, int(round(expected + rng.uniform(-1.5, 1.5))))
                    if count == 0:
                        continue

                    for _ in range(count):
                        ts = day_start + timedelta(
                            seconds=rng.randint(8 * 3600, 20 * 3600),
                            milliseconds=rng.randint(0, 999),
                        )
                        events.append(
                            Event(
                                event_name=feature,
                                timestamp=ts,
                                distinct_id=_distinct_id(rng, acct.company_id),
                                company_id=acct.company_id,
                                properties={
                                    "feature": feature,
                                    "action": _random_action(rng, feature),
                                    "duration_ms": rng.randint(250, 15000),
                                    "screen": _screen_for_feature(feature),
                                },
                            )
                        )

        # Insert in chunks to keep memory/statement sizes sane.
        chunk_size = 2000
        for i in range(0, len(events), chunk_size):
            session.add_all(events[i : i + chunk_size])
            await session.flush()

        await session.commit()

        # Print a quick sanity summary.
        print(f"Seeded {len(accounts)} accounts, {len(events)} events, {len(notes)} notes.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
