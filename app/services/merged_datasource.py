"""
MergedDataSource(base, overlay) — DataSource that reads from two sources
and combines their results.

For aggregated methods (feature_trend, feature_distribution, etc.) counts
are summed by the grouping key so uploaded and seeded data add together.

For list methods (account_list, event_sample, notes_list) results are
concatenated, de-duplicated by id, and re-sorted.
"""
from typing import Optional

from app.services.datasource import DataSource


class MergedDataSource(DataSource):

    def __init__(self, base: DataSource, overlay: DataSource) -> None:
        self._base = base
        self._overlay = overlay

    async def product_context(self) -> list[dict]:
        base = await self._base.product_context()
        over = await self._overlay.product_context()
        seen: set[str] = set()
        out: list[dict] = []
        for r in base + over:
            wid = r.get("workspace_id", "")
            if wid in seen:
                continue
            seen.add(wid)
            out.append(r)
        return out

    # ------------------------------------------------------------------
    # Aggregated methods — merge by grouping key, sum counts
    # ------------------------------------------------------------------

    async def feature_trend(
        self,
        feature: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        base = await self._base.feature_trend(feature=feature, days=days, plan=plan)
        over = await self._overlay.feature_trend(feature=feature, days=days, plan=plan)
        merged: dict[str, int] = {}
        for r in base + over:
            merged[r["day"]] = merged.get(r["day"], 0) + r["count"]
        return [{"day": d, "count": c} for d, c in sorted(merged.items())]

    async def feature_distribution(
        self,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        base = await self._base.feature_distribution(days=days, plan=plan)
        over = await self._overlay.feature_distribution(days=days, plan=plan)
        merged: dict[str, int] = {}
        for r in base + over:
            merged[r["feature"]] = merged.get(r["feature"], 0) + r["count"]
        return sorted(
            [{"feature": f, "count": c} for f, c in merged.items()],
            key=lambda r: -r["count"],
        )

    async def compare_features(
        self,
        features: list[str],
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        base = await self._base.compare_features(features=features, days=days, plan=plan)
        over = await self._overlay.compare_features(features=features, days=days, plan=plan)
        merged: dict[tuple[str, str], int] = {}
        for r in base + over:
            key = (r["week"], r["feature"])
            merged[key] = merged.get(key, 0) + r["count"]
        return sorted(
            [{"week": w, "feature": f, "count": c} for (w, f), c in merged.items()]
        )

    async def activation_trend(
        self,
        event_name: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        base = await self._base.activation_trend(event_name=event_name, days=days, plan=plan)
        over = await self._overlay.activation_trend(event_name=event_name, days=days, plan=plan)
        merged: dict[tuple[str, str], int] = {}
        for r in base + over:
            key = (r["day"], r["plan"])
            merged[key] = merged.get(key, 0) + r["count"]
        return sorted(
            [{"day": d, "plan": p, "count": c} for (d, p), c in merged.items()]
        )

    # ------------------------------------------------------------------
    # List methods — concatenate, de-duplicate by id, re-sort
    # ------------------------------------------------------------------

    async def account_list(
        self,
        plan: Optional[str] = None,
        industry: Optional[str] = None,
    ) -> list[dict]:
        base = await self._base.account_list(plan=plan, industry=industry)
        over = await self._overlay.account_list(plan=plan, industry=industry)
        seen: set[str] = set()
        out: list[dict] = []
        for r in base + over:
            cid = r.get("company_id", "")
            if cid not in seen:
                seen.add(cid)
                out.append(r)
        return sorted(out, key=lambda r: (-r.get("mrr", 0)))

    async def event_sample(
        self,
        event_name: str,
        days: int = 7,
        company_id: Optional[str] = None,
        plan: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        base = await self._base.event_sample(
            event_name=event_name, days=days, company_id=company_id, plan=plan, limit=limit
        )
        over = await self._overlay.event_sample(
            event_name=event_name, days=days, company_id=company_id, plan=plan, limit=limit
        )
        seen: set[str] = set()
        out: list[dict] = []
        for r in base + over:
            eid = r.get("event_id", "")
            if eid not in seen:
                seen.add(eid)
                out.append(r)
        out.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return out[:limit]

    async def notes_list(
        self,
        tags: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[dict]:
        base = await self._base.notes_list(tags=tags, limit=limit)
        over = await self._overlay.notes_list(tags=tags, limit=limit)
        seen: set[str] = set()
        out: list[dict] = []
        for r in base + over:
            nid = r.get("note_id", "")
            if nid not in seen:
                seen.add(nid)
                out.append(r)
        out.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return out[:limit]
