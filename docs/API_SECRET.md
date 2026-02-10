# API_SECRET: API Key Authentication

This document describes how API key authentication works. **API_SECRET is required** - all Search API endpoints require authentication. Clients must send the correct headers; otherwise protected endpoints return **401 Unauthorized**.

---

## Overview

- **API_SECRET** is a **required** server-side secret (in `.env`). All protected Search API endpoints require authentication.
- API keys are **derived**, not stored:  
  **Key = HMAC-SHA256(API_SECRET, user_input)** → 64-character hex string.
- The client sends **which input** it is using (`X-Key-Input`) and the **key** (`X-API-Key`). The server recomputes the key and compares; no database of keys is needed.

---

## Architecture: NestJS + FastAPI Workflow

**Typical setup:**

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Client    │────────▶│   NestJS     │────────▶│   FastAPI   │
│  (Frontend) │         │  (Backend)   │         │ (AI Search) │
└─────────────┘         └──────────────┘         └─────────────┘
                              │
                              │ Has API_SECRET
                              │ Computes master key
                              │ Calls /generate-key
                              │ Gets org-specific keys
                              │ Returns to client
```

**Flow:**

1. **NestJS backend** e same `API_SECRET` thake (FastAPI er moto `.env` e)
2. **NestJS** master key compute kore: `HMAC(API_SECRET, "generate")`
3. **NestJS** FastAPI `/generate-key` endpoint call kore (master key diye) → org-specific key paay
4. **NestJS** client ke org-specific key diye dey
5. **Client** direct FastAPI Search endpoints call kore (org-specific key diye)

**Benefits:**

- Master key **shudhu NestJS backend** e thake (client ke jana na)
- Client ke **org-specific key** diye dewa jay (per-org isolation)
- FastAPI e **kono key store** kora lagena (HMAC derive kore)

---

## Configuration

In `.env`:

```env
# Required: server-side secret. Search API requires X-Key-Input + X-API-Key on all protected routes.
API_SECRET=your-secret-string
```

- **Required:** All Search endpoints require valid `X-Key-Input` + `X-API-Key` (or `Authorization: Bearer <key>`).
- **Must be set:** Application will fail to start if `API_SECRET` is missing.

Restart the app after changing `API_SECRET`.

---

## How Keys Are Generated

```
api_key = HMAC-SHA256(API_SECRET, user_input).hexdigest()
```

- **user_input:** Any string you choose, e.g. `org_id`, `tenant_123`, or a custom identifier.
- **token** (in `/generate-key` response): 64-character lowercase hex string (e.g. for org `org_abc` you get one token, for `org_xyz` another).

Same `API_SECRET` + same `user_input` → same key every time. Different input → different key.

---

## Headers for Protected Endpoints

| Header            | Required | Description                                                                                                                   |
| ----------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **X-Key-Input**   | Yes      | The “user input” the key was generated from (e.g. `org_id`). Server computes expected key as `HMAC(API_SECRET, X-Key-Input)`. |
| **X-API-Key**     | Yes\*    | The API key: `HMAC-SHA256(API_SECRET, X-Key-Input).hexdigest()`.                                                              |
| **Authorization** | Optional | Alternative: `Authorization: Bearer <api_key>`. Same key as `X-API-Key`.                                                      |

\* Either `X-API-Key` or `Authorization: Bearer <key>` must be present.

Example:

```http
X-Key-Input: org_abc123
X-API-Key: a1b2c3d4e5f6...（64 hex chars）
```

---

## Special Value: List All (X-Key-Input = \*)

For **list indexed** endpoints, you can use a special key that allows “list all orgs”:

- **X-Key-Input:** `*`
- **X-API-Key:** `HMAC-SHA256(API_SECRET, "*").hexdigest()`

Only this combination is accepted for the “list all” behaviour when you want to avoid filtering by a specific org.

---

## Generate-Key Endpoint (Get Keys for Your Inputs)

To get an API key for a given input (e.g. for an org), call:

**POST** `/api/v1/search/generate-key`

This endpoint itself is protected by a **master key**:

- **X-Key-Input:** `generate`
- **X-API-Key:** `HMAC-SHA256(API_SECRET, "generate").hexdigest()`

**Request body:**

```json
{
  "input": "org_abc123"
}
```

**Response:**

```json
{
  "input": "org_abc123",
  "token": "a1b2c3d4e5f6..."
}
```

Use that `token` with **X-Key-Input: org_abc123** (and **X-API-Key:** that value) when calling other Search endpoints for that org.

You can call `/generate-key` once per org/tenant and give the key to the client that will use it.

---

## Which Endpoints Require Auth (when API_SECRET is set)

| Endpoint                      | Method | Auth                                                                       |
| ----------------------------- | ------ | -------------------------------------------------------------------------- |
| `/api/v1/search/generate-key` | POST   | Master key: `X-Key-Input: generate` + key = HMAC(API_SECRET, `"generate"`) |
| `/api/v1/search/indexed`      | GET    | X-Key-Input + X-API-Key (or `*` for list-all key)                          |
| `/api/v1/search/indexed/list` | POST   | Same as above                                                              |
| `/api/v1/search/index`        | POST   | X-Key-Input + X-API-Key (per-org key)                                      |
| `/api/v1/search/semantic`     | POST   | Same                                                                       |
| `/api/v1/search/rag`          | POST   | Same                                                                       |
| `/api/v1/search/debug`        | GET    | Same                                                                       |

**Note:** All these endpoints require authentication. `API_SECRET` must be configured in `.env`.

---

## Example: Compute Master Key (to Call generate-key)

**PowerShell (Windows):**

```powershell
$secret = "your-api-secret"
$input = "generate"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($input)
$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$hash = $hmac.ComputeHash($bytes)
$masterKey = [BitConverter]::ToString($hash).Replace("-","").ToLower()
Write-Host $masterKey
```

**Python (one-off):**

```python
import hmac, hashlib
API_SECRET = "your-api-secret"
master_key = hmac.new(API_SECRET.encode("utf-8"), b"generate", hashlib.sha256).hexdigest()
print(master_key)
```

**Node.js (plain – master key + org key):**

```javascript
const crypto = require("crypto");

