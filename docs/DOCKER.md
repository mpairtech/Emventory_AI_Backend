# Docker দিয়ে চালানো

## আপনার pgvector Postgres আলাদা জায়গায় চালু

আপনি ইতিমধ্যে এইভাবে postgres চালাচ্ছেন:

```yaml
postgres:
  image: pgvector/pgvector:pg16
  container_name: pgvector_db
  environment:
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: sAkawat321
    POSTGRES_DB: Search
  ports:
    - "5433:5432"
  volumes:
    - pgvector_data:/var/lib/postgresql/data
```

এই প্রজেক্ট (AI Search Backend) শুধু **app** চালাবে এবং ওই Postgres এ কানেক্ট করবে।

---

## ১. .env সেট করা

প্রজেক্ট রুটে `.env` বানান (অথবা `.env.example` কপি করে পূরণ করুন):

```env
# আপনার pgvector_db — host থেকে পোর্ট 5433
DB_HOST=host.docker.internal
DB_PORT=5433
DB_NAME=Search
DB_USER=postgres
DB_PASSWORD=sAkawat321

GEMINI_API_KEY=your_gemini_api_key
LOG_LEVEL=INFO
```

- **Windows/Mac:** App Docker এ চালালে Postgres host এ থাকলে `DB_HOST=host.docker.internal`, `DB_PORT=5433`।
- **Linux:** `DB_HOST=172.17.0.1` বা host এর IP, `DB_PORT=5433`।
- **একই Docker network:** postgres ও app একই network এ থাকলে `DB_HOST=pgvector_db`, `DB_PORT=5432`।

---

## ২. এই প্রজেক্ট চালানো (docker-compose)

```bash
docker compose up -d
```

অ্যাপ: **http://localhost:5000**

প্রথমবার টেবিল বানাতে (একবার):

```bash
docker compose exec app python scripts/init_db.py
```

পুরনো টেবিলে org_id থাকলে না থাকলে মাইগ্রেশন:

```bash
docker compose exec app python scripts/migrate_add_org_id.py
```

---

## ৩. শুধু docker run দিয়ে (compose ছাড়া)

```bash
docker build -t emventory-ai-backend .
docker run -p 5000:5000 --env-file .env emventory-ai-backend
```

Init DB / মাইগ্রেশন:

```bash
docker run --rm --env-file .env emventory-ai-backend python scripts/init_db.py
docker run --rm --env-file .env emventory-ai-backend python scripts/migrate_add_org_id.py
```

---

## ৪. সংক্ষেপে

| কাজ                                 | কমান্ড                                                         |
| ----------------------------------- | -------------------------------------------------------------- |
| অ্যাপ চালু (আপনার Postgres এর সাথে) | `docker compose up -d`                                         |
| টেবিল বানানো (প্রথমবার)             | `docker compose exec app python scripts/init_db.py`            |
| org_id মাইগ্রেশন                    | `docker compose exec app python scripts/migrate_add_org_id.py` |
| বন্ধ                                | `docker compose down`                                          |

`.env` এ `DB_NAME=Search`, `DB_PORT=5433` এবং পাসওয়ার্ড ঠিক থাকলে এই প্রজেক্ট আপনার pgvector_db তেই কানেক্ট করবে।
