# fifthrow-be

A product analytics AI assistant backend built with FastAPI. It connects to a PostgreSQL database of product events, accounts, and internal notes, and exposes a chat API where an OpenAI model answers analytics questions by calling typed tools grounded in real data. Uploaded CSV or JSON files are merged with the live database on a per-conversation basis, so users can ask questions against their own data without writing queries.

---

## Local setup

### Prerequisites

- Python 3.9+
- PostgreSQL 16+ running locally
- An OpenAI API key

---

### 1. Clone and install

```bash
git clone https://github.com/harpsquatch/fifthrow-be.git
cd fifthrow-be

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### 2. Configure environment

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/fifthrow
```

Adjust `DATABASE_URL` to match your local Postgres credentials.

---

### 3. Create the database

```bash
createdb -h 127.0.0.1 -p 5432 -U postgres fifthrow
```

If your local Postgres requires a password:

```bash
PGPASSWORD='your_password' createdb -h 127.0.0.1 -p 5432 -U postgres fifthrow
```

---

### 4. Run migrations

```bash
source .venv/bin/activate
alembic upgrade head
```

This creates three tables: `accounts`, `events`, `notes`.

---

### 5. Seed the database

```bash
python scripts/seed.py
```

Inserts:
- 8 accounts across enterprise / growth / starter plan tiers
- ~21,000 events over 30 days with baked-in trends (funnel decline, AI assistant growth, starter activation drop)
- 5 internal analyst notes

---

### 6. Start the server

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API is now available at `http://127.0.0.1:8000`.

---

### 7. Send your first chat message

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Why is funnel_analysis usage declining?"}'
```

The model will call `feature_trend` and `notes_list` tools, then return a data-grounded answer.

---

## API reference

### `GET /health`

Returns server status.

**Response**

```json
{"status": "ok"}
```

---

### `POST /api/chat`

Send a message. The model runs an agentic loop — calling tools against the database until it has enough data to answer — then returns a plain-text response.

**Request**

```json
{
  "message": "Which features are growing among enterprise accounts?",
  "conversation_id": "optional-uuid-to-continue-a-session"
}
```

`conversation_id` is optional on the first message. Pass the returned value on follow-up messages to maintain conversation history.

**Response**

```json
{
  "answer": "Among enterprise accounts over the last 30 days, ai_assistant is growing strongly — up from 86 events in the week of Mar 16 to 290 in the week of Apr 13, a 237% increase. dashboard is stable with a slight decline. funnel_analysis has dropped ~40% over the same period.",
  "conversation_id": "9c59f3f7-729a-479b-aace-72856552d2a6",
  "used_tools": ["feature_distribution", "feature_trend", "feature_trend"]
}
```

**`used_tools`** lists the actual tool names called during this request. An empty tool call falls back to `["openai_chat_completion"]`.

---

### `POST /api/upload`

Upload a CSV or JSON file to enrich a conversation with custom data. The endpoint detects whether the file contains events, accounts, or notes based on the fields present, and attaches it to the given conversation. Subsequent `/api/chat` calls with the same `conversation_id` will query a merged view of the database and the uploaded data.

**Request** — `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | file | CSV or JSON file |
| `conversation_id` | string | Conversation to attach the upload to |

**Example**

```bash
curl -X POST http://127.0.0.1:8000/api/upload \
  -F "file=@events.csv;type=text/csv" \
  -F "conversation_id=9c59f3f7-729a-479b-aace-72856552d2a6"
```

**Accepted file formats**

- **CSV** — first row is the header
- **JSON** — a top-level array `[{...}, ...]`, or an object with a known key such as `{"events": [...]}` or `{"accounts": [...]}`

**Type detection** — the endpoint inspects the column names and picks the best match:

| Detected type | Required fields |
|---|---|
| `events` | `event_name` + `distinct_id` |
| `accounts` | `company_name` or `mrr` |
| `notes` | `content` + `author` |

**Response**

```json
{
  "conversation_id": "9c59f3f7-729a-479b-aace-72856552d2a6",
  "detected_type": "events",
  "row_count": 142,
  "message": "Loaded 142 events rows into conversation 9c59f3f7-729a-479b-aace-72856552d2a6."
}
```

