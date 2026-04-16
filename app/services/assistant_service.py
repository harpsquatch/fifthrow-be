"""
AssistantService — agentic loop over OpenAI function calling.

Flow per request:
  1. Append user message to conversation history.
  2. Call OpenAI with full history + all tool schemas.
  3. If the model returns tool_calls → execute each via ToolExecutor,
     append results as tool-role messages, go to 2.
  4. When the model returns a plain text message → return it to the caller.

Conversation memory is in-process, keyed by conversation_id.
"""
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from app.services.datasource import DataSource
from app.services.tool_executor import TOOL_SCHEMAS, ToolExecutor

# ---------------------------------------------------------------------------
# In-memory conversation store
# ---------------------------------------------------------------------------

_conversation_memory: dict[str, list[dict]] = {}
_conversation_followups_seen: dict[str, set[str]] = {}
_MAX_HISTORY = 40   # message slots retained per conversation (tool messages count)
_MAX_LOOP    = 10   # max agentic iterations per request (safety valve)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a product analytics assistant for a B2B SaaS platform used by \
product managers, growth leads, and data analysts.

You have access to tools that query real event data, account data, \
and internal analyst notes. Your primary responsibility is to answer \
questions about feature adoption, user behaviour, account health, \
and product trends.

Important context model:
- The platform itself may be called Fifthrow, but the tracked usage data belongs to customer companies.
- Each customer company can have its own product.
- Do not assume the customer product name unless it exists in data.
- If asked "what product are we analysing?", answer from data:
  - first call account_list to retrieve customer_product_name values,
  - then summarize which customer products and companies are in scope,
  - and explicitly state unknowns only if customer_product_name is missing.

Rules:
- Always call a tool before responding if the question touches data \
  (trends, counts, accounts, notes). Never speculate when data is available.
- If the user asks about platform identity (who built this platform), call product_context.
- If the user asks about customer product identity, call account_list and answer from customer_product_name.
- When you have tool results, cite specific numbers and dates. \
  Do not speak in generalities like "usage is declining" — say \
  "funnel_analysis dropped from 471 events in week of Mar 16 to 254 in the week of Apr 13, a 46% decline".
- When something is anomalous or declining, say so clearly and \
  reference the data point that shows it.
- If a question requires multiple tools (e.g., trend + context from notes), \
  call them all before composing your answer.
- Be concise and direct. Bullet points are fine for multi-part answers. \
  Avoid filler phrases.
- If the data is insufficient to answer, say so explicitly rather than guessing.
"""

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AssistantService:
    def __init__(self) -> None:
        self._load_env_from_file()
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

    async def answer(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        datasource: Optional[DataSource] = None,
    ) -> dict[str, object]:
        conv_id = conversation_id or str(uuid.uuid4())

        if not self.api_key or self.client is None:
            return {
                "answer": "OpenAI API key is missing or invalid.",
                "conversation_id": conv_id,
                "used_tools": ["openai_unavailable"],
                "suggested_followups": [],
            }

        # Load and extend history.
        history = _conversation_memory.setdefault(conv_id, [])
        history.append({"role": "user", "content": message})

        executor = ToolExecutor(datasource) if datasource else None
        tools_used: list[str] = []

        # Build initial messages list (system prompt is never stored in history).
        messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}] + list(history)

        for _ in range(_MAX_LOOP):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOL_SCHEMAS if executor else None,
                    tool_choice="auto" if executor else None,
                )
            except Exception:
                return {
                    "answer": "OpenAI request failed. Check your API key and backend logs.",
                    "conversation_id": conv_id,
                    "used_tools": tools_used or ["openai_error"],
                    "suggested_followups": [],
                }

            msg = response.choices[0].message

            # ── Terminal: plain text response ──────────────────────────────
            if not msg.tool_calls:
                content = msg.content or "No response generated."
                history.append({"role": "assistant", "content": content})
                followups = await self._generate_followups(
                    conv_id=conv_id,
                    user_message=message,
                    assistant_answer=content,
                    tools_used=tools_used,
                )
                _trim(conv_id)
                return {
                    "answer": content,
                    "conversation_id": conv_id,
                    "used_tools": tools_used if tools_used else ["openai_chat_completion"],
                    "suggested_followups": followups,
                }

            # ── Tool calls ─────────────────────────────────────────────────
            # Append assistant turn (with tool_calls) to both lists.
            assistant_turn: dict = {
                "role": "assistant",
                "content": msg.content,  # may be None
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
            messages.append(assistant_turn)
            history.append(assistant_turn)

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                tools_used.append(tool_name)

                try:
                    args = json.loads(tc.function.arguments)
                    result_str = await executor.execute(tool_name, args) if executor else json.dumps({"error": "No datasource"})
                except Exception as exc:
                    result_str = json.dumps({"error": str(exc)})

                tool_turn: dict = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                }
                messages.append(tool_turn)
                history.append(tool_turn)

        # Exceeded iteration cap — return what we have.
        return {
            "answer": "Could not produce a final answer within the allowed reasoning steps.",
            "conversation_id": conv_id,
            "used_tools": tools_used,
            "suggested_followups": [],
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_env_from_file(self) -> None:
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#") or "=" not in cleaned:
                continue
            key, value = cleaned.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    async def _generate_followups(
        self,
        conv_id: str,
        user_message: str,
        assistant_answer: str,
        tools_used: list[str],
    ) -> list[str]:
        if self.client is None:
            return []

        seen = _conversation_followups_seen.setdefault(conv_id, set())
        seen_list = sorted(seen)

        prompt = (
            "Generate concise follow-up questions for a product analytics assistant.\n"
            "Return ONLY valid JSON in this format: "
            '{"suggested_followups":["...", "...", "..."]}\n'
            "Rules:\n"
            "- 3 to 5 follow-up questions\n"
            "- Must be specific and grounded in the prior answer\n"
            "- Must be useful next analytical steps\n"
            "- Avoid repeating these already-suggested followups: "
            f"{seen_list}\n"
            "- Avoid vague or generic prompts\n"
            "- No markdown, no explanation, JSON only"
        )

        context_payload = {
            "user_message": user_message,
            "assistant_answer": assistant_answer,
            "used_tools": tools_used,
        }

        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(context_payload)},
                ],
            )
            content = resp.choices[0].message.content or "{}"
            data = json.loads(content)
            candidates = data.get("suggested_followups", [])
            if not isinstance(candidates, list):
                return []
        except Exception:
            return []

        cleaned: list[str] = []
        seen_lower = {s.lower() for s in seen}
        for item in candidates:
            if not isinstance(item, str):
                continue
            q = item.strip()
            if not q:
                continue
            if q.lower() in seen_lower:
                continue
            cleaned.append(q)
            seen.add(q)
            seen_lower.add(q.lower())
            if len(cleaned) >= 5:
                break

        return cleaned


def _trim(conv_id: str) -> None:
    """Keep memory bounded."""
    turns = _conversation_memory.get(conv_id, [])
    if len(turns) > _MAX_HISTORY:
        _conversation_memory[conv_id] = turns[-_MAX_HISTORY:]
