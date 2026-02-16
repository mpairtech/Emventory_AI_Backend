# Architecture Overview

## Components

| Component               | Stack                              | Role                                                                                      |
| ----------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------- |
| **NestJS Backend**      | GraphQL (Apollo) + Raw SQL + MySQL | Product search, auth, logging. Single entry for Admin & E‑commerce.                       |
| **Admin Frontend**      | —                                  | Product management.                                                                       |
| **E‑commerce Frontend** | Custom theme                       | Live e‑commerce.                                                                          |
| **AI Service**          | FastAPI (this repo)                | Single third‑party service; multiple AI models inside. NestJS calls it by **model** name. |

## Flow

```
Admin / E‑commerce Frontend
    → Apollo (NestJS GraphQL)
        → NestJS calls AI Backend with a model (e.g. rag, semantic, embedding)
        → AI Backend (FastAPI) runs the internal service for that model
        → Result returned to NestJS
        → NestJS does product search (MySQL) / matches result
        → Response to Frontend
```

## NestJS ↔ AI Backend (FastAPI)

- **One AI service**: FastAPI exposes one service; internally it uses multiple AI models (embeddings, RAG, etc.).
- **Model-based calls**: NestJS hits the AI Backend with a **model** parameter so the right capability runs (e.g. `rag`, `semantic`, `embedding`, `index`).

### Unified endpoint (for NestJS)

- **`POST /api/v1/ai/invoke`**

  - Body: `{ "model": "<model_name>", "input": { ... } }`
  - FastAPI routes by `model` and runs the corresponding internal flow, then returns the result.

  **Request body by model:**

  | model       | input fields                              | description           |
  | ----------- | ----------------------------------------- | --------------------- |
  | `rag`       | `query`                                   | RAG answer + sources  |
  | `semantic`  | `query`                                   | Vector search results |
  | `embedding` | `text`                                    | Embedding vector      |
  | `index`     | `product_id`, `name`, `category`, `price` | Index product         |

  **Example (RAG):**

  ```json
  { "model": "rag", "input": { "query": "cheap laptop" } }
  ```

  **Response:** `{ "model": "rag", "result": { "answer": "...", "sources": [...] } }`

### Model-specific endpoints (optional)

- `POST /api/v1/search/rag` — RAG (retrieve + generate).
- `POST /api/v1/search/semantic` — Vector search only.
- `POST /api/v1/search/index` — Index a product (embedding + store).
- `POST /api/v1/search/debug` — Debug search.

NestJS can use either the unified `POST /api/v1/ai/invoke` with `model` or the direct search endpoints.

---

## Project structure (multiple AI features)

একটা FastAPI service এর ভেতরে অনেকগুলো AI feature রাখার জন্য structure এভাবে সাজানো:

```
app/
├── main.py                    # FastAPI app, exception handlers, router mount
├── api/v1/
│   ├── router.py              # সব v1 router একসাথে (search + ai)
│   ├── schemas.py             # Request/response models (AIInvokeRequest, SearchRequest, ...)
│   └── routers/
│       ├── ai_invoke.py       # একটাই entry: model দিয়ে dispatch (NestJS এর জন্য)
│       └── search.py          # Feature-specific: /search/rag, /search/semantic, /search/index, /search/debug
├── core/                      # Shared infrastructure (সব AI feature use করে)
│   ├── config.py              # DB, API keys (GEMINI_API_KEY, DATABASE_URL)
│   ├── exceptions.py          # RateLimitError, EmbeddingGenerationError, LLMGenerationError, ...
│   ├── llm/                   # AI provider clients (এক জায়গায়, সব feature use করে)
│   │   ├── gemini.py          # GeminiClient: embed(), generate()
│   │   └── embedding_client.py
│   └── vector/
│       └── pgvector.py        # VectorStore.search() — shared vector DB access
├── db/                        # DB session, models, repos (shared)
│   ├── session.py
│   ├── models/
│   └── repositories/
└── modules/                   # এক একটা AI feature = এক একটা module (এখানে multiple AI)
    ├── search/                # ✅ Implemented: product search + RAG
    │   ├── service.py         # SearchService: index_product, semantic_search, rag_search
    │   ├── embeddings.py      # EmbeddingService (Gemini দিয়ে embed)
    │   └── repository.py     # SearchRepository (product_vectors upsert)
    ├── content/               # 🔲 Placeholder (future: content moderation, summarization, ...)
    ├── fraud/                 # 🔲 Placeholder (future: fraud detection model)
    └── image/                 # 🔲 Placeholder (future: image tagging, similarity, ...)
```