Multiple uploads to the same conversation are supported and additive — each one appends to the relevant bucket.

---

## Architecture

### DataSource pattern

All data access goes through the `DataSource` abstract base class (`app/services/datasource.py`). It defines seven methods:

| Method | What it returns |
|---|---|
| `feature_trend(feature, days, plan)` | Daily counts for one feature |
| `feature_distribution(days, plan)` | Count per feature, sorted desc |
| `compare_features(features, days, plan)` | Weekly counts side-by-side |
| `account_list(plan, industry)` | Account rows with MRR and seats |
| `event_sample(event_name, days, company_id, plan, limit)` | Raw event rows |
| `activation_trend(event_name, days, plan)` | Daily counts broken down by plan tier |
| `notes_list(tags, limit)` | Analyst notes with optional tag filter |

Three implementations exist:

- **`PostgresDataSource`** — queries the live database using SQLAlchemy async. Takes an `AsyncSession` injected per request via FastAPI's `Depends`.
- **`UploadedDataSource`** — holds in-memory lists of events, accounts, and notes parsed from uploaded files. Implements all the same methods using Python aggregations.
- **`MergedDataSource(base, overlay)`** — wraps two DataSource instances. For aggregated methods (trend, distribution, compare, activation), it calls both, then sums counts by grouping key. For list methods (account_list, event_sample, notes_list), it concatenates, de-duplicates by id, and re-sorts.

The AI assistant and tool executor never know which implementation they are talking to.

---

### Agentic loop

`AssistantService.answer()` runs a loop with a ceiling of 10 iterations:

1. Append the user message to the in-memory conversation history (keyed by `conversation_id`).
2. Send the full history plus all seven tool schemas to OpenAI.
3. If the model returns `tool_calls`, execute each via `ToolExecutor`, which dispatches to the appropriate `DataSource` method and serialises the result as a JSON string.
4. Append the assistant turn (with `tool_calls`) and each tool result (as `role: tool` messages) to history.
5. Send the updated history back to OpenAI and repeat.
6. When the model returns a plain text response with no tool calls, return it to the caller.

The system prompt instructs the model to always call tools before responding and to cite specific numbers and dates rather than speaking in generalities.

---

### Upload merge flow

```
POST /api/upload
  → parse file (CSV or JSON)
  → detect type by column names
  → get or create UploadedDataSource for conversation_id
  → add rows to the matching bucket (events / accounts / notes)
  → store in upload_store (in-memory dict)

POST /api/chat
  → create PostgresDataSource(session)
  → check upload_store for conversation_id
  → if found: datasource = MergedDataSource(postgres, uploaded)
  → else:     datasource = PostgresDataSource
  → run agentic loop with that datasource
```

Uploaded data is process-local and not persisted across server restarts. It is scoped to a single conversation.

---

## Project structure

```
fifthrow-be/
├── app/
│   ├── api/
│   │   ├── router.py                   # Mounts /api prefix
│   │   └── routes/
│   │       ├── chat.py                 # POST /api/chat
│   │       └── upload.py               # POST /api/upload
│   ├── core/
│   │   └── config.py                   # Env var loading + validation
│   ├── db/
│   │   ├── base.py                     # Async engine + session factory
│   │   └── models.py                   # Account, Event, Note ORM models
│   ├── models/
│   │   └── schemas.py                  # ChatRequest / ChatResponse
│   ├── services/
│   │   ├── datasource.py               # Abstract base class
│   │   ├── postgres_datasource.py      # SQLAlchemy async implementation
│   │   ├── uploaded_datasource.py      # In-memory implementation
│   │   ├── merged_datasource.py        # Combines base + overlay
│   │   ├── upload_store.py             # Per-conversation upload registry
│   │   ├── tool_executor.py            # TOOL_SCHEMAS + dispatch
│   │   └── assistant_service.py        # OpenAI agentic loop
│   └── main.py                         # FastAPI app + CORS
├── migrations/
│   ├── env.py                          # Async Alembic config
│   └── versions/
│       └── 0001_initial_schema.py      # accounts, events, notes
├── scripts/
│   └── seed.py                         # Inserts realistic mock data
├── alembic.ini
├── requirements.txt
└── .env                                # Not committed — see setup above
```
