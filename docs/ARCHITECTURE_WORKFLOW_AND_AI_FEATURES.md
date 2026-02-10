# Architecture, Workflow, Folder Structure & Multiple AI Features

This document explains the backend in order: **architecture** → **workflow** → **folder structure** → **how multiple AI features work and how to add new ones**.

**Standard:** All AI capabilities are exposed only via **feature-specific routes** (one capability = one endpoint). No unified “invoke by model” endpoint.

---

## 1. Architecture

### 1.1 High-level layers

The app is split into clear layers so that **HTTP**, **business logic**, and **shared infrastructure** stay separate.

```
┌─────────────────────────────────────────────────────────────────┐
│  Entry & global setup                                            │
│  main.py: FastAPI app, exception handlers, router mount          │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│  API layer (gate)                                                │
│  api/v1: routing, request/response schemas, auth (API key)       │
│  • router.py → search_router (and future feature routers)        │
│  • routers/search.py                                             │
│  • schemas.py                                                    │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│  Feature layer (business logic)                                   │
│  modules/: one folder per AI feature (e.g. search)                │
│  • service, repository, embeddings, etc.                          │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│  Shared infrastructure                                            │
│  core/: config, LLM client (Gemini), vector store, exceptions    │
│  db/:   session, models                                          │
└─────────────────────────────────────────────────────────────────┘
```

