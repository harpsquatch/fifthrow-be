from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.schemas import ChatRequest, ChatResponse
from app.services import upload_store
from app.services.assistant_service import AssistantService
from app.services.merged_datasource import MergedDataSource
from app.services.postgres_datasource import PostgresDataSource

router = APIRouter(tags=["chat"])
assistant_service = AssistantService()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    postgres_ds = PostgresDataSource(session)

    # If the client supplied a conversation_id and there is uploaded data for
    # that session, merge it on top of the Postgres source.
    uploaded_ds = (
        upload_store.get(request.conversation_id)
        if request.conversation_id
        else None
    )
    ds = MergedDataSource(postgres_ds, uploaded_ds) if uploaded_ds else postgres_ds

    result = await assistant_service.answer(
        message=request.message,
        conversation_id=request.conversation_id,
        datasource=ds,
    )
    return ChatResponse(**result)
