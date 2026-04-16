# ADR-001: AI Analytics Assistant — Architecture Decisions

**Date:** April 16, 2026  
**Status:** Implemented

---

## Context

We are building a minimal AI chat assistant for a B2B SaaS product analytics platform. The assistant must answer natural language questions about product usage, grounded in real data. The system must support a predefined dataset, user-uploaded data, and tool-based reasoning.

---

## ADR-001: DataSource Abstraction as the Core Swap Point

**Decision:** All data access goes through an abstract `DataSource` interface. The AI layer, tool definitions, and agentic loop never touch a database or data format directly.

**Reasoning:** The assistant needs to work against mock data today, real Postgres tomorrow, and user-uploaded CSVs in the same session. If the AI talked to Postgres directly, every data source change would require changes to the AI layer. The interface decouples them completely.

**Consequence:** Adding a new data source — ClickHouse, BigQuery, a live Mixpanel API — is a single file. Implement the interface, inject it. Nothing else changes.

---

## ADR-002: Postgres over TimescaleDB or ClickHouse

**Decision:** Plain Postgres with a timestamped `events` table and JSONB `properties` column.

**Reasoning:** At assessment scale (21k events) Postgres queries in milliseconds. TimescaleDB and ClickHouse add operational complexity — setup, drivers, extensions — that buys nothing at this volume. The 3-5 hour constraint makes this the right call.

**Upgrade path:** TimescaleDB is a drop-in Postgres extension — same schema, same queries, adds time-based partitioning and compression. ClickHouse would require a new `ClickHouseDataSource` implementation. Either swap happens entirely within the DataSource layer.

**Production note:** Event streams are append-only and time-series in nature. Postgres handles this well up to ~50M rows. Beyond that, columnar storage becomes necessary — same pattern Mixpanel uses with Arb, their in-house columnar store sharded by `distinct_id`.

---

## ADR-003: JSONB Properties Column — Schema-on-Read

**Decision:** Event properties are stored as a JSONB blob rather than individual columns.

**Reasoning:** Mixpanel's Arb database uses this exact pattern — ingest arbitrary JSON, infer schema at query time. Fixed columns would require a migration every time a new event property is tracked. JSONB allows any upstream product to send any properties without schema coordination.

**Consequence:** Queries filter on `properties->>'feature'` rather than a dedicated column. Slight query overhead, but the flexibility is worth it at this scale. For production, a GIN index on the properties column resolves the performance concern.

---

## ADR-004: Zero Domain Knowledge in the System Prompt

**Decision:** The system prompt contains no description of the product, features, or what is being tracked. The assistant discovers everything from the data.

**Reasoning:** A system prompt that describes the product hardcodes assumptions. If a different company connects their database, the assistant would describe the wrong product. The assistant should be a blank slate — it knows how to reason about analytics data, not what this specific product is.

**Implementation:** The first tool call for any identity question (`what is our product?`) is always `account_list`, which returns `customer_product_name` per account. Product identity comes from the database, not the prompt.

**Consequence:** The assistant is genuinely plug-and-play. Connect any database that implements the DataSource interface and the assistant accurately describes that product.

---

## ADR-005: Agentic Loop with Tool Chaining

**Decision:** The assistant runs in a loop — send message, execute tool calls, feed results back, repeat — until OpenAI returns a plain text response. Max 10 iterations as a safety valve.

**Reasoning:** Single-turn tool use is insufficient for analytical questions. "Why did activation drop?" requires: pull the trend, pull the notes, pull the account segment, synthesize. That's 3 tool calls in sequence. The loop enables natural multi-step reasoning without the user having to decompose the question themselves.

**Consequence:** Latency scales with tool calls. Each iteration is an OpenAI round trip. For production, parallel tool execution where calls are independent would reduce this significantly.

---

## ADR-006: MergedDataSource for User Uploads

**Decision:** When a user uploads data, a `MergedDataSource(base=Postgres, overlay=Uploaded)` is created for that session. Uploaded data is merged with, not replacing, the predefined dataset.

**Reasoning:** Users rarely upload complete datasets. They upload a CSV of recent events, or a JSON of new accounts. A pure replace would lose all the baseline data. Merging means partial uploads still produce useful answers — uploaded events appear alongside seeded events, uploaded accounts extend the account list.

**Session scope:** Upload state is in-memory, keyed by `conversation_id`. Two users' uploads never interfere. Production path is Redis or S3 for persistence across restarts.

---

## ADR-007: Excluding Today from Trend Queries

**Decision:** All daily aggregation queries use `WHERE DATE(timestamp) < CURRENT_DATE`.

**Reasoning:** Partial-day data creates false anomaly signals. An account with 69 peak daily active users showing 8 today looks like a critical drop — but it's 9am. Including today in trend analysis would cause the assistant to consistently flag the current day as a decline, eroding trust in its answers.

**Consequence:** The assistant's view of "recent" is always yesterday-complete. For real-time monitoring this would need a separate live query path — but for daily trend analysis it's the correct default.