- **main.py** — Single entry; no business logic.
- **api/v1** — Only routing, validation, and auth; calls into modules.
- **modules/** — All feature logic; uses **core** and **db**.
- **core/** and **db/** — Used by all features; no feature-specific code.

### 1.2 How AI capabilities are exposed (standard)

**One capability = one endpoint.** Clients call the exact URL for the capability they need:

| Capability          | Method & URL                       | Purpose                                       |
| ------------------- | ---------------------------------- | --------------------------------------------- |
| RAG search          | `POST /api/v1/search/rag`          | Query → vector search + AI answer             |
| Semantic            | `POST /api/v1/search/semantic`     | Query → similar products                      |
| Index product       | `POST /api/v1/search/index`        | Index one product (embedding + DB)            |
| List indexed        | `GET /api/v1/search/indexed`       | List indexed products (optional query params) |
| List indexed (POST) | `POST /api/v1/search/indexed/list` | Same with JSON body                           |
| Generate API key    | `POST /api/v1/search/generate-key` | Get API key for an input (e.g. org_id)        |
| Debug               | `POST /api/v1/search/debug`        | Debug similarity / matching                   |

Each endpoint has its own schema and (where applied) API key check. No “model” parameter; the URL defines the capability.

---

## 2. Workflow (request flow)

### 2.1 Path of a single request

Every HTTP request follows the same path:

```
Client
  │
  │  HTTP Request (e.g. POST /api/v1/search/rag)
  ▼
┌──────────────────────────────────────────────────────────────────┐
│  main.py                                                          │
│  • Receives request                                               │
│  • On error: exception handlers return appropriate HTTP response  │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  api/v1/router.py                                                 │
│  • Prefix: /api/v1                                                │
│  • Dispatches to search_router (by path prefix)                    │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  routers/search.py                                                │
│  • /search/* endpoints                                            │
│  • Validate body (schemas)                                        │
│  • API key check (X-Key-Input, X-API-Key)                         │
│  • Call module (e.g. SearchService.rag_search)                     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  modules/search/                                                  │
│  • service, repository, embeddings                                 │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  core/ + db/                                                      │
│  • Config, GeminiClient, VectorStore, exceptions                  │
│  • get_db(), ProductVector model                                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
                      JSON response → Client
```

### 2.2 Summary

1. **main.py** — Entry; global exception handling.
2. **api/v1/router.py** — Mounts feature routers (e.g. search) under `/api/v1`.
3. **routers/search.py** — Validates input and API key, then calls **modules/search**.
4. **modules/** — Runs the feature logic; uses **core** and **db**.
5. Response goes back through the same layers to the client.

---

## 3. Folder structure

### 3.1 Tree

```
app/
├── main.py                      # Entry: FastAPI app, exception handlers, mount /api/v1
├── api/v1/
│   ├── router.py                # Aggregates all v1 routers (search; more later)
│   ├── schemas.py               # Request/response models (Pydantic)
│   └── routers/
│       └── search.py            # /search/rag, /semantic, /index, /indexed, /generate-key, /debug
├── core/                        # Shared across all features
│   ├── config.py                # Settings from .env (DB, GEMINI_API_KEY, API_SECRET, etc.)
│   ├── exceptions.py            # Custom exceptions (RateLimitError, EmbeddingGenerationError, ...)
│   ├── llm/
│   │   └── gemini.py            # GeminiClient: embed(), generate()
│   └── vector/
│       └── pgvector.py          # VectorStore.search()
├── db/
│   ├── session.py               # Engine, SessionLocal, get_db()
│   └── models/
│       └── vector.py            # ProductVector (product_vectors table)
├── modules/                     # One folder per AI feature
│   └── search/
│       ├── service.py           # SearchService: index_product, semantic_search, rag_search
│       ├── embeddings.py       # EmbeddingService (uses core/llm)
│       └── repository.py        # SearchRepository (product_vectors upsert)
└── tests/
    └── db_test.py
```

### 3.2 Role of each part

| Layer / folder | Role                                                                                                                                                    |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **main.py**    | Create app, register exception handlers, mount `api/v1` router. Startup: init DB (pgvector, tables).                                                    |
| **api/v1/**    | **Gate:** define URLs, validate request/response (schemas), apply auth where needed. No business logic; only calls **modules** (or **core** if needed). |
| **core/**      | **Shared:** config, LLM client, vector store, exceptions. Used by every feature.                                                                        |
| **db/**        | **Data:** connection (session), table definitions (models). Used by modules that need DB.                                                               |
| **modules/**   | **Features:** one directory per capability (e.g. `search`). Contains service, repository, and any feature-specific helpers (e.g. embeddings).           |
| **tests/**     | Tests for app, DB, and logic.                                                                                                                           |

Schemas live in **api/v1/schemas.py**.  
New features = new **module** + new **router** (and routes) under **api/v1**.

---

## 4. How multiple AI features work

### 4.1 One feature = one router (and its routes)

Each AI capability belongs to a **feature** (e.g. search). The feature has:

- **modules/<feature>/** — service, repository, helpers.
- **api/v1/routers/<feature>.py** — routes under a prefix (e.g. `/search`).

Clients always call **feature routes**; there is no second “unified” entry point.

### 4.2 Current: search feature

**Routes:** All under `/api/v1/search/`:

- `POST /search/rag` — RAG search.
- `POST /search/semantic` — Semantic search.
- `POST /search/index` — Index one product.
- `GET /search/indexed` — List indexed (query params).
- `POST /search/indexed/list` — List indexed (JSON body).
- `POST /search/generate-key` — Generate API key from input.
- `POST /search/debug` — Debug search.

**Module:** `modules/search/` (SearchService, EmbeddingService, SearchRepository).  
**Shared:** `core/` (config, Gemini, pgvector, exceptions), `db/` (session, ProductVector).

### 4.3 Adding a new AI feature (e.g. content or fraud)

1. **New module**  
   Create `modules/<feature>/` with at least:

   - `service.py` (business logic),
   - and optionally repository, helpers, etc.

2. **Use core and db**  
   The new module uses **core** (config, LLM if needed, exceptions) and **db** only if it needs persistence.

3. **New router and routes**

   - Add **api/v1/routers/<feature>.py** with a router (e.g. prefix `/content`).
   - Define endpoints (e.g. `POST /content/moderate`) with their own schemas and auth.
   - In **api/v1/router.py**, include the new router:  
     `router.include_router(content_router)` (or similar).

4. **Schemas**  
   Add request/response models for the new feature in **schemas.py** (or a dedicated file if you prefer).

No registry, no “model” dispatch. New capability = new routes under a new (or existing) feature prefix.

### 4.4 Summary diagram (multiple AI features)

```
                    Client
                       │
                       │  POST /api/v1/search/rag  (or /search/semantic, /search/index, ...)
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  main.py  →  api/v1/router.py  →  routers/search.py               │
│  (validate, API key, then call module)                            │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  modules/search/  (service, repository, embeddings)                │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  core/ + db/  (config, LLM, vector, session, models)               │
└──────────────────────────────────────────────────────────────────┘

Future: modules/content/ + routers/content.py  →  /api/v1/content/*
        modules/fraud/   + routers/fraud.py    →  /api/v1/fraud/*
```

---

## 5. Quick reference

- **Architecture:** Entry (main) → API (gate) → Modules (features) → Core + DB (shared). **Single style:** feature-specific routes only.
- **Workflow:** Request → main → api/v1 router → feature router (e.g. search) → module → core/db → response.
- **Folder structure:** `main.py`, `api/v1` (router, schemas, routers), `core/`, `db/`, `modules/<feature>/`, `tests/`.
- **Multiple AI features:** Implement in **modules/**; expose via **feature routers** (one router per feature, with clear endpoints). Share **core** and **db**. No unified invoke; no model registry.

This keeps the API clear and consistent: one capability = one endpoint; clients use only the routes you expose.