const API_SECRET = process.env.API_SECRET || "your-api-secret";

// Key = HMAC-SHA256(API_SECRET, input) → 64-char hex
function generateKey(input) {
  return crypto.createHmac("sha256", API_SECRET).update(input).digest("hex");
}

// Master key (দিয়ে FastAPI /generate-key call করবেন)
const masterKey = generateKey("generate");
console.log("Master key:", masterKey);

// কোনো org এর key সরাসরি (FastAPI call না করে)
const orgId = "38e7d815-fd80-4a86-b124-835b17eb6227";
const orgKey = generateKey(orgId);
console.log("Org key:", orgKey);
```

**Node.js থেকে FastAPI `/generate-key` call (master key দিয়ে):**

```javascript
const crypto = require("crypto");

const API_SECRET = process.env.API_SECRET || "your-api-secret";
const FASTAPI_URL = process.env.FASTAPI_URL || "http://localhost:8000";

function getMasterKey() {
  return crypto
    .createHmac("sha256", API_SECRET)
    .update("generate")
    .digest("hex");
}

async function getKeyForOrg(orgId) {
  const res = await fetch(`${FASTAPI_URL}/api/v1/search/generate-key`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Key-Input": "generate",
      "X-API-Key": getMasterKey(),
    },
    body: JSON.stringify({ input: orgId }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.token;
}

// ব্যবহার
getKeyForOrg("38e7d815-fd80-4a86-b124-835b17eb6227").then((apiKey) =>
  console.log(apiKey)
);
```

**NestJS/TypeScript (Backend Service):**

```typescript
import * as crypto from "crypto";

// In your NestJS service (e.g. SearchKeyService)
export class SearchKeyService {
  private readonly API_SECRET: string; // From your NestJS .env (same as FastAPI API_SECRET)

  constructor() {
    this.API_SECRET = process.env.API_SECRET || "";
  }

  /**
   * Generate master key to call /generate-key endpoint
   * Master key = HMAC-SHA256(API_SECRET, "generate")
   */
  private generateMasterKey(): string {
    const hmac = crypto.createHmac("sha256", this.API_SECRET);
    hmac.update("generate");
    return hmac.digest("hex"); // 64-char lowercase hex
  }

  /**
   * Generate API key for a specific org/input
   * Calls FastAPI /generate-key endpoint
   */
  async generateKeyForOrg(orgId: string): Promise<string> {
    const masterKey = this.generateMasterKey();
    const fastApiUrl = process.env.FASTAPI_URL || "http://localhost:8000";

    const response = await fetch(`${fastApiUrl}/api/v1/search/generate-key`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Key-Input": "generate",
        "X-API-Key": masterKey,
      },
      body: JSON.stringify({ input: orgId }),
    });

    if (!response.ok) {
      throw new Error(`Failed to generate key: ${response.statusText}`);
    }

    const data = await response.json();
    return data.token; // Return this token to your client for that org
  }

  /**
   * Generate API key directly (without calling FastAPI)
   * Useful if you want to compute it locally
   */
  generateKeyForInput(input: string): string {
    const hmac = crypto.createHmac("sha256", this.API_SECRET);
    hmac.update(input);
    return hmac.digest("hex");
  }
}
```

**Usage in NestJS Controller:**

```typescript
@Controller("search-keys")
export class SearchKeyController {
  constructor(private readonly searchKeyService: SearchKeyService) {}

