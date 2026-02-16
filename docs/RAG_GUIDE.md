# RAG (Retrieve-Augmented Generation) Guide

RAG endpoint কিভাবে কাজ করে এবং কিভাবে use করবেন।

---

## RAG কি?

**RAG = Retrieve + Generate**

1. **Retrieve**: আপনার query এর embedding বানিয়ে DB থেকে নিকটতম product গুলো খুঁজে আনে (vector similarity search)।
2. **Generate**: ওই product গুলো দিয়ে context বানিয়ে Gemini LLM কে দিয়ে একটা natural answer জেনারেট করে।

---

## Endpoints

### ১. Direct RAG endpoint

**POST** `/api/v1/search/rag`

**Request:**

```json
{
  "query": "cheap laptop under 500"
}
```

**Response:**

```json
{
  "answer": "Based on the available products, I found several budget-friendly laptops...",
  "sources": [
    {
      "product_id": 1,
      "name": "Budget Laptop",
      "category": "Electronics",
      "price": 299.99,
      "similarity_score": 0.85
    },
    ...
  ]
}
```

---

## আমাদের product অনুযায়ী model কি কি জানে?

**মডেল আগে থেকে আমাদের কোনো product list জানে না।**

- Gemini (LLM) এর training এ আমাদের product নেই।
- **প্রতিবার request এ** আমরা:
  1. আপনার **query** দিয়ে আমাদের **DB (product_vectors)** এ vector search করি।
  2. যে product গুলো query এর সাথে **সবচেয়ে কাছাকাছি** (similarity অনুযায়ী) সেগুলো নিয়ে একটা **context** (টেক্সট) বানাই।
  3. ওই **context + query** শুধু সেই request এ Gemini কে দিই।
- তাই **মডেল শুধু ওই retrieved product গুলোই “জানে”** — যে গুলো আমরা ওই query এর জন্য DB থেকে এনে context এ দিয়েছি।

**আমাদের DB তে যা index করা আছে শুধু সেগুলোই** search/retrieve হয়। নতুন product দিলে আগে **index** করতে হবে, তবেই RAG সেটা পাবে।

---

## RAG model কিভাবে run করে? (step by step)

```
1. Request: { "query": "headphones 3000 TK" }
   ↓
2. EmbeddingService.embed(query)
   → Gemini text-embedding-004 দিয়ে query এর একটা vector (768 সংখ্যা) বানায়।
   ↓
3. VectorStore.search(db, embedding)
   → আমাদের DB (product_vectors) এ ওই vector এর সাথে কতটা কাছাকাছি সেটা মাপে (cosine similarity)।
   → যেগুলো সবচেয়ে কাছাকাছি (top 10) সেগুলো return করে।
   ↓
4. আমাদের DB তে শুধু "Budget Laptop" index করা ছিল
   → তাই "headphones" query এর সাথেও ওটাই সবচেয়ে কাছাকাছি হয়ে গেছে (similarity ~0.45)।
   → sources = [Budget Laptop] (একটা product)।
   ↓
5. Context বানানো হয় শুধু ওই retrieved product দিয়ে:
   → "- Budget Laptop (Category: Electronics, Price: $299.99, Similarity: 0.45)"
   ↓
6. Gemini কে পাঠানো হয়:
   → "You are a helpful product assistant. Based on the following product information..."
   → Product Information: "- Budget Laptop (...)"
   → User Query: "headphones 3000 TK"
   ↓
7. Gemini উত্তর দেয় শুধু ওই context দেখে:
   → "I only have Budget Laptop, no headphones in my inventory."
   ↓
8. Response: { "answer": "...", "sources": [Budget Laptop] }
```

তাহলে: **আমাদের product list = শুধু যেগুলো DB তে index করা আছে।** RAG প্রতিবার **query দিয়ে DB থেকে retrieve** করে, সেই গুলো দিয়ে context বানিয়ে **শুধু সেই context** মডেলকে দেয়। মডেল নিজে DB বা product list দেখে না।

