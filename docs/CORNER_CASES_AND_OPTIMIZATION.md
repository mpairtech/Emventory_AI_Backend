# Corner cases ও optimization

প্রজেক্টে যেসব corner case আছে এবং কোথায় optimize করা যায় — সংক্ষিপ্ত তালিকা ও সমাধান।

---

## ১. Corner cases (এখনই যেগুলো আছে)

### Config ও startup

| #   | Corner case                            | জায়গা               | সমস্যা                                                                                                |
| --- | -------------------------------------- | -------------------- | ----------------------------------------------------------------------------------------------------- |
| 1   | **Env না থাকলে app শুরুই হয় না**      | `core/config.py`     | `DB_PORT` string, সংখ্যা expected হলে validation নেই। `.env` এ typo থাকলে runtime এ DB error।         |
| 2   | **Gemini client import time এ বানায়** | `core/llm/gemini.py` | `GEMINI_API_KEY` খালি বা invalid হলে module load এই fail; error message ভালো না।                      |
| 3   | **DATABASE_URL এ password plain**      | `core/config.py`     | লগ/ডিবাগে leak হতে পারে। Production এ env থেকে read করাই ঠিক, কিন্তু sensitive value log করা যাবে না। |

### API ও schema

| #   | Corner case                                              | জায়গা                                   | সমস্যা                                                                                                                                                                                     |
| --- | -------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 4   | **`input.text` এর কোনো max length নেই**                  | `api/v1/schemas.py` (AIInvokeInput)      | বড় text দিলে Gemini token limit exceed / slow / cost বাড়ে।                                                                                                                               |
| 5   | **`input.query` max 500, SearchRequest query max 100**   | schemas                                  | একই জিনিস দুই জায়গায় আলাদা limit — inconsistent।                                                                                                                                         |
| 6   | **index এ name/category শুধু strip, অন্য validation না** | ai_invoke + repository                   | `name` এ শুধু whitespace দিলে strip এর পর খালি হতে পারে; DB/constraint এ error।                                                                                                            |
| 7   | **Empty product_vectors**                                | `modules/search/service.py` (rag_search) | টেবিল খালি থাকলে `results = []`, RAG একটা generic message দেয় — OK। কিন্তু semantic শুধু `[]` return করে; client কে “no data” নাকি “error” বোঝানোর জন্য structure একটু explicit করা যায়। |

### Database ও vector

| #   | Corner case                             | জায়গা                    | সমস্যা                                                                                      |
| --- | --------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------- |
| 8   | **Embedding dimension hardcoded (768)** | `db/models/vector.py`     | API যদি ভিন্ন dimension দেয় (বা model change) তাহলে insert/query fail।                     |
| 9   | **DB connection pool default**          | `db/session.py`           | `create_engine` এ pool_size/pre_ping না থাকলে connection leak বা stale connection হতে পারে। |
| 10  | **VectorStore.search empty embedding**  | `core/vector/pgvector.py` | Already check আছে; কিন্তু embedding list এ non-float থাকলে CAST fail।                       |

### Error handling ও security

| #   | Corner case                                | জায়গা                                      | সমস্যা                                                                                                 |
| --- | ------------------------------------------ | ------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 11  | **ProductNotFoundError কখনো raise হয় না** | `core/exceptions.py`, `main.py`             | Repository থেকে কেউ এটা raise করছে না — unused; ভবিষ্যতে get_by_id এ use করা যাবে।                     |
| 12  | **Routers এ exception handling duplicate** | `routers/search.py`, `routers/ai_invoke.py` | একই exception গুলো বারবার catch → HTTPException। এক জায়গায় (middleware/decorator) করলে maintain সহজ। |
| 13  | **কোনো auth নেই**                          | `main.py`                                   | NestJS internal call করলে OK; কিন্তু API public থাকলে যেকোনো কেউ hit করতে পারবে।                       |
| 14  | **Rate limit শুধু Gemini 429 এ**           | সার্বিক                                     | FastAPI layer এ নিজস্ব rate limit নেই; এক client অনেক request দিলে সব Gemini এ যাবে।                   |

### RAG ও LLM

| #   | Corner case                    | জায়গা                      | সমস্যা                                                                                                 |
| --- | ------------------------------ | --------------------------- | ------------------------------------------------------------------------------------------------------ |
| 15  | **RAG context size unbounded** | `modules/search/service.py` | অনেক product থাকলে context বড়; Gemini token limit exceed বা slow।                                     |
| 16  | **generate() এ context খালি**  | `core/llm/gemini.py`        | `context` empty string হলে prompt ঠিক আছে, কিন্তু “no products” case RAG service এ already handle করা। |

### Debug endpoint

| #   | Corner case                                     | জায়গা              | সমস্যা                                                                                          |
| --- | ----------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------- |
| 17  | **debug_search এ VectorSearchError handle নেই** | `routers/search.py` | semantic/rag এর মতো এখানে VectorSearchError explicitly catch করা নেই; generic Exception এ যাবে। |