  @Post("generate/:orgId")
  async generateKey(@Param("orgId") orgId: string) {
    // Generate key for this org and return to client
    const apiKey = await this.searchKeyService.generateKeyForOrg(orgId);
    return { org_id: orgId, token: apiKey };
  }
}
```

**Important:**

- NestJS backend e **same `API_SECRET`** thakte hobe (FastAPI er `.env` er moto)
- Master key ta **backend e compute** kore `/generate-key` call korbe
- Client ke **org-specific key** diye dibe (master key na)

**cURL – generate key for org (after you have master key):**

```bash
curl -X POST "http://localhost:8000/api/v1/search/generate-key" \
  -H "Content-Type: application/json" \
  -H "X-Key-Input: generate" \
  -H "X-API-Key: YOUR_MASTER_KEY" \
  -d "{\"input\": \"org_abc123\"}"
```

**PowerShell – same request:**

```powershell
$masterKey = "YOUR_MASTER_KEY"
$body = '{"input":"org_abc123"}'
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/search/generate-key" `
  -Method POST -ContentType "application/json" `
  -Headers @{"X-Key-Input"="generate"; "X-API-Key"=$masterKey} `
  -Body $body
```

---

## Example: Call a Protected Endpoint (e.g. semantic search)

After you have a `token` for `org_abc123` from `/generate-key`:

```bash
curl -X POST "http://localhost:8000/api/v1/search/semantic" \
  -H "Content-Type: application/json" \
  -H "X-Key-Input: org_abc123" \
  -H "X-API-Key: API_KEY_FOR_ORG_ABC123" \
  -d "{\"query\": \"laptop\", \"org_id\": \"org_abc123\"}"
```

---

## Error Responses

| Status                        | When                                                              |
| ----------------------------- | ----------------------------------------------------------------- |
| **401 Unauthorized**          | Missing or wrong `X-Key-Input` / `X-API-Key` (or Bearer token).   |
| **500 Internal Server Error** | Application startup fails if `API_SECRET` is missing from `.env`. |

Error body example:

```json
{
  "detail": "Invalid or missing API key"
}
```

or

```json
{
  "detail": "Missing X-Key-Input header (e.g. org_id). API key is generated from this input."
}
```

---

## Security Notes

1. **Keep API_SECRET secret** – only on the server (e.g. `.env`), never in client code or in git.
2. **HTTPS in production** – so headers (and keys) are not sent in clear text.
3. **One key per org/tenant** – use `input` = org_id (or tenant id); each client gets only the key for its org.
4. **Master key** – only use `X-Key-Input: generate` and the HMAC(API_SECRET, `"generate"`) key on a secure backend that generates keys for clients; do not expose the master key to end users or frontends.
5. **Constant-time comparison** – the server uses `hmac.compare_digest()` so timing does not leak key information.

---

## Quick Reference

| Goal                             | X-Key-Input    | X-API-Key                                  |
| -------------------------------- | -------------- | ------------------------------------------ |
| Call `/generate-key`             | `generate`     | HMAC(API_SECRET, `"generate"`).hexdigest() |
| Call other endpoints for one org | e.g. `org_abc` | HMAC(API_SECRET, `"org_abc"`).hexdigest()  |
| List all (indexed)               | `*`            | HMAC(API_SECRET, `"*"`).hexdigest()        |

All keys are **64-character lowercase hex** strings (SHA-256 output in hex).

### NestJS Workflow Summary

1. **NestJS `.env`:** `API_SECRET=your-secret` (same as FastAPI)
2. **Compute master key:** `crypto.createHmac('sha256', API_SECRET).update('generate').digest('hex')`
3. **Call FastAPI `/generate-key`:** Use master key to get org-specific keys
4. **Return to client:** Give org-specific key (not master key) to frontend/client
5. **Client calls FastAPI:** Uses org-specific key directly on Search endpoints

---

## Generate Key কি? (সহজ ব্যাখ্যা)

- **Key generate** মানে: আপনার একটা **input** (যেমন `org_abc123`) দিলে server একটা **64 অক্ষরের API key** বানিয়ে দেয়।
- এই key দিয়েই পরবর্তীতে **search API** (semantic, index, rag ইত্যাদি) call করবেন।
- Key **store করা হয় না** – প্রতিবার একই `API_SECRET` + একই input দিলে একই key পাওয়া যায় (HMAC দিয়ে derive)।

**দুই ধাপ:**

1. **Master key** বানাও (শুধু একবার, আপনার `.env` এর `API_SECRET` দিয়ে) → এই key দিয়ে **শুধু** `/generate-key` call করবে।
2. **`/generate-key`** call করে **org-specific key** নাও (যেমন `org_abc123` এর জন্য) → এই key দিয়ে বাকি সব Search API use করবে।

---

## Node.js থেকে Key জেনারেট করার দুটো সহজ উপায়

### ১. সরাসরি key বানানো (কোনো API call নেই)

আপনার Node.js/NestJS প্রজেক্টে **API_SECRET** একই রাখুন (FastAPI এর `.env` এর মতো)। তারপর:

```javascript
const crypto = require("crypto");

