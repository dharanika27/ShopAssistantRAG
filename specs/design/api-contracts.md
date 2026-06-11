# API Contracts — ShopAssistantRAG

Base URL (dev): `http://localhost:8000`  ·  All paths prefixed `/api`.
Content-Type: `application/json`. No authentication (BRD §3.3 — auth out of scope). CORS allows the Streamlit origin (`http://localhost:8501`).

**Rate limits:** none enforced (low-concurrency demo, BRD §7). Single-user/small-group workload.

**Canonical field names** (must match mockups and data models): `product_id, name, description, brand, category, gender, color, price, image_url, stock, tags, in_stock`. Chat: `session_id, message, reply, products`. Filters: `brand, category, gender, color, min_price, max_price`.

---

## Error Envelope (all non-2xx, except 422 validation)

```json
{
  "error": {
    "code": "GEMINI_UNAVAILABLE",
    "message": "The AI assistant is temporarily unavailable. Please try again in a few moments."
  }
}
```

| `code` | HTTP | User message (BRD §9.1) |
|--------|------|--------------------------|
| `GEMINI_UNAVAILABLE` | 503 | The AI assistant is temporarily unavailable. Please try again in a few moments. |
| `PINECONE_UNAVAILABLE` | 503 | Product search is temporarily unavailable. Please try again later. |
| `MYSQL_UNAVAILABLE` | 503 | We are unable to load product details right now. Please try again later. |
| `VALIDATION_ERROR` | 422 | FastAPI default validation body (field-level detail). |
| `INTERNAL_ERROR` | 500 | An unexpected error occurred. Please try again later. (no stack trace) |

Stack traces are **never** present in any response body (BRD NFR-3).

---

## 1. `GET /api/health`  (E7-S1)

Liveness/readiness probe.

- **Request:** no params, no body.
- **Auth:** none.
- **200 Response:**
```json
{ "status": "ok", "service": "shopassistant-backend", "version": "1.0" }
```

---

## 2. `POST /api/chat`  (E7-S2)

Primary RAG entry point. Runs the full conversational turn.

- **Headers:** `Content-Type: application/json`
- **Request body:**
```json
{ "session_id": "a3f1c2...", "message": "Show me red Nike shoes under ₹3000" }
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `session_id` | string | yes | non-empty; stable per browser session |
| `message` | string | yes | non-empty (empty/missing → 422) |

- **200 Response:**
```json
{
  "reply": "Here are some red Nike shoes under ₹3000 you might like…",
  "products": [
    {
      "product_id": "P1001",
      "name": "Nike Revolution 6",
      "description": "Lightweight running shoes…",
      "brand": "Nike",
      "category": "Shoes",
      "gender": "Men",
      "color": "Red",
      "price": 2799.00,
      "image_url": "https://…/p1001.jpg",
      "stock": 12,
      "in_stock": true,
      "tags": ["Running", "Sports"]
    }
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `reply` | string | Grounded NL message (or friendly no-match/clarification message) |
| `products` | array | 0–5 hydrated `Product` objects, retrieval-rank order |

- **Behavior:** Distinct `session_id` values keep independent state (AC-3). No-match → friendly `reply` + `products: []` (AC-4 of E6-S3). Greetings/small talk/invalid → scoped `reply`, `products: []`. Target latency < 5s (AC-5).
- **422:** missing/empty `message` or `session_id`.
- **503:** downstream Gemini/Pinecone/MySQL failure → mapped error envelope (AC-6).

---

## 3. `GET /api/products`  (E7-S3)

Catalog listing with optional structured filters. Source: MySQL.

- **Query params (all optional):**

| Param | Type | Notes |
|-------|------|-------|
| `brand` | string | exact match |
| `category` | string (enum) | Shoes\|Clothing\|Accessories\|Sportswear\|Bags |
| `gender` | string (enum) | Men\|Women\|Unisex\|Kids |
| `color` | string | exact match |
| `min_price` | number | inclusive lower bound |
| `max_price` | number | inclusive upper bound |

- **200 Response:** array of `Product` objects (same shape as in chat `products`). No matches → `[]` with 200 (AC-4). `stock=0` → `in_stock: false` (AC-5).
```json
[ { "product_id": "P1001", "name": "Nike Revolution 6", "brand": "Nike", "category": "Shoes", "gender": "Men", "color": "Red", "price": 2799.00, "image_url": "https://…", "stock": 12, "in_stock": true, "description": "…", "tags": ["Running"] } ]
```
- **422:** `category`/`gender` not in enum, or non-numeric price.

---

## 4. `GET /api/filters`  (E7-S3)

Distinct filter option values for populating UI controls. Source: MySQL.

- **Request:** no params.
- **200 Response:**
```json
{
  "brands": ["Nike", "Adidas", "Puma"],
  "categories": ["Shoes", "Clothing", "Accessories", "Sportswear", "Bags"],
  "genders": ["Men", "Women", "Unisex", "Kids"],
  "colors": ["Red", "Black", "Blue", "White"],
  "price_range": { "min": 199.00, "max": 14999.00 }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `brands` | string[] | distinct brand values present in catalog |
| `categories` | string[] | distinct categories present |
| `genders` | string[] | distinct genders present |
| `colors` | string[] | distinct colors present |
| `price_range` | object | `{min, max}` numeric, for the price slider |

---

## Endpoint ↔ Story map

| Endpoint | Story |
|----------|-------|
| `GET /api/health` | E7-S1 |
| `POST /api/chat` | E7-S2 |
| `GET /api/products` | E7-S3 |
| `GET /api/filters` | E7-S3 |