---

## ২. Better structure (recommendations)

### ২.১ Model registry (scaling + test)

- **সমস্যা:** `ai_invoke.py` এ অনেকগুলো `if model == "..."`; নতুন model = আরও if।
- **সমাধান:** একটা **registry** (dict) — model name → handler function। নতুন model = একটা function + এক লাইন register।

```
app/core/ai_registry.py   # MODEL_HANDLERS = {"rag": handle_rag, "semantic": handle_semantic, ...}
app/api/v1/routers/ai_invoke.py  # handler = MODEL_HANDLERS.get(model); handler(req, db)
```

### ২.২ Config validation ও optional env

- **সমস্যা:** DB_PORT string, optional env (e.g. LOG_LEVEL) নেই।
- **সমাধান:** Pydantic এ `validator` / `field_validator` দিয়ে DB_PORT কে int করানো, optional field with default (e.g. `LOG_LEVEL: str = "INFO"`)। Startup এ একবার validation চালানো।

### ২.৩ Module-level schemas

- **সমস্যা:** সব input একটা বড় `AIInvokeInput` এ; feature বাড়লে এক জায়গা ফুলে যাবে।
- **সমাধান:** প্রতিটি module নিজের request/response রাখে, e.g. `modules/search/schemas.py`। `ai_invoke` শুধু `model` অনুযায়ী ওই module এর schema use করে validate।

### ২.৪ Shared exception → HTTP mapping

- **সমস্যা:** প্রতিটি router এ একই exception → status code mapping।
- **সমাধান:** `core/http_mapping.py` বা middleware: custom exception catch করে এক জায়গায় `JSONResponse`। Router শুধু service call করে; exception ওঠলে global handler handle করবে (ইতিমধ্যে main.py এ আছে, কিন্তু router গুলো আগে catch করে HTTPException করছে তাই main এর handler use হয় না)। তাই হয় router থেকে custom exception **re-raise** করতে দেয়া (তাহলে main এর handler কাজ করবে), নয়তো একটা **decorator** দিয়ে router ফাংশন wrap করা যাতে শুধু mapping এক জায়গায় থাকে।

### ২.৫ DB session: pool ও health

- **সমাধান:** `create_engine(..., pool_size=10, pool_pre_ping=True)`। Optional: startup event এ একটা trivial query দিয়ে DB connectivity check।

### ২.৬ Embedding dimension এক জায়গায়

- **সমাধান:** `core/config.py` বা `core/constants.py` এ `EMBEDDING_DIM = 768`। Model ও pgvector দুজায়গায় এই constant use করবে; model change করলে এক জায়গা পরিবর্তন।

---

## ৩. Optimized solutions (কোনটা আগে করবো)

### Priority 1 (দ্রুত ও কম ঝামেলা)

1. **Config:** `DB_PORT` কে int validation, optional `LOG_LEVEL`, `EMBEDDING_DIM=768` constant।
2. **Schema:** `AIInvokeInput.text` এ `max_length=8192` (বা একটা reasonable limit)।
3. **Schema:** index এর জন্য `name`/`category` strip এর পর খালি হলে Pydantic validator এ reject।
4. **debug_search:** `VectorSearchError` explicitly catch করে same HTTP mapping যেমন semantic/rag।

### Priority 2 (structure ভালো করার জন্য)

5. **Model registry:** `core/ai_registry.py` + `ai_invoke` এ dict lookup; নতুন model = register one function।
6. **DB session:** `pool_size`, `pool_pre_ping`; optional startup health check।
7. **RAG context cap:** e.g. top 10 এর পর আর product না নিয়ে, বা character limit দিয়ে context truncate।

### Priority 3 (ভবিষ্যৎ)

8. Module-level schemas যখন নতুন feature (content/fraud/image) add করবে।
9. API-level rate limiting (e.g. slowapi বা custom middleware) যখন traffic বাড়বে।
10. Auth (API key / JWT) যখন NestJS ছাড়া অন্য client আসবে।

---

## ৪. সংক্ষিপ্ত checklist

| করা হয়েছে কি? | আইটেম                                                                              |
| -------------- | ---------------------------------------------------------------------------------- |
| ✅             | Config: DB_PORT validation, LOG_LEVEL optional, EMBEDDING_DIM constant             |
| ✅             | AIInvokeInput.text max_length (8192); name/category strip + reject whitespace-only |
| ✅             | debug_search এ VectorSearchError handle                                            |
| ✅             | Model registry (core/ai_registry.py) + ai_invoke refactor                          |
| ✅             | DB pool_size=10, max_overflow=5, pool_pre_ping                                     |
| ☐              | RAG context limit (top-K or char limit)                                            |
| ☐              | ProductNotFoundError ব্যবহার (e.g. get_by_id) বা doc এ “reserved” লিখে রাখা        |

এই দিকগুলো মেনে optimize করলে structure আরও ভালো হবে এবং corner case গুলো কভার হবে।
