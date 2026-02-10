# ফোল্ডারগুলোর কাজ এবং প্রজেক্ট ফ্লো

এই ডকুমেন্টে **প্রথমে** প্রজেক্ট স্ট্রাকচার ও একটা request এর ওয়ার্কফ্লো সহজভাবে বোঝানো হয়েছে, **তারপর** প্রতিটি ফোল্ডারের বিস্তারিত।

---

## ১. প্রথমে এক নজরে

- **এই অ্যাপ কি:** AI-based product search (semantic + RAG)। Client request পাঠায় → আমরা embedding + vector search + (RAG হলে) Gemini দিয়ে answer দেই।
- **এক লাইনে ফ্লো:**  
  **Client → main.py → api (router) → module (search) → core + db → আবার api দিয়ে response।**

নিচে প্রথম **কোডবেস কেমন সাজানো** (structure) এবং **একটা request ঠিক কোথা দিয়ে কীভাবে যায়** (workflow) — দুটোই পরিষ্কার করা হয়েছে।

---

## ২. প্রজেক্ট স্ট্রাকচার (ফোল্ডার ট্রি)

```
app/
├── main.py                      # এন্ট্রি: FastAPI app, exception handlers, router mount
├── api/v1/
│   ├── router.py                # সব v1 রাউট একসাথে (search + ai)
│   ├── schemas.py               # Request/response এর shape (SearchRequest, ProductIndexRequest, ...)
│   └── routers/
│       └── search.py            # Search ফিচার: /search/rag, /semantic, /index, /indexed, /generate-key, ...
├── core/                        # সবার shared জিনিস (কোনো একটা feature এর জন্য না)
│   ├── config.py                # .env থেকে: DB, GEMINI_API_KEY, API_SECRET, LOG_LEVEL
│   ├── exceptions.py            # RateLimitError, EmbeddingGenerationError, VectorSearchError, ...
│   ├── llm/
│   │   └── gemini.py            # GeminiClient: embed(), generate()
│   └── vector/
│       └── pgvector.py         # VectorStore.search() — pgvector দিয়ে similarity search
├── db/
│   ├── session.py               # DB connection, get_db() — প্রতিটি request এ session
│   └── models/
│       └── vector.py            # ProductVector টেবিল (product_vectors)
├── modules/                     # Feature অনুযায়ী business logic (এক feature = এক ফোল্ডার)
│   └── search/
│       ├── service.py           # SearchService: index_product, semantic_search, rag_search
│       ├── embeddings.py        # EmbeddingService — টেক্সট → embedding (Gemini দিয়ে)
│       └── repository.py        # SearchRepository — product_vectors এ upsert
└── tests/
    └── db_test.py
```

**মনে রাখুন:**

- **api** = বাইরের দুনিয়ার সাথে কথা (URL, schema, কোন endpoint কী করবে)।
- **core** + **db** = সব feature এর shared জিনিস।
- **modules** = আসল কাজ (এখন শুধু **search**); ভবিষ্যতে আরও module যোগ করা যাবে।

---

## ৩. একটা request কিভাবে চলে (ওয়ার্কফ্লো)

যেকোনো HTTP request (যেমন search) এভাবে অ্যাপের ভেতর দিয়ে যায়:

```
  [Client]
      │
      │  POST /api/v1/search/rag  { "query": "cheap laptop" }
      ▼
  ┌─────────────┐
  │  main.py    │  ← FastAPI app, exception handlers, /api/v1 mount
  └──────┬──────┘
         │
         ▼
  ┌─────────────────────┐
  │  api/v1/router.py   │  ← search_router (ভবিষ্যতে আরও feature router)
  └──────┬──────────────┘
         │
         ▼
  ┌─────────────────────────┐
  │  routers/search.py      │  ← endpoint (rag_search), schema দিয়ে body validate, API key চেক
  └──────┬──────────────────┘
         │
         │  SearchService.rag_search(db, query)
         ▼
  ┌─────────────────────────┐
  │  modules/search/        │  ← business logic: embed → vector search → Gemini generate
  │  (service, embeddings,  │
  │   repository)           │
  └──────┬──────────────────┘
         │
         │  ব্যবহার করে: core/llm (Gemini), core/vector (pgvector), db/session, db/models
         ▼
  ┌─────────────────────────┐
  │  core/ + db/            │  ← config, GeminiClient, VectorStore, get_db(), ProductVector
  └──────┬──────────────────┘
         │
         │  result ফিরে
         ▼
  [response: { "answer": "...", "sources": [...] }]  →  Client
```