const API_SECRET = process.env.API_SECRET; // same as FastAPI .env

function generateKey(input) {
  return crypto.createHmac("sha256", API_SECRET).update(input).digest("hex");
}

// Master key (শুধু /generate-key call করার জন্য)
const masterKey = generateKey("generate");

// যেকোনো org এর key (বাকি Search API এর জন্য)
const orgId = "38e7d815-fd80-4a86-b124-835b17eb6227";
const orgKey = generateKey(orgId);
```

- **Master key** = `generateKey("generate")` → দিয়ে শুধু FastAPI এর `POST /api/v1/search/generate-key` call করবেন।
- **Org key** = `generateKey(orgId)` → এই key + `X-Key-Input: <orgId>` দিয়ে semantic/index/rag সব call করবেন।

### ২. FastAPI এর `/generate-key` Node.js থেকে call করা

অর্থাৎ আগে master key বানিয়ে, সেই key দিয়ে FastAPI কে বলবেন “এই org এর key দাও”:

```javascript
const crypto = require("crypto");

const API_SECRET = process.env.API_SECRET;
const FASTAPI_URL = process.env.FASTAPI_URL || "http://localhost:8000";

function getMasterKey() {
  return crypto
    .createHmac("sha256", API_SECRET)
    .update("generate")
    .digest("hex");
}

