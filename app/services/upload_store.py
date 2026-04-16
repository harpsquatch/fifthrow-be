"""
Shared in-memory store for per-conversation uploaded data sources.

Kept in its own module so both the upload route and the chat route
can import it without creating circular dependencies.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.uploaded_datasource import UploadedDataSource

# conversation_id → UploadedDataSource
_store: dict[str, "UploadedDataSource"] = {}


def get(conversation_id: str) -> "UploadedDataSource | None":
    return _store.get(conversation_id)


def put(conversation_id: str, ds: "UploadedDataSource") -> None:
    _store[conversation_id] = ds