---

## কিভাবে কাজ করে (technical step by step)

```
1. Request: { "query": "cheap laptop" }
   ↓
2. EmbeddingService.embed(query)
   → Gemini text-embedding-004 দিয়ে query এর vector (768 dim)
   ↓
3. VectorStore.search(db, embedding)
   → PostgreSQL pgvector দিয়ে cosine similarity search
   → Top 10 নিকটতম product (similarity_score descending)
   ↓
4. যদি product না পাওয়া যায়:
   → { "answer": "I couldn't find...", "sources": [] }
   ↓
5. যদি product পাওয়া যায়:
   → Context format: "- Product Name (Category: X, Price: $Y, Similarity: 0.85)"
   → GeminiClient.generate(query, context)
   → Gemini Flash দিয়ে natural answer জেনারেট
   ↓
6. Response: { "answer": "...", "sources": [product list] }
```

---

## Setup (প্রথমবার)

### ১. Database setup

```bash
# Python script (recommended)
python scripts/init_db.py

# অথবা SQL directly
psql -U your_user -d your_db -f scripts/init_db.sql
```

এটা করবে:

- `vector` extension enable
- `product_vectors` table create

### ২. Product index করা (data থাকতে হবে)

RAG কাজ করার জন্য আগে কিছু product index করতে হবে:

**POST** `/api/v1/search/index`

```json
{
  "product_id": 1,
  "name": "Budget Laptop",
  "category": "Electronics",
  "price": 299.99
}
```

একবার index করলে:

- Product text → embedding → DB তে save
- পরে RAG/search এ use হবে

---

## Example requests

### cURL

```bash
# RAG search
curl -X POST http://127.0.0.1:8000/api/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "cheap laptop"}'
```

### Python

```python
import requests

# RAG
response = requests.post(
    "http://127.0.0.1:8000/api/v1/search/rag",
    json={"query": "cheap laptop"}
)
print(response.json())
```

---

## Error handling

| Error                      | Status | কারণ                                                  |
| -------------------------- | ------ | ----------------------------------------------------- |
| `EmbeddingGenerationError` | 503    | Gemini embedding API fail (rate limit, network, auth) |
| `VectorSearchError`        | 500    | DB query fail বা embedding format issue               |
| `LLMGenerationError`       | 503    | Gemini generate API fail                              |
| `DatabaseError`            | 500    | DB connection/operation fail                          |
| `RateLimitError`           | 429    | Gemini API rate limit exceed                          |

Empty result (no products found):

- Status: 200
- Response: `{ "answer": "I couldn't find...", "sources": [] }`

---

## Tips

1. **Query ভালো হলে result ভালো**: "cheap laptop" > "laptop" (more specific)
2. **Product index করতে ভুলবেন না**: RAG কাজ করার জন্য DB তে product থাকতে হবে
3. **Similarity score**: 0.0 (no match) থেকে 1.0 (perfect match)। সাধারণত 0.7+ হলে ভালো match
4. **Context size**: এখন top 10 product use হয়; অনেক product থাকলে সব নাও হতে পারে (future: context limit)

---

## Code flow

```
api/v1/routers/search.py::rag_search()
  → SearchService.rag_search(db, query)
    → EmbeddingService.embed(query)  [modules/search/embeddings.py]
      → GeminiClient.embed(text)  [core/llm/gemini.py]
    → VectorStore.search(db, embedding)  [core/vector/pgvector.py]
      → PostgreSQL pgvector cosine search
    → GeminiClient.generate(query, context)  [core/llm/gemini.py]
  → Return {answer, sources}
```

---

## Next steps

- RAG test করতে: আগে কিছু product index করুন, তারপর query করুন
- Better results: বেশি product index করুন, specific query ব্যবহার করুন
- Customize: `modules/search/service.py` এর `rag_search()` এ prompt/context format change করতে পারেন
