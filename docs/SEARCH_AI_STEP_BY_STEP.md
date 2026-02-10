# Search AI — স্টেপ বাই স্টেপ (কোন API আগে, কোনটা পরে)

এক লাইনে: **প্রথমে Key জেনারেট → তারপর প্রোডাক্ট Index → তারপর RAG/Semantic Search**।

---

## ধাপ ১: API Key জেনারেট (যদি API_SECRET সেট থাকে)

Backend এ `.env` এ `API_SECRET` থাকলে প্রতিটি protected API তে **X-Key-Input** ও **X-API-Key** header দিতে হয়। Key টা আসে `HMAC(API_SECRET, input)` দিয়ে; `input` সাধারণত **org_id**।

- **কি করবেন:**  
  একবার (অথবা প্রতিটি org_id এর জন্য) একটা key নিতে হবে।

**API:** `POST /api/v1/search/generate-key`

- **Headers (অবশ্য):**
  - `X-Key-Input: generate`
  - `X-API-Key: HMAC(API_SECRET, "generate")` — এই value টা শুধু backend/আপনার জানে; client কে দেবেন না, backend থেকে key generate করে NestJS/Admin এ সেভ করবেন।
- **Body:**

  ```json
  { "input": "3b7f6e51-1f00-4cff-a435-53364d0ed49c" }
  ```

  এখানে `input` = সেই org এর **org_id** (যে org এর জন্য index/search চালাবেন)।

- **Response:**
  ```json
  { "input": "3b7f6e51-1f00-4cff-a435-53364d0ed49c", "token": "a1b2c3..." }
  ```
  এই `token` টা সেভ করে রাখুন — **Index** ও **Search** এর সময় এই token + ওই org_id use করবেন।

**নোট:** যদি `API_SECRET` সেট না থাকে, তাহলে ধাপ ১ ছেড়ে দিয়ে সরাসরি ধাপ ২ থেকে শুরু করবেন (কোনো header লাগবে না)।

---

## ধাপ ২: প্রোডাক্ট Index করা

MySQL/Admin এ প্রোডাক্ট create/update হলে সেই ডেটা AI backend এ পাঠাতে হবে যাতে vector store এ ঢুকে।

**API:** `POST /api/v1/search/index`

- **Headers (যদি API_SECRET থাকে):**

  - `X-Key-Input: <org_id>` (যে org এর প্রোডাক্ট)
  - `X-API-Key: <ধাপ ১ থেকে পাওয়া token>`

- **Body (উদাহরণ):**

  ```json
  {
    "org_id": "3b7f6e51-1f00-4cff-a435-53364d0ed49c",
    "product_id": "prod-001",
    "name": "Budget Laptop",
    "category": "Electronics",
    "price": 299.99,
    "brand": "TechBrand",
    "description": "Good for students"
  }
  ```

- **Response:** `201` + `{ "status": "indexed", "org_id": "...", "product_id": "...", "message": "..." }`

একটা প্রোডাক্টের জন্য একবার; একই product_id আবার পাঠালে **update** হবে (upsert)।

---

## ধাপ ৩ (ঐচ্ছিক): Index কতগুলো আছে দেখতে

**API:** `GET /api/v1/search/indexed?org_id=<org_id>&limit=100`

- **Headers:** ওই একই `X-Key-Input` + `X-API-Key` (org_id এর key)।

যাচাই করতে চাইলে ধাপ ২ এর পর এটা hit করে দেখতে পারেন কতগুলো প্রোডাক্ট vector store এ আছে।

---

## ধাপ ৪: Search — RAG অথবা Semantic

ইউজার query দিলে AI answer (RAG) অথবা শুধু প্রোডাক্ট লিস্ট (semantic) পেতে।

### RAG (Answer + sources)

**API:** `POST /api/v1/search/rag`

- **Headers:** `X-Key-Input: <org_id>`, `X-API-Key: <token>`
- **Body:**
  ```json
  { "query": "cheap laptop", "org_id": "3b7f6e51-1f00-4cff-a435-53364d0ed49c" }
  ```
- **Response:** `{ "answer": "...", "sources": [ ... ] }`

### শুধু Semantic (প্রোডাক্ট লিস্ট, AI answer নাই)

**API:** `POST /api/v1/search/semantic`

- **Headers:** একই।
- **Body:** `{ "query": "cheap laptop", "org_id": "..." }`
- **Response:** `{ "results": [ ... ], "query": "..." }`

`org_id` optional — না দিলে সব org এর প্রোডাক্ট থেকে search (সাধারণত এক org এ দিয়ে দেবেন)।

---

## সংক্ষেপে অর্ডার

| ধাপ        | API                                           | কাজ                                                  |
| ---------- | --------------------------------------------- | ---------------------------------------------------- |
| ১          | `POST /search/generate-key`                   | org_id এর জন্য token নেওয়া (একবার বা per org)       |
| ২          | `POST /search/index`                          | প্রোডাক্ট index/update (create/update এ এক একটা করে) |
| ৩ (ঐচ্ছিক) | `GET /search/indexed`                         | কতগুলো index আছে দেখতে                               |
| ৪          | `POST /search/rag` বা `POST /search/semantic` | ইউজার query দিয়ে search                             |

**মনে রাখুন:**

- আগে **key generate** (ধাপ ১), তারপর **index** (ধাপ ২), তারপর **search** (ধাপ ৪)।
- `API_SECRET` না থাকলে ধাপ ১ ছাড়াই ২ ও ৪ চালাবেন, header ছাড়া।
