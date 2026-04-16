"""
DataSource abstract interface.

Tools talk to DataSource. DataSource talks to storage.
The implementation is swappable (Postgres, mock, upload, etc.).

All methods are async and return plain dicts — no ORM objects.
"""
from abc import ABC, abstractmethod
from typing import Optional


class DataSource(ABC):
    @abstractmethod
    async def product_context(self) -> list[dict]:
        """
        Returns product/workspace identity metadata.

        Returns:
            [{"workspace_id":"...","product_name":"...","product_description":"...",
              "company_name":"...","timezone":"...","default_currency":"..."}]
        """

    @abstractmethod
    async def feature_trend(
        self,
        feature: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        """
        Daily event count for a single feature over the last `days` days.
        Optional plan filter ('starter' | 'growth' | 'enterprise').

        Returns:
            [{"day": "2026-04-01", "count": 142}, ...]
        """

    @abstractmethod
    async def feature_distribution(
        self,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        """
        Aggregate count per feature over the last `days` days.
        Optional plan filter.

        Returns:
            [{"feature": "dashboard", "count": 5710}, ...]  sorted desc
        """

    @abstractmethod
    async def compare_features(
        self,
        features: list[str],
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        """
        Weekly counts for each of the given features side-by-side.
        Useful for "is X cannibalising Y?" questions.

        Returns:
            [{"week": "2026-03-17", "feature": "funnel_analysis", "count": 471}, ...]
        """

    @abstractmethod
    async def account_list(
        self,
        plan: Optional[str] = None,
        industry: Optional[str] = None,
    ) -> list[dict]:
        """
        Return accounts, optionally filtered by plan and/or industry.

        Returns:
            [{"company_id": "...", "company_name": "Acme Corp",
              "customer_product_name": "AcmeFlow", "plan": "enterprise",
              "industry": "fintech", "seats": 120, "mrr": 12500.0,
              "joined_date": "2024-02-23"}, ...]
        """

    @abstractmethod
    async def event_sample(
        self,
        event_name: str,
        days: int = 7,
        company_id: Optional[str] = None,
        plan: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Raw event rows for a given event_name, newest first.
        Optional filters: company_id and/or plan.

        Returns:
            [{"event_id": "...", "timestamp": "...", "distinct_id": "...",
              "company_id": "...", "properties": {...}}, ...]
        """

    @abstractmethod
    async def activation_trend(
        self,
        event_name: str,
        days: int = 30,
        plan: Optional[str] = None,
    ) -> list[dict]:
        """
        Daily count for one event broken down by plan tier.
        If `plan` is given, returns only that tier.

        Returns:
            [{"day": "2026-04-01", "plan": "starter", "count": 3}, ...]
        """

    @abstractmethod
    async def notes_list(
        self,
        tags: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        Analyst notes, optionally filtered by tag overlap.
        Ordered by timestamp desc.

        Returns:
            [{"note_id": "...", "timestamp": "...", "author": "...",
              "content": "...", "tags": [...]}, ...]
        """
