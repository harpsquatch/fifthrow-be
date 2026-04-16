from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    used_tools: list[str]
