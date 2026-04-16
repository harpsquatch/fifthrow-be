"""
POST /api/upload

Accepts a CSV or JSON file upload alongside a conversation_id.
Detects what type of data the file contains (events, accounts, notes)
and stores it in the per-conversation UploadedDataSource.

Content-Type: multipart/form-data
Fields:
  - file:            the file to upload
  - conversation_id: the conversation this upload belongs to

Response:
  {"conversation_id": "...", "detected_type": "events", "row_count": 42}
"""
import csv
import io
import json

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.services import upload_store
from app.services.uploaded_datasource import UploadedDataSource

router = APIRouter(tags=["upload"])


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_json(content: bytes) -> list[dict]:
    data = json.loads(content.decode("utf-8", errors="replace"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Support {"events": [...]} / {"accounts": [...]} / {"notes": [...]}
        for key in ("events", "accounts", "notes", "data", "rows", "records"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    raise ValueError("Unrecognised JSON structure — expected list or object.")


def _auto_parse(content: bytes, filename: str) -> list[dict]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return _parse_csv(content)
    if lower.endswith(".json") or lower.endswith(".jsonl"):
        return _parse_json(content)
    # Detect by content
    stripped = content.lstrip()
    if stripped.startswith(b"[") or stripped.startswith(b"{"):
        return _parse_json(content)
    return _parse_csv(content)


# ---------------------------------------------------------------------------
# Type detection
# ---------------------------------------------------------------------------

def _normalise_keys(row: dict) -> set[str]:
    return {k.lower().strip().replace(" ", "_") for k in row}


_EVENT_SIGNALS   = {"event_name", "distinct_id"}
_ACCOUNT_SIGNALS = {"company_name", "mrr", "company_id"}
_NOTE_SIGNALS    = {"content", "author", "tags", "note_id"}


def detect_type(rows: list[dict]) -> str:
    if not rows:
        return "unknown"
    # Sample up to 5 rows to handle sparse/malformed data
    sample_keys: set[str] = set()
    for row in rows[:5]:
        sample_keys |= _normalise_keys(row)

    event_score   = len(sample_keys & _EVENT_SIGNALS)
    account_score = len(sample_keys & _ACCOUNT_SIGNALS)
    note_score    = len(sample_keys & _NOTE_SIGNALS)

    best = max(event_score, account_score, note_score)
    if best == 0:
        return "unknown"
    if event_score == best:
        return "events"
    if account_score == best:
        return "accounts"
    return "notes"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload(
    file: UploadFile,
    conversation_id: str = Form(...),
) -> dict:
    if not conversation_id.strip():
        raise HTTPException(status_code=422, detail="conversation_id is required.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    filename = file.filename or ""
    try:
        rows = _auto_parse(content, filename)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse file '{filename}': {exc}",
        )

    if not rows:
        raise HTTPException(status_code=400, detail="No data rows found in file.")

    dtype = detect_type(rows)
    if dtype == "unknown":
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not detect data type. "
                "Events require 'event_name' + 'distinct_id'. "
                "Accounts require 'company_name' or 'mrr'. "
                "Notes require 'content' + 'author'."
            ),
        )

    # Get or create the UploadedDataSource for this conversation.
    ds = upload_store.get(conversation_id)
    if ds is None:
        ds = UploadedDataSource()
        upload_store.put(conversation_id, ds)

    if dtype == "events":
        ds.add_events(rows)
    elif dtype == "accounts":
        ds.add_accounts(rows)
    else:
        ds.add_notes(rows)

    return {
        "conversation_id": conversation_id,
        "detected_type": dtype,
        "row_count": len(rows),
        "message": f"Loaded {len(rows)} {dtype} rows into conversation {conversation_id}.",
    }
