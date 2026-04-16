"""
Tool layer between OpenAI function-calling and the DataSource interface.

TOOL_SCHEMAS — OpenAI-compatible tool definitions (passed verbatim to the API).
ToolExecutor  — dispatches tool_call results to the right DataSource method.
"""
import json
from typing import Any

from app.services.datasource import DataSource

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_FEATURE_NAMES = (
    "'dashboard', 'funnel_analysis', 'retention_chart', "
    "'user_segments', 'event_explorer', 'ai_assistant', 'data_export'"
)

_PLAN_PARAM = {
    "type": "string",
    "enum": ["starter", "growth", "enterprise"],
    "description": "Filter results to one account plan tier.",
}

_DAYS_PARAM = {
    "type": "integer",
    "description": "Number of past days to include (default 30).",
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "feature_trend",
            "description": (
                "Returns daily event counts for a single feature over the last N days. "
                "Use this to spot growth, decline, or sudden changes in feature adoption."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "feature": {
                        "type": "string",
                        "description": f"Feature to query. Known values: {_FEATURE_NAMES}.",
                    },
                    "days": _DAYS_PARAM,
                    "plan": _PLAN_PARAM,
                },
                "required": ["feature"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "feature_distribution",
            "description": (
                "Returns aggregate event counts for every feature over the last N days, "
                "sorted descending. Use to compare feature popularity or find the most/least used."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": _DAYS_PARAM,
                    "plan": _PLAN_PARAM,
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_features",
            "description": (
                "Returns weekly event counts for two or more features side-by-side. "
                "Use to detect cannibalisation, substitution, or correlated trends."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "features": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"List of feature names to compare. Known values: {_FEATURE_NAMES}.",
                    },
                    "days": _DAYS_PARAM,
                    "plan": _PLAN_PARAM,
                },
                "required": ["features"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "account_list",
            "description": (
                "Returns accounts with their plan, industry, MRR, and seat count. "
                "Use to identify which companies are active, large, or in a specific vertical."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": _PLAN_PARAM,
                    "industry": {
                        "type": "string",
                        "description": "Filter by industry, e.g. 'fintech', 'healthtech', 'saas', 'ecommerce', 'logistics'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "event_sample",
            "description": (
                "Returns raw event rows for a given feature, newest first. "
                "Use to inspect what actions users are taking or to find anomalies in event properties."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": f"Feature/event to sample. Known values: {_FEATURE_NAMES}.",
                    },
                    "days": _DAYS_PARAM,
                    "plan": _PLAN_PARAM,
                    "company_id": {
                        "type": "string",
                        "description": "UUID of a specific account to narrow results.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default 50, max 200).",
                    },
                },
                "required": ["event_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "activation_trend",
            "description": (
                "Returns daily event counts for one feature broken down by account plan tier. "
                "Use to detect activation drops or plan-specific adoption patterns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": f"Feature/event to analyse. Known values: {_FEATURE_NAMES}.",
                    },
                    "days": _DAYS_PARAM,
                    "plan": _PLAN_PARAM,
                },
                "required": ["event_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notes_list",
            "description": (
                "Returns internal analyst notes, optionally filtered by tag. "
                "Use to find context, hypotheses, or previously logged observations "
                "about a feature, release, or metric change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Filter to notes that contain at least one of these tags. "
                            "Known tags include: funnel_analysis, ai_assistant, activation, "
                            "onboarding, retention_chart, user_segments, enterprise, starter, "
                            "release, performance, cohorts, product, v2.3.0."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max notes to return (default 20).",
                    },
                },
                "required": [],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, str] = {
    "feature_trend": "feature_trend",
    "feature_distribution": "feature_distribution",
    "compare_features": "compare_features",
    "account_list": "account_list",
    "event_sample": "event_sample",
    "activation_trend": "activation_trend",
    "notes_list": "notes_list",
}


class ToolExecutor:
    def __init__(self, datasource: DataSource) -> None:
        self._ds = datasource

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        method_name = _DISPATCH.get(name)
        if method_name is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            method = getattr(self._ds, method_name)
            result: Any = await method(**args)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps(result, default=str)