**সংক্ষেপে চার ধাপ:**

1. **main.py** — request ঢোকে, কোন error হলে এখানকার handler response দেয়।
2. **api/v1** — URL দেখে সঠিক রাউটার (search/ai) এ পাঠায়; রাউটার schema + API key চেক করে।
3. **modules/search** — search এর লজিক চালায় (embed, vector search, RAG generate)।
4. **core + db** — config, Gemini, pgvector, DB session, মডেল — এগুলো **modules** use করে; response আবার **api** দিয়ে client কে ফেরত যায়।

এই স্ট্রাকচার ও ফ্লো মাথায় রাখলে কোড খুঁজতে ও নতুন feature যোগ করতে সুবিধা হবে।

---

## ৪. কোন লেয়ার কী করে (টেবিল)

| লেয়ার / ফোল্ডার | কাজ                                                                                                                                                                         |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **main.py**      | এন্ট্রি পয়েন্ট। FastAPI app, global exception handlers, এবং `api/v1` রাউটার mount।                                                                                         |
| **api/**         | **দরজা।** কোন URL এ কী হবে, request/response এর structure (schemas), এবং API key যাচাই — এখানে। রাউটার শুধু **modules** বা **core** কে কল করে, নিজে business logic রাখে না। |
| **core/**        | **সবার shared।** Config (DB, API keys), exceptions, LLM client (Gemini), vector store (pgvector)। একাধিক feature এ একই জিনিস ব্যবহার হয়।                                   |
| **db/**          | DB **কানেকশন** (session) এবং **টেবিলের মডেল** (যেমন ProductVector)। কে কখন DB খুলবে/বন্ধ করবে, কোন টেবিলে কী column — সেটা এখানে।                                           |
| **modules/**     | **Feature-wise লজিক।** একটা feature = একটা ফোল্ডার (এখন শুধু `search/`)। ভেতরে service (কী করবে), repository (DB read/write), দরকার হলে embeddings। API শুধু এদেরকে ডাকে।   |
| **tests/**       | অ্যাপ/DB/লজিক ঠিক আছে কিনা চেক করার টেস্ট।                                                                                                                                  |

**নোট:**

- Request/response এর structure আলাদা ফোল্ডার নয় — **`api/v1/schemas.py`** এ আছে।
- নতুন feature = **modules** এ নতুন ফোল্ডার + **api** এ নতুন রাউট/স키মা; দরকার হলে **core/db** তে shared জিনিস যোগ।

---

## ৫. Search এর জন্য বিস্তারিত (কোথায় কী হয়)

### ৫.১ Entry: main.py

- সব request `POST /api/v1/...` বা `GET /api/v1/...` এ আসে।
- `app.include_router(router, prefix="/api/v1")` এর জন্য এই রাউটারই সব handle করে।
- কোন error (RateLimit, Embedding, DB, …) হলে main এর exception handler সঠিক HTTP response দেয়।

### ৫.২ Routing: api/v1/

- **router.py** — `search_router` যুক্ত (ভবিষ্যতে আরও feature router যোগ করা যাবে)।
  - `/api/v1/search/*` → **routers/search.py**
- **routers/search.py** — প্রতিটি endpoint (যেমন `POST /search/rag`) request নেয়, schema দিয়ে body validate করে, API key (X-Key-Input, X-API-Key) চেক করে, তারপর **modules/search** কে ডাকে।
- **schemas.py** — `SearchRequest`, `ProductIndexRequest`, `ListIndexedRequest`, `GenerateKeyRequest`, `RAGResponse` ইত্যাদি — request/response এর ফিল্ড ও টাইপ।

### ৫.৩ Business logic: modules/search/

- **service.py** — search এর মূল লজিক:
  - `index_product`: প্রোডাক্ট টেক্সট → embedding → DB তে সেভ।
  - `semantic_search`: query → embedding → vector search → results।
  - `rag_search`: একই vector search + Gemini দিয়ে answer জেনারেট।
- **embeddings.py** — টেক্সট → embedding এর একটা layer; ভেতরে **core/llm/gemini** কে ডাকে।
- **repository.py** — `product_vectors` টেবিলে insert/update (upsert); **db/models/vector** (ProductVector) ও **db session** ব্যবহার করে।

### ৫.৪ Shared: core/ ও db/

- **core/config.py** — DB URL, GEMINI_API_KEY, API_SECRET, LOG_LEVEL, EMBEDDING_DIM।
- **core/llm/gemini.py** — Gemini: embed (টেক্সট → vector), generate (RAG এর জন্য টেক্সট)।
- **core/vector/pgvector.py** — pgvector দিয়ে similarity search।
- **core/exceptions.py** — বিভিন্ন error ক্লাস; service/repository এ throw করলে main এ গিয়ে সঠিক HTTP response।
- **db/session.py** — connection pool, `get_db()`; রাউটারে `Depends(get_db)` দিলে request এ session পাওয়া যায়।
- **db/models/vector.py** — `ProductVector` টেবিলের definition (org_id, product_id, embedding, name, category, brand, price, ইত্যাদি)।

---

## ৬. একটা উদাহরণ: RAG request ধাপে ধাপে

1. Client পাঠায়: `POST /api/v1/search/rag` body `{ "query": "cheap laptop", "org_id": "..." }` (+ প্রটেক্টেড হলে headers: X-Key-Input, X-API-Key)।
2. **main** → **api/v1/router** → **routers/search.py** এর `rag_search`।
3. রাউটার `SearchRequest` দিয়ে validate করে, API key চেক করে, তারপর `SearchService.rag_search(db, query, org_id)` ডাকে।
4. **modules/search/service.py**:
   - `EmbeddingService.embed(query)` → **core/llm/gemini** দিয়ে query এর embedding।
   - `VectorStore.search(db, embedding, org_id)` → **core/vector/pgvector** দিয়ে DB থেকে নিকটতম product গুলো।
   - product গুলো দিয়ে context বানিয়ে `GeminiClient.generate(query, context)` → **core/llm/gemini** দিয়ে answer।
5. `{ "answer": "...", "sources": [...] }` ফিরে আসে।
6. search রাউটার এটা response হিসেবে দেয় → client পায়।

পুরো পথে **api** = দরজা, **modules/search** = কাজ, **core** ও **db** = shared জিনিস।

---

## ৭. সংক্ষেপে

- **প্রজেক্ট স্ট্রাকচার:** main + api (router + schemas + routers) + core (config, llm, vector, exceptions, registry) + db (session, models) + modules (এখন শুধু search) + tests।
- **ওয়ার্কফ্লো:** Client → main → api/v1 router → সঠিক রাউটার (search/ai) → module (business logic) → core + db → আবার api দিয়ে response।
- **api** = দরজা, **core** ও **db** = shared, **modules** = feature-wise লজিক।
- নতুন feature = **modules** এ নতুন ফোল্ডার + **api** এ রাউট/স키মা; প্রয়োজনে **core/db** তে shared অংশ যোগ।

এই স্ট্রাকচার ও ফ্লো দিয়ে কোড খুঁজতে ও প্রজেক্ট এগিয়ে নিতে পারবেন।
