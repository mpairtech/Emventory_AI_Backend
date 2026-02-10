# pgvector এ কী সেভ আছে — কিভাবে চেক করবেন

## ১. API দিয়ে চেক (সবচেয়ে সহজ)

**GET** `/api/v1/search/indexed`

- সব indexed product এর তালিকা পাবেন (org_id, product_id, name, category, price — embedding নেই)।
- **Query params (optional):**
  - `org_id` — শুধু ওই org এর product দেখাবে।
  - `limit` — কতগুলো row (default 100, max 500)।

**উদাহরণ:**

```http
GET http://127.0.0.1:8000/api/v1/search/indexed
GET http://127.0.0.1:8000/api/v1/search/indexed?org_id=38e7d815-fd80-4a86-b124-835b17eb6227
GET http://127.0.0.1:8000/api/v1/search/indexed?org_id=38e7d815-fd80-4a86-b124-835b17eb6227&limit=20
```

**Response:**

```json
{
  "total": 5,
  "org_id_filter": "38e7d815-fd80-4a86-b124-835b17eb6227",
  "items": [
    {
      "org_id": "38e7d815-fd80-4a86-b124-835b17eb6227",
      "product_id": "26001",
      "name": "sdbggfj",
      "category": "df",
      "price": 5.0
    },
    ...
  ]
}
```

Swagger এ গিয়ে **GET /api/v1/search/indexed** দিয়ে Try out করলেই দেখতে পারবেন।

---

## ২. PostgreSQL (psql) দিয়ে চেক

DB এ সরাসরি কুয়েরি চালাতে চাইলে:

```bash
psql -U your_user -d your_db
```

**কয়েকটা দরকারি কুয়েরি:**

```sql
-- কতগুলো product index করা আছে
SELECT COUNT(*) FROM product_vectors;

-- org অনুযায়ী কতগুলো
SELECT org_id, COUNT(*) AS product_count
FROM product_vectors
GROUP BY org_id
ORDER BY product_count DESC;

-- সব product (embedding ছাড়া) — সামান্য sample
SELECT org_id, product_id, name, category, price
FROM product_vectors
ORDER BY org_id, product_id
LIMIT 50;

-- একটা নির্দিষ্ট org এর product
SELECT org_id, product_id, name, category, price
FROM product_vectors
WHERE org_id = '38e7d815-fd80-4a86-b124-835b17eb6227';

-- embedding আছে কিনা (dimension check) — শুধু একটা row
SELECT org_id, product_id, array_length(embedding::real[], 1) AS embedding_dim
FROM product_vectors
LIMIT 1;
```

---

## ৩. সংক্ষেপে

| কী চেক করবেন                          | কিভাবে                                                                                                          |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| সব / একটা org এর indexed product list | **GET** `/api/v1/search/indexed` বা `/api/v1/search/indexed?org_id=...`                                         |
| DB তে কত row / org অনুযায়ী কত        | psql এ `SELECT COUNT(*)`, `GROUP BY org_id`                                                                     |
| একটা product index হয়েছে কিনা        | GET indexed এ `org_id` + list দেখে product_id match করুন, অথবা psql এ `WHERE org_id = ... AND product_id = ...` |

embedding ভ্যালু সাধারণত API তে দেখানো হয় না (বড় array)। শুধু metadata (org_id, product_id, name, category, price) দিয়েই চেক করলেই হয়।
