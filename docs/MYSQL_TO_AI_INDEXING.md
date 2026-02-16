# MySQL থেকে Org-based Indexing ও Search

আপনার UI/Admin প্রজেক্ট MySQL এ ডেটা রাখে (`emventory_admin_db`) — org, product, store ইত্যাদি। AI search/RAG এর জন্য সেই ডেটা কিভাবে **org অনুযায়ী** index করবেন এবং search করবেন।

---

## ১. ধারণা

- **MySQL (NestJS)** = সোর্স অফ ট্রুথ: `organization`, `product` (org_id, product_id, name, category, price ইত্যাদি)।
- **PostgreSQL + pgvector (এই FastAPI AI backend)** = vector store যেখানে আমরা **org_id + product_id** দিয়ে প্রোডাক্ট index করি এবং query দিয়ে semantic/RAG search করি।
- প্রতিটি **org** এর প্রোডাক্ট আলাদা — search করার সময় **org_id** দিলে শুধু সেই org এর প্রোডাক্ট দেখাবে।

---

## ২. টেবিল ম্যাপিং (MySQL → AI Backend)

| MySQL (emventory_admin_db) | AI Backend (PostgreSQL product_vectors) |
| -------------------------- | --------------------------------------- |
| `organization.org_id`      | `product_vectors.org_id`                |
| `product.product_id`       | `product_vectors.product_id`            |
| `product.name`             | `product_vectors.name`                  |
| `product.price`            | `product_vectors.price`                 |
| `category.name` (join)     | `product_vectors.category` (string)     |
| —                          | `product_vectors.embedding` (vector)    |

প্রোডাক্ট টেক্সট থেকে embedding বানিয়ে আমরা `product_vectors` এ সেভ করি।

---

## ৩. Indexing: MySQL থেকে ডেটা কিভাবে আনা যায়

### অপশন A: NestJS থেকে প্রতিবার product create/update এ AI backend কে ডাকা (recommended)

- Admin/UI তে যখন একটা প্রোডাক্ট **create** বা **update** হয়, NestJS সেই মুহূর্তে আমাদের **index** API hit করবে।
- একটাই প্রোডাক্টের জন্য: `POST /api/v1/search/index`।

**Request body (index):**

```json
{
  "org_id": "3b7f6e51-1f00-4cff-a435-53364d0ed49c",
  "product_id": "prod-001",
  "name": "Budget Laptop",
  "category": "Electronics",
  "price": 299.99
}
```

- NestJS MySQL থেকে `product` + `category` (join) নিয়ে `org_id`, `product_id`, `name`, `category` (name), `price` আমাদের API তে পাঠাবে।
- আমাদের backend embedding বানিয়ে PostgreSQL `product_vectors` এ upsert করবে (ওই org_id + product_id এর জন্য)।

### অপশন B: বাল্ক সিন্ক (একবার বা নির্দিষ্ট সময়ে)

- NestJS একটা job/cron চালাবে: MySQL থেকে সব (অথবা একটা org এর সব) প্রোডাক্ট নিয়ে লুপে আমাদের **index** API কে এক একটা করে (অথবা batch endpoint থাকলে batch) ডাকবে।
- অথবা আমাদের FastAPI তে একটা **sync** endpoint বানানো যায় যেখানে NestJS সব প্রোডাক্ট JSON array পাঠাবে; আমরা লুপে index করব।

### অপশন C: আমাদের backend সরাসরি MySQL read করে (কম প্রচলিত)

- FastAPI তে MySQL connection + একটা script/endpoint: নির্দিষ্ট org এর product গুলো read করে আমাদের embedding + pgvector এ লিখে। এতে দুইটা DB এর সাথে এই সার্ভিসের coupling বাড়ে।

**সাধারণত অপশন A** — product create/update এ NestJS থেকে index API call — সবচেয়ে সহজ এবং রিয়েল-টাইম।

---

## ৪. Search / RAG: Org-based কিভাবে চালাবেন

- যেকোনো search (semantic বা RAG) এ **org_id** দিলে শুধু সেই org এর প্রোডাক্ট থেকে result আসবে।

**Direct endpoint:**

```http
POST /api/v1/search/rag
Content-Type: application/json

{
  "query": "cheap laptop",
  "org_id": "3b7f6e51-1f00-4cff-a435-53364d0ed49c"
}
```

- `org_id` optional: না দিলে সব org এর প্রোডাক্ট থেকে search হবে (multi-tenant না থাকলে এক org থাকলে সমস্যা নেই)।
- NestJS যেই org এর জন্য পেজ/ইউজার দেখাচ্ছে, সেই `org_id` GraphQL/context থেকে নিয়ে আমাদের API তে পাঠাবে।

---

## ৫. সংক্ষিপ্ত ফ্লো

1. **Index (MySQL → AI):**  
   Product create/update (MySQL) → NestJS → `POST /api/v1/search/index` with `org_id`, `product_id`, `name`, `category`, `price` (ও অন্যান্য optional ফিল্ড) → AI backend embedding বানিয়ে `product_vectors` এ upsert।

2. **Search/RAG:**  
   User query + `org_id` (NestJS থেকে) → `POST /api/v1/search/rag` with `query` + `org_id` → AI backend শুধু ওই org এর ভেক্টর search করে → RAG answer + sources।

---

## ৬. API সুমারি (org সহ)

| Endpoint              | Body (প্রাসঙ্গিক ফিল্ড)                                | ব্যবহার                                           |
| --------------------- | ------------------------------------------------------ | ------------------------------------------------- |
| POST /search/index    | org_id, product_id, name, category, price (+ optional) | একটা প্রোডাক্ট index (NestJS থেকে MySQL অনুযায়ী) |
| POST /search/rag      | query, org_id (optional)                               | RAG answer শুধু ওই org এর প্রোডাক্ট থেকে          |
| POST /search/semantic | query, org_id (optional)                               | Vector search শুধু ওই org এ                       |

---

## ৭. প্রথমবার সেটআপ

1. **PostgreSQL এ টেবিল:**  
   আগে যারা পুরনো `product_vectors` (শুধু product_id PK) use করছেন তারা একবার টেবিল ড্রপ করে নতুন স্কিম চালান।  
   নতুন ডিপ্লয় হলে শুধু:

   ```bash
   python scripts/init_db.py
   ```

   অথবা `scripts/init_db.sql` চালান। এতে `org_id` + `product_id` দিয়ে টেবিল তৈরি হবে।

2. **প্রোডাক্ট ডেটা:**  
   NestJS থেকে যেকোনো একটা org এর জন্য কয়েকটা প্রোডাক্ট index API দিয়ে ঢুকিয়ে নিন; তারপর ওই org_id দিয়ে RAG/semantic টেস্ট করুন।

এইভাবে MySQL এর org-based ডেটা দিয়ে indexing এবং search দুটোই চালানো যায়।
