# Emventory AI Backend — Product Roadmap

AI-based product search ও RAG সেবার জন্য এই ব্যাকএন্ডের দিকনির্দেশ ও পরবর্তী ধাপ।

---

## Product সংক্ষেপ

- **কি:** Org-based product vector search + RAG (Gemini)। MySQL (NestJS) এর product ডেটা এখানে index হয়ে semantic/RAG search হয়।
- **কাদের জন্য:** Emventory admin/store যারা org অনুযায়ী product খুঁজতে ও AI answer চায়।
- **স্ট্যাক:** FastAPI, PostgreSQL + pgvector, Gemini (embedding + generate), Docker।

---

## Phase 1 — সম্পন্ন (বর্তমান)

| আইটেম                | বর্ণনা                                                                                                                                                                                                                 |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Product indexing** | `POST /search/index` — org_id, product_id, name, category, brand, description, specifications, price, rating, review_count, status। Embedding text: Name, Category, Brand, Price, Description, Specifications, Rating। |
| **List indexed**     | `GET /search/indexed`, `POST /search/indexed/list` — কোন org কি কি index আছে দেখা।                                                                                                                                     |
| **Semantic search**  | `POST /search/semantic` — query দিয়ে embedding-based similarity search, org filter।                                                                                                                                   |
| **RAG search**       | `POST /search/rag` — semantic search + Gemini দিয়ে natural language answer।                                                                                                                                           |
| **Debug**            | `POST /search/debug` — query vs results similarity ও matching দেখার জন্য।                                                                                                                                              |
| **API security**     | API key = HMAC(API_SECRET, user_input)। Headers: `X-Key-Input`, `X-API-Key`। `POST /search/generate-key` দিয়ে input থেকে key নেওয়া।                                                                                  |
| **DB & schema**      | pgvector, `product_vectors` টেবিল, init/migration scripts, startup এ auto-init।                                                                                                                                        |
| **Docker**           | Dockerfile + docker-compose (postgres + app), healthcheck।                                                                                                                                                             |
| **Search API**       | সব capability feature-specific: `/search/rag`, `/search/semantic`, `/search/index`, `/search/indexed`, `/search/generate-key`, `/search/debug`।                                                                        |
| **Docs**             | FOLDER_AND_FLOW, MYSQL_TO_AI_INDEXING, RAG_GUIDE, DOCKER, ARCHITECTURE ইত্যাদি।                                                                                                                                        |

---

## Phase 2 — স্বল্পমেয়াদি (পরবর্তী)

| আইটেম                  | বর্ণনা                                                                                                    |
| ---------------------- | --------------------------------------------------------------------------------------------------------- |
| **Bulk indexing**      | একবারে অনেক product index — `POST /search/index/bulk` বা file upload। MySQL sync/export থেকে batch index। |
| **Re-index / delete**  | একটা product বা পুরো org এর index মুছে ফেলা / আবার index করা।                                             |
| **Search filters**     | Semantic/RAG এর সাথে price range, category, brand, status filter।                                         |
| **Pagination & limit** | List indexed ও search results এ limit/offset বা cursor-based pagination।                                  |
| **Rate limiting**      | IP/org অনুযায়ী request limit যাতে abuse না হয়।                                                          |
| **Health & metrics**   | `/health`, `/ready` এবং optional metrics (index count, search latency)।                                   |
| **Tests**              | Important endpoints এর জন্য integration/API tests বাড়ানো।                                                 |

---

## Phase 3 — মধ্যমেয়াদি

| আইটেম                      | বর্ণনা                                                                              |
| -------------------------- | ----------------------------------------------------------------------------------- |
| **Multi-tenant hardening** | Org isolation আরও কড়া, audit log (কে কোন org এর data access করছে)।                 |
| **Caching**                | জনপ্রিয় query বা embedding cache (Redis বা in-memory)।                             |
| **Better RAG**             | Context length ঠিক করা, prompt টিউন, source citation improve।                       |
| **Analytics**              | Search query log, popular queries, zero-result queries — optional dashboard/export। |
| **Webhook / events**       | Product index/update হলে অন্য সিস্টেমকে নটিফাই (যদি দরকার হয়)।                     |
| **Alternative embedding**  | একাধিক model support বা configurable embedding model।                               |

---

## Phase 4 — দীর্ঘমেয়াদি

| আইটেম                     | বর্ণনা                                                                  |
| ------------------------- | ----------------------------------------------------------------------- |
| **Hybrid search**         | Vector + keyword (BM25/full-text) combine করে ranking।                  |
| **Recommendations**       | “Similar products” বা “often bought with” style suggestions।            |
| **Multi-language**        | Query ও product text একাধিক ভাষায়; embedding/model accordingly।        |
| **Graph / related data**  | Category hierarchy বা product relation use করে search improve।          |
| **Self-hosted / on-prem** | Optional deployment guide ও config for air-gapped or strict compliance। |

---

## অগ্রাধিকার (সংক্ষেপ)

1. **এখনই:** Bulk index, re-index/delete, search filters, pagination।
2. **তারপর:** Rate limiting, health/metrics, tests, caching।
3. **পরে:** RAG improve, analytics, hybrid search, recommendations।

---

## নোট

- Roadmap পরিবর্তনযোগ্য — product need ও feedback অনুযায়ী আপডেট করা যাবে।
- প্রতিটি phase এ security (API key, org isolation) ও performance (DB, embedding cost) মাথায় রাখতে হবে।