### কিভাবে multiple AI feature fit হয়

| জায়গা                            | ভূমিকা                                                                                                                                                                              |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`core/llm/`**                   | সব AI model/provider এক জায়গায় (Gemini embed + generate). নতুন provider (e.g. OpenAI) এখানে add করলে সব module use করতে পারবে।                                                    |
| **`core/vector/`**                | Shared vector DB (pgvector). Search ছাড়াও অন্য feature চাইলে same store বা আলাদা table use করতে পারবে।                                                                             |
| **`modules/<feature>/`**          | প্রতিটা AI capability আলাদা module: নিজের `service`, দরকার হলে `repository`, `embeddings`। নতুন feature = নতুন folder + service, তারপর `ai_invoke` এ model নাম দিয়ে register।      |
| **`api/v1/routers/ai_invoke.py`** | NestJS শুধু এখানে hit করে `model` দিয়ে। ভেতরে `model` অনুযায়ী কোন module এর service চালাতে হবে সেটা decide হয় (এখন শুধু search-related models: rag, semantic, embedding, index)। |

### নতুন AI feature add করার ধাপ

1. **Module বানানো** — `app/modules/<feature>/` (e.g. `content/`, `fraud/`, `image/`):
   - `service.py` — business logic (কোন LLM/API call, কোন DB)।
   - প্রয়োজন হলে `repository.py`, নিজের schema/helper।
2. **Model নাম ঠিক করা** — NestJS যে নাম দিয়ে hit করবে (e.g. `content_summarize`, `fraud_check`, `image_tag`)。
3. **`api/v1/schemas.py`** — `AI_MODELS` এ নতুন model যোগ, `AIInvokeInput` এ ওই model এর জন্য লাগবে এমন optional field (e.g. `content_url`, `image_base64`)।
4. **`api/v1/routers/ai_invoke.py`** — `_validate_input` এ ওই model এর validation; `ai_invoke()` এ `if model == "content_summarize": ... ContentService.summarize(...)` ইত্যাদি।
5. (Optional) **Feature-specific router** — দরকার হলে `api/v1/routers/<feature>.py` এবং `router.py` এ include (e.g. `/content/summarize`), যাতে direct endpoint ও থাকে।

এই structure অনুযায়ী একই প্রজেক্টে অনেকগুলো AI feature (search, content, fraud, image, ...) একসাথে থাকবে এবং NestJS শুধু `POST /api/v1/ai/invoke` + `model` দিয়ে সঠিক feature টা run করাবে。

---

## Structure rating (১০-এর মধ্যে)

| মার্ক | **৮ / ১০** |
| ----- | ---------- |

### ভালো দিক (+)

- **Separation of concerns** — `core/` (shared), `modules/` (feature-wise), `api/` (entry) স্পষ্ট।
- **Single entry for NestJS** — `POST /api/v1/ai/invoke` + `model` দিয়ে সব AI feature এক জায়গা থেকে call করা যায়।
- **Multiple AI feature ready** — নতুন feature = নতুন module + `ai_invoke` এ একটু wiring; structure already support করে।
- **Shared LLM/vector** — `core/llm/`, `core/vector/` এক জায়গায়; duplicate code কম।
- **API versioning** — `api/v1/` থাকায় ভবিষ্যতে v2 নেওয়া সহজ।

### যেগুলো improve করলে ১০ নিকটে যাবে

- **Registry pattern** — এখন `ai_invoke.py` এ অনেকগুলো `if model == "..."`। Model list বড় হলে একটা **model registry** (dict/map: model name → handler function) করলে scaling ও test ভালো হবে।
- **Module-level schemas** — এখন সব input `schemas.py` এর একটা বড় `AIInvokeInput` এ। Feature বাড়লে প্রতিটা module নিজের request/response schema রাখলে (`modules/<feature>/schemas.py`) maintain সহজ।
- **Dependency injection** — LLM/vector client গুলো `Depends()` দিয়ে inject করলে test ও mock করা সহজ হয়।

সংক্ষেপে: multiple AI feature এর জন্য structure টা **৮/১০** — পরিষ্কার, scalable, NestJS-friendly; registry + module schemas + DI এগুলো add করলে ৯–১০ এর দিকে যাবে।