async function getKeyForOrg(orgId) {
  const res = await fetch(`${FASTAPI_URL}/api/v1/search/generate-key`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Key-Input": "generate",
      "X-API-Key": getMasterKey(),
    },
    body: JSON.stringify({ input: orgId }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.token;
}

// ব্যবহার
getKeyForOrg("38e7d815-fd80-4a86-b124-835b17eb6227").then((apiKey) =>
  console.log(apiKey)
);
```

**NestJS** use করলে উপরের **Example: Compute Master Key** সেকশনে যে **NestJS/TypeScript (Backend Service)** উদাহরণ আছে, সেটা দিয়েই একই কাজ করা যায়: ওখানে `generateMasterKey()` আর `generateKeyForOrg(orgId)` / `generateKeyForInput(input)` দিয়ে Node.js থেকেই key generate করছেন।

---

## Postman এ কিভাবে কাজ করবেন (Step-by-Step)

### ধাপ ১: Master Key বানানো

Postman key **generate** করে না; key আপনাকে **বাইরে** বানাতে হবে (নিচের যেকোনো একটা দিয়ে)।

**Option A – Python (সবচেয়ে সহজ):**

টার্মিনালে একবার চালান (আপনার `.env` এর `API_SECRET` দিন):

```bash
python -c "import hmac, hashlib; s='YOUR_API_SECRET'; print(hmac.new(s.encode(), b'generate', hashlib.sha256).hexdigest())"
```

যেমন `API_SECRET=mysecret123` হলে:

```bash
python -c "import hmac, hashlib; s='mysecret123'; print(hmac.new(s.encode(), b'generate', hashlib.sha256).hexdigest())"
```

যে **64-character hex string** আউটপুট আসবে সেটাই আপনার **Master Key**। একে কপি করে রাখুন।

**Option B – PowerShell (Windows):**

```powershell
$secret = "mysecret123"   # আপনার API_SECRET
$input = "generate"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($input)
$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$hash = $hmac.ComputeHash($bytes)
$masterKey = [BitConverter]::ToString($hash).Replace("-","").ToLower()
Write-Host $masterKey
```

---

### ধাপ ২: Postman এ `/generate-key` call করা

1. **New Request** খুলুন।
2. **Method:** `POST`
3. **URL:** `http://localhost:8000/api/v1/search/generate-key` (বা আপনার FastAPI base URL)
4. **Headers** ট্যাবে যান এবং যোগ করুন:

   | Key          | Value                                   |
   | ------------ | --------------------------------------- |
   | Content-Type | application/json                        |
   | X-Key-Input  | `generate`                              |
   | X-API-Key    | _(ধাপ ১ এ যে Master Key পেয়েছেন সেটা)_ |

5. **Body** ট্যাবে:

   - **raw** সিলেক্ট করুন
   - **JSON** সিলেক্ট করুন
   - লিখুন:

   ```json
   {
     "input": "org_abc123"
   }
   ```

   (যে org id দিয়ে পরবর্তীতে search করবেন সেটা দিন।)

6. **Send** চাপুন।

**Response উদাহরণ:**

```json
{
  "input": "org_abc123",
  "token": "a1b2c3d4e5f6..."
}
```

এই **`token`** টাই হলো সেই org এর জন্য key। একে কপি করে রাখুন।

---

### ধাপ ৩: Postman এ Search API (যেমন semantic) call করা

এখন এই **org key** দিয়ে যেকোনো protected endpoint call করবেন।

1. আরেকটা **New Request** খুলুন।
2. **Method:** `POST`
3. **URL:** `http://localhost:8000/api/v1/search/semantic`
4. **Headers:**

   | Key          | Value                                                      |
   | ------------ | ---------------------------------------------------------- |
   | Content-Type | application/json                                           |
   | X-Key-Input  | `org_abc123` _(যে input দিয়ে generate-key call করেছিলেন)_ |
   | X-API-Key    | _(ধাপ ২ এ পাওয়া `token`)_                                 |

5. **Body** (raw, JSON):

   ```json
   {
     "query": "laptop",
     "org_id": "org_abc123"
   }
   ```

6. **Send** চাপুন।

এভাবে **index**, **rag**, **indexed** ইত্যাদি endpoint এও একই ভাবে **X-Key-Input** = সেই org id আর **X-API-Key** = সেই org এর key দিলেই কাজ করবে।

---

```json
const crypto = require("crypto");

const API_SECRET = process.env.API_SECRET;
const FASTAPI_URL = process.env.FASTAPI_URL || "http://localhost:8000";

function getMasterKey() {
 return crypto.createHmac("sha256", API_SECRET).update("generate").digest("hex");
}

async function getKeyForOrg(orgId) {
 const res = await fetch(`${FASTAPI_URL}/api/v1/search/generate-key`, {
   method: "POST",
   headers: {
     "Content-Type": "application/json",
     "X-Key-Input": "generate",
     "X-API-Key": getMasterKey(),
   },
   body: JSON.stringify({ input: orgId }),
 });
 if (!res.ok) throw new Error(await res.text());
 const data = await res.json();
 return data.token;
}
```

### Postman এ এক নজরে

| আপনি কি করছেন         | URL                            | X-Key-Input  | X-API-Key      |
| --------------------- | ------------------------------ | ------------ | -------------- |
| Org এর key নেওয়া     | `POST .../search/generate-key` | `generate`   | Master Key     |
| Semantic search করা   | `POST .../search/semantic`     | `org_abc123` | ঐ org এর token |
| Index / RAG / indexed | respective endpoint            | `org_abc123` | ঐ org এর token |

**সারাংশ:** আগে একবার Master Key বানিয়ে Postman এ দিয়ে `/generate-key` call করুন → response থেকে org এর `token` নিন → সেই token + সেই org id দিয়ে বাকি সব Search API Postman এ call করুন।
