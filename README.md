# ⚡ NL → SQL Assistant

A production-grade, **Natural Language to SQL** system that lets non-technical users query any PostgreSQL database using plain English — powered by Google Gemini, built with FastAPI, and designed with the same rigor as real-world LLM applications.

---

## ❗ Problem Statement

Data is locked inside databases that only engineers can query.

Business analysts, product managers, and operations teams face three hard problems every day:

- They **can't write SQL** — so they wait on data teams for every insight
- Data teams become **bottlenecks** — hours or days to answer questions that should take seconds
- When they do get SQL, they **can't verify it** — no way to know if the query is right, safe, or returning complete data

Traditional NL-to-SQL tools fail because they treat the LLM as a blackbox oracle — no validation, no safety, no cost control. One wrong query can scan an entire production table or return misleading results with no warning.

This project solves all three. It builds a complete, **production-style NL-to-SQL system** — from intent classification to safe SQL execution to result transparency — using the same defensive architecture used in enterprise AI systems.

---

## 📋 Table of Contents

- [Project Overview](#-project-overview)
- [Business Context](#-business-context)
- [System Architecture](#️-system-architecture)
- [Pipeline Deep Dive](#-pipeline-deep-dive)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [How to Run Locally](#-how-to-run-locally)
- [Key Highlights](#-key-highlights)
- [Future Improvements](#-future-improvements)

---

## 🚀 Project Overview

This project implements a production-grade NL-to-SQL intelligence system that goes far beyond "send question to LLM, return SQL." It covers the complete lifecycle of safe, reliable natural language database querying:

| Capability | What It Does |
|---|---|
| **Intent Classification** | Multi-layer filter rejects off-topic, malicious, or ambiguous queries before touching the LLM |
| **Schema-Aware SQL Generation** | Injects live database schema into Gemini's context — no hallucinated tables or columns |
| **SQL Safety Validation** | Blocks all non-SELECT statements; prevents injection, stacked queries, and comment exploits |
| **Confidence Evaluation** | Rule-based warnings for missing filters, ambiguous columns, exact-match ILIKE, and large results |
| **CTE-Aware Execution** | Injects LIMIT safely on both plain SELECTs and WITH clauses without truncating the wrong subquery |
| **Result Transparency** | Truncation flags, row counts, and structured warning codes surfaced to the user |
| **On-Demand Explanation** | Plain-English summary of what the SQL does — triggered only when the user asks |
| **Session History** | Conversation-aware SQL generation; follow-up questions reference previous context |
| **Schema Caching** | TTL-based schema cache with fingerprinting; auto-refreshes only on actual schema changes |
| **Query Observability** | Structured JSONL logging of every request with latency breakdown, warning codes, and failure stage |

---

## 🏦 Business Context

### The Problem

Non-technical teams making data-driven decisions face significant challenges:

- **No consistent access** — insights depend on SQL expertise or data team availability
- **No portfolio visibility** — no way to explore a database schema without knowing SQL
- **LLM blindness** — off-the-shelf NL-to-SQL tools don't know your schema and hallucinate freely
- **Safety gaps** — without validation, a poorly phrased question could generate a destructive or runaway query

### The Solution

This system provides a **data-driven, standardized framework** for natural language database access:

- **Multi-layer validation** ensures only safe, relevant, well-formed queries reach the database
- **Schema-aware prompting** grounds the LLM in real table and column names — eliminating hallucination
- **Backend-controlled guardrails** (LIMIT, read-only mode, blocked keywords) prevent LLM from controlling system-level constraints
- **Structured warnings** give users visibility into result quality, not just results
- **Cost-conscious design** calls the LLM only when necessary — explanation is on-demand, not automatic

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────┐
│              User (Browser / Frontend)           │
│           Pure HTML / CSS / JavaScript           │
└─────────────────────┬───────────────────────────┘
                      │  HTTP / REST API
┌─────────────────────▼───────────────────────────┐
│              FastAPI Backend                     │
│      /query  /explain  /schema  /session         │
│      /admin/logs  /admin/metrics  /health        │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│           7-Stage Query Pipeline                 │
│                                                  │
│  [1] Ambiguity Check (rule-based)                │
│  [2] Schema Relevance Check (fuzzy keyword)      │
│  [3] LLM Classifier (Gemini — VALID/INVALID)     │
│  [4] SQL Generation (Gemini + schema context)    │
│  [5] Confidence Evaluation (rule-based warnings) │
│  [6] SQL Validation (safety gate)                │
│  [7] Execution (asyncpg, read-only, LIMIT cap)   │
└──────────┬──────────────────────┬───────────────┘
           │                      │
┌──────────▼──────────┐  ┌───────▼───────────────┐
│  GeminiProvider     │  │  QueryExecutor          │
│  (classify + gen)   │  │  CTE-aware LIMIT inject │
│  Retry + fallback   │  │  asyncpg connection pool│
│  Truncation detect  │  │  Read-only transaction  │
└─────────────────────┘  └───────────────────────┘
           │
┌──────────▼──────────┐
│  Schema Cache        │
│  TTL + fingerprint   │
│  Auto-refresh on     │
│  schema change       │
└─────────────────────┘
```

### Key Design Decisions

**7-Stage Defense Pipeline:** Every query passes through intent check → LLM classification → SQL generation → confidence evaluation → safety validation → execution. Each stage is a hard gate — failure at any stage returns a structured error without reaching the database.

**LLM Does Not Control System Constraints:** LIMIT injection, read-only mode, and row caps all live in the backend executor layer. The LLM is never trusted to enforce these itself.

**Schema Caching with Fingerprinting:** Schema is extracted once, cached with a TTL, and only re-extracted when the MD5 fingerprint changes — avoiding redundant DB calls while staying current.

**On-Demand Explanation:** The `/explain` endpoint is completely separate from `/query`. Explanation is never called automatically — only when the user clicks the button. This eliminates unnecessary LLM calls on every query.

**Session Isolation:** Each session carries its own conversation history (last N turns), credentials (custom mode), and schema context. Sessions are independent in-memory — no cross-user contamination.

---

## 🔬 Pipeline Deep Dive

### Stage 1 — Ambiguity Check (Rule-Based)
Fast pre-filter before any LLM call. Rejects greetings, write-intent keywords (`INSERT`, `DROP`), and questions too short or vague to be answerable. "High ambiguity" = hard reject. "Low ambiguity" = allow with a warning attached to the response.

### Stage 2 — Schema Relevance Check (Fuzzy Keyword)
Extracts all table and column names from the schema, then checks if the user's question contains words that match (with fuzzy matching via `difflib.SequenceMatcher`). Catches typos like "produts" matching "products". Rejects questions with zero schema overlap before spending an LLM call.

### Stage 3 — LLM Classifier (Gemini)
Sends the question + schema to Gemini with a strict VALID/INVALID classification prompt. Parses the structured response (CLASSIFICATION / REASON lines). Falls back to INVALID on parse failure — never assumes validity.

### Stage 4 — SQL Generation (Gemini + Schema Context)
Builds a prompt that injects:
- Full formatted schema (tables, columns, PKs, FKs, types)
- Conversation history (last N turns for follow-up awareness)
- 10 strict SQL rules (ILIKE wildcards, explicit JOINs, no SELECT *, named columns, semicolons, etc.)

Gemini's output is cleaned: markdown fences stripped, prose prefixes removed, multi-statement output truncated to first statement. Truncation detection checks for unbalanced parentheses, CTEs with no outer SELECT, and unclosed OVER() clauses — retrying with a larger token budget if detected.

### Stage 5 — Confidence Evaluation (Rule-Based)
Runs six checks against the generated SQL without executing it:

| Check | Warning Code | Condition |
|---|---|---|
| No WHERE on large table | `MISSING_FILTER` | `borrowings` queried with no filter |
| SELECT * used | `SELECT_STAR` | Pattern `SELECT\s+\*` detected |
| Unqualified ambiguous column | `AMBIGUOUS_COLUMN` | `status`, `name`, `date`, `id` without table prefix |
| No LIMIT or aggregate | `LARGE_RESULT` | No LIMIT, no COUNT/SUM/AVG/MAX/MIN |
| Vague question words | `LOW_CONFIDENCE` | "something", "anything", "stuff" detected |
| ILIKE without wildcards | `STRICT_MATCH` | `ILIKE 'value'` instead of `ILIKE '%value%'` |

All warnings are non-fatal — the query continues but the frontend surfaces them prominently.

### Stage 6 — SQL Validation (Safety Gate)
Hard blocking rules — any failure here returns an error with no execution:

- Must start with `SELECT` or `WITH` (CTEs allowed)
- CTEs must contain at least one `SELECT`
- Blocked keywords: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `REPLACE`, `GRANT`, `REVOKE`, `EXECUTE`
- No stacked statements (no mid-query semicolons)
- No SQL comment injections (`--`, `/* */`)
- Maximum length cap (5000 chars)

### Stage 7 — Execution (CTE-Aware, Read-Only)
The executor wraps every query in a `SET TRANSACTION READ ONLY` block. Before executing, `_inject_limit()` runs:

- If SQL already has `LIMIT` → cap it at `MAX_RESULT_ROWS` if it exceeds, leave it otherwise
- If no `LIMIT` → inject one, but for CTEs, parse paren depth to find the **outer SELECT** position and inject there — not inside the CTE body

Result formatting handles `datetime`, `Decimal`, and `timedelta` serialization. If `total_fetched > MAX_RESULT_ROWS`, `truncated=True` is set and a `LARGE_RESULT` warning is appended post-execution.

---

## ✨ Key Features

### 🛡️ Multi-Layer Validation System
Three distinct layers of query defense before any SQL reaches the database:
- **Layer 1 — Rule-Based Filter:** Catches obvious cases instantly, zero LLM cost
- **Layer 2 — LLM Classifier:** Validates intent against the actual schema
- **Layer 3 — SQL Validator:** Enforces hard safety rules on generated SQL

### 🧠 Schema-Aware Prompting
Live database schema is injected into every LLM prompt. The LLM sees actual table names, column types, primary keys, and foreign key relationships — making hallucination structurally impossible for in-schema queries.

### 🔄 Conversation-Aware SQL Generation
Session history (last N question/SQL pairs) is injected into the prompt. "Show me their email too" correctly refers to the member from the previous query. Follow-up questions work naturally.

### ⚡ Schema Caching with Fingerprinting
Schema is extracted once, cached with a configurable TTL, and only re-fetched when the MD5 fingerprint of the schema dict changes. A schema refresh that finds no changes just resets the TTL — no version bump, no redundant work.

### 💡 On-Demand SQL Explanation
A separate `/explain` endpoint generates a plain-English summary of what the SQL does. The frontend caches explanations per SQL string — repeated clicks cost zero additional LLM calls.

### 📊 Query Observability Dashboard
Every request writes a structured JSONL log entry with:
- Full latency breakdown (classify / generate / execute / total)
- Warning codes, error stage, row count, truncation flag
- Session ID, mode, fallback model usage

`/admin/metrics` aggregates these into success rate, p95 latency, top error stages, and top warning codes in real time.

### 🗂️ Schema Explorer
The frontend includes a collapsible schema explorer showing all tables, columns, PKs, and FKs — rendered from the cached `/schema` endpoint. No extra API calls; the schema is already in memory.

### 📤 Export Toolbar
Query results can be copied as a tab-separated table, downloaded as CSV, or downloaded as Excel — directly from the frontend with no backend round-trip.

### 🔌 Custom Mode
Users can supply their own PostgreSQL URL and Gemini API key. The system initializes a fresh schema extraction, session, and credential store for that connection. Demo mode and custom mode coexist with zero state collision.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI (Python) |
| **LLM** | Google Gemini 2.5 Flash (via `google-genai` SDK) |
| **Database** | PostgreSQL (asyncpg connection pool) |
| **Schema Extraction** | `information_schema` queries (tables, columns, PKs, FKs) |
| **Validation** | Pydantic v2 (all request/response models) |
| **Async** | Python `asyncio` throughout (DB, LLM, logging) |
| **Frontend** | Vanilla HTML / CSS / JavaScript (no framework) |
| **Logging** | JSONL structured logging (background tasks) |
| **Configuration** | `pydantic-settings` + `.env` file |

---

## 📂 Project Structure

```
nl-to-sql/
│
├── backend/
│   ├── api/
│   │   ├── middleware.py          # CORS + request logging middleware
│   │   └── routes/
│   │       ├── query.py           # POST /query — main 7-stage pipeline
│   │       ├── explain.py         # POST /explain — on-demand SQL explanation
│   │       ├── schema.py          # GET /schema, POST /schema/refresh
│   │       ├── session.py         # Session init, info, reset, delete
│   │       └── admin.py           # GET /admin/logs, /metrics, /sessions
│   │
│   ├── cache/
│   │   └── schema_cache.py        # TTL cache with MD5 fingerprinting
│   │
│   ├── config.py                  # pydantic-settings — all config from .env
│   ├── dependencies.py
│   │
│   ├── db/
│   │   ├── connection.py          # asyncpg pool creation, health check
│   │   └── schema_extractor.py    # information_schema queries → structured dict
│   │
│   ├── llm/
│   │   └── gemini_provider.py     # Gemini wrapper — retry, fallback, truncation detection
│   │
│   ├── models/
│   │   ├── request.py             # QueryRequest, CredentialsInput, SchemaRefreshRequest
│   │   └── response.py            # QueryResponse, SchemaResponse, WarningDetail, etc.
│   │
│   ├── prompts/
│   │   ├── classifier.py          # VALID/INVALID classification prompt builder
│   │   └── nl_to_sql.py           # SQL generation prompt with 10 strict rules
│   │
│   ├── services/
│   │   ├── classifier.py          # Fast reject + LLM classify + schema relevance
│   │   ├── confidence.py          # 6-check rule-based warning evaluator
│   │   ├── nl_to_sql.py           # SQL generation + explanation (calls GeminiProvider)
│   │   ├── query_executor.py      # CTE-aware LIMIT injection + asyncpg execution
│   │   ├── query_logger.py        # JSONL logging + metrics aggregation
│   │   ├── schema_service.py      # Public facade over schema cache
│   │   ├── session_manager.py     # In-memory session store + credential management
│   │   └── validator.py           # SQL safety gate (blocked keywords, structure checks)
│   │
│   └── main.py                    # App factory, startup/shutdown, health endpoint
│
├── frontend/
│   ├── index.html                 # Full single-page UI
│   ├── css/style.css              # Design system (CSS variables, dark SQL theme)
│   └── js/app.js                  # All frontend logic (state, API calls, rendering)
│
├── demo/
│   └── seed.sql                   # Library management demo DB (3 tables, 60 rows)
│
├── logs/
│   └── query_logs.jsonl           # Structured per-request log (JSONL, auto-created)
│
├── evaluation/
│   ├── evaluator.py
│   ├── expected_sql.json
│   └── test_queries.json
│
├── tests/
│   ├── test_classifier.py
│   ├── test_nl_to_sql.py
│   ├── test_schema_service.py
│   └── test_validator.py
│
├── requirements.txt
└── .env.example
```

---

## ⚙️ How to Run Locally

### Prerequisites

- Python 3.9+
- PostgreSQL (local or remote)
- Google Gemini API key (free tier works)

### 1. Clone and Install

```bash
git clone https://github.com/OmPatel01/nl-to-sql.git
cd nl-to-sql
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set Up Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/your_db
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
MAX_RESULT_ROWS=500
SCHEMA_CACHE_TTL_SECS=3600
```

### 3. Seed Demo Database (Optional)

```bash
psql -U your_user -d your_db -f demo/seed.sql
```

This creates a Library Management System demo database with `members`, `books`, and `borrowings` tables and 60+ rows of realistic seed data.

### 4. Start the Backend

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### 5. Open the Frontend

Open `frontend/index.html` directly in your browser, or serve it:

```bash
cd frontend
python -m http.server 3000
# Open http://localhost:3000
```

### 6. Try It Out

For **demo mode** — just open the UI and start asking questions:
- *"Show me all overdue borrowings with member names"*
- *"Which members have borrowed the most books?"*
- *"List books in the Sci-Fi genre with available copies"*

For **custom mode** — enter your PostgreSQL URL and Gemini API key in the connection panel.

---

## 📌 Key Highlights

**Production-grade LLM pipeline:**
- 7-stage query defense with hard gates at each step
- Truncation detection and retry with doubled token budget
- Exponential backoff + fallback model for Gemini failures
- CTE-aware LIMIT injection — structurally correct, not string-appended

**Clean software architecture:**
- Strict separation: routes → services → cache → DB
- No business logic in route handlers
- Services are FastAPI-agnostic (pure Python, independently testable)
- Background task logging — never adds to response latency

**Cost-conscious LLM design:**
- Fast-reject filters eliminate LLM calls for obvious invalid queries
- Schema relevance check costs zero tokens
- Explanation is on-demand only — never automatic
- Frontend caches explanations per SQL — no duplicate calls

**Real observability:**
- Structured JSONL log per request with latency breakdown and failure stage
- `/admin/metrics` aggregates success rate, p95 latency, top warning codes
- `/admin/logs` supports filtering by status and error-only views
- `/admin/sessions` shows active session count and per-session turn history

**User transparency:**
- Warnings surface non-fatal issues without blocking results
- Truncation is always explicit — users know when they're seeing partial data
- On-demand explanation bridges the gap between "SQL returned" and "what does it mean"

---

## 🔮 Future Improvements

| Area | Improvement |
|---|---|
| **Model** | Periodic prompt drift detection — flag when generated SQL quality degrades |
| **Validation** | Column-level schema verification of generated SQL (does `members.email` actually exist?) |
| **Cache** | Redis-backed schema cache for multi-worker / multi-process deployments |
| **Session** | Persistent session storage (Redis or DB) — current in-memory store resets on restart |
| **Evaluation** | Automated SQL accuracy evaluation against `evaluation/expected_sql.json` |
| **Frontend** | CSV upload for bulk question evaluation |
| **API** | JWT authentication and rate limiting for production use |

---

## 💬 Honest Evaluation

This is not a basic "call GPT with a question, return SQL" project.

It is an **LLM-powered intelligent query system with production-grade safeguards** — built with the understanding that LLMs must be treated as unreliable components, wrapped with strong backend controls, and never trusted with system-level constraints.

> *"I started with a simple NL-to-SQL prototype, but iteratively evolved it into a production-style architecture by introducing multi-layer validation, schema-aware prompting, execution guardrails, CTE-aware SQL handling, and cost-optimized LLM usage. The key learning was that the hard problems in LLM systems are not generation — they are validation, transparency, and cost control."*

---

## 📬 Contact

Built by **Om Patel**

📧 ompatel2587@gmail.com  
🔗 [LinkedIn](https://linkedin.com/in/your-profile)