# Data Models — ShopAssistantRAG

Authoritative entity definitions. MySQL is the system of record; Pinecone stores a derived vector + retrieval metadata. Source: BRD §5, stories E1-S1 / E2-S1 / E4-S2.

---

## 1. Enums

### Category
`Shoes | Clothing | Accessories | Sportswear | Bags` (exactly these five — E1-S1 AC-2).

### Gender
`Men | Women | Unisex | Kids` (exactly these four — E1-S1 AC-3).

---

## 2. Entity — Product  (system of record: MySQL `products`)

| Field | Type | Constraint | Notes |
|-------|------|-----------|-------|
| `product_id` | string | **PK**, unique, NOT NULL | Vector ID in Pinecone (1:1 map). |
| `name` | string | **NOT NULL** | Embedded. |
| `description` | text | nullable | Embedded. |
| `brand` | string | nullable | Embedded + Pinecone metadata. |
| `category` | enum(Category) | **NOT NULL** | Embedded + Pinecone metadata. |
| `gender` | enum(Gender) | nullable | Embedded + Pinecone metadata. |
| `color` | string | nullable | Embedded + Pinecone metadata. |
| `price` | decimal(10,2) | **NOT NULL**, ≥ 0 | INR. Pinecone metadata (numeric) for range filters. NOT embedded. |
| `image_url` | string | nullable | Display only. NOT embedded. |
| `stock` | integer | DEFAULT 0, ≥ 0 | `stock=0` ⇒ out of stock. NOT embedded. |
| `tags` | list[string] | nullable | Stored in MySQL as delimited/JSON; parsed to list. Embedded. |
| `in_stock` | boolean | **derived** | `stock > 0`. Not a stored column; computed on the model. |

**Validation rules (E1-S1):** missing `name`, `price`, or `category` → validation error. `stock=0` is valid and yields `in_stock=False`. `category`/`gender` outside the enum sets are rejected.

### MySQL DDL (sql/schema.sql — E2-S1)
```sql
CREATE TABLE IF NOT EXISTS products (
  product_id   VARCHAR(64)   NOT NULL,
  name         VARCHAR(255)  NOT NULL,
  description  TEXT          NULL,
  brand        VARCHAR(128)  NULL,
  category     VARCHAR(32)   NOT NULL,
  gender       VARCHAR(16)   NULL,
  color        VARCHAR(64)   NULL,
  price        DECIMAL(10,2) NOT NULL,
  image_url    VARCHAR(1024) NULL,
  stock        INT           NOT NULL DEFAULT 0,
  tags         JSON          NULL,
  PRIMARY KEY (product_id),
  CONSTRAINT chk_category CHECK (category IN ('Shoes','Clothing','Accessories','Sportswear','Bags')),
  CONSTRAINT chk_gender   CHECK (gender IS NULL OR gender IN ('Men','Women','Unisex','Kids')),
  CONSTRAINT chk_price    CHECK (price >= 0),
  CONSTRAINT chk_stock    CHECK (stock >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_products_category ON products (category);
CREATE INDEX idx_products_brand    ON products (brand);
CREATE INDEX idx_products_gender   ON products (gender);
CREATE INDEX idx_products_color    ON products (color);
CREATE INDEX idx_products_price    ON products (price);
```

**Indexes rationale:** `/api/products` and `/api/filters` filter/distinct on category, brand, gender, color, price (E7-S3, E8-S2). PK lookup serves bulk hydration (E5-S3).

### Example record
```json
{
  "product_id": "P1001",
  "name": "Nike Revolution 6",
  "description": "Lightweight everyday running shoes with soft foam cushioning.",
  "brand": "Nike",
  "category": "Shoes",
  "gender": "Men",
  "color": "Red",
  "price": 2799.00,
  "image_url": "https://cdn.example.com/p1001.jpg",
  "stock": 12,
  "tags": ["Running", "Sports"],
  "in_stock": true
}
```

---

## 3. Entity — QueryFilters  (in-memory; not persisted)

Produced by filter extraction (E5-S1), accumulated in session state (E6-S1), consumed by the retriever (E5-S2).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `brand` | string \| None | None | Pinecone `$eq` |
| `color` | string \| None | None | Pinecone `$eq` (normalized enum vocab) |
| `category` | enum(Category) \| None | None | Pinecone `$eq` |
| `gender` | enum(Gender) \| None | None | Pinecone `$eq` |
| `min_price` | number \| None | None | Pinecone `$gte` on price metadata |
| `max_price` | number \| None | None | Pinecone `$lte` on price metadata |

All fields optional, defaulting to `None` (E1-S1 AC-4). Out-of-vocab extracted values are dropped to `None` (E5-S1 AC-3).

### Example
```json
{ "brand": "Nike", "color": "Red", "category": "Shoes", "gender": null, "min_price": null, "max_price": 3000 }
```

---

## 4. Entity — Pinecone Vector Record  (derived index)

| Element | Type | Source | Notes |
|---------|------|--------|-------|
| `id` | string | `product_id` | 1:1 with MySQL PK (E4-S2 AC-1). |
| `values` | float[768] | Gemini `text-embedding-004` | From `build_embedding_text` (E3-S1). |
| `metadata.brand` | string | Product.brand | Equality filter. |
| `metadata.color` | string | Product.color | Equality filter. |
| `metadata.category` | string | Product.category | Equality filter. |
| `metadata.gender` | string | Product.gender | Equality filter. |
| `metadata.price` | number | Product.price | Numeric — `$gte`/`$lte` range (E4-S2 AC-4). |

Metadata holds **only** retrieval fields (BRD §5.3). Display fields are hydrated from MySQL. Upsert overwrites on existing ID (E4-S2 AC-3); batched for 500–1000 products (AC-5).

### Example
```json
{
  "id": "P1001",
  "values": [0.013, -0.082, "...768 floats..."],
  "metadata": { "brand": "Nike", "color": "Red", "category": "Shoes", "gender": "Men", "price": 2799.00 }
}
```

---

## 5. Entity — SessionState  (in-memory only; per active session — E6-S1)

| Field | Type | Notes |
|-------|------|-------|
| `session_id` | string | Key. |
| `filters` | QueryFilters | Accumulating; reset to empty on category change / explicit reset. |
| `history` | list[Turn] | Bounded to last N turns (no unbounded growth — AC-5). |
| `last_category` | enum(Category) \| None | Used to detect category change → reset (E6-S3 AC-3). |

### Turn
| Field | Type | Notes |
|-------|------|-------|
| `role` | string | `user` \| `assistant`. |
| `message` | string | Turn text. |

Not persisted across restarts (E6-S1 AC-4). Session isolation guaranteed (AC-2).

---

## 6. Entity — Ingestion Summary  (transient; printed report — E3-S3)

| Field | Type | Notes |
|-------|------|-------|
| `total_processed` | int | Rows read from CSV. |
| `successful` | int | Upserted to MySQL + Pinecone. |
| `failed` | int | Skipped rows + embedding failures. |
| `failures` | list[FailureRecord] | `{ row_id, reason }`. |

---

## 7. Relationships

```
products (MySQL, 1) ──────1:1────── Pinecone vector (id = product_id)
QueryFilters (transient) ── consumed by ─→ HybridRetriever ──→ product_id[] ──→ hydrate ──→ products
SessionState (1) ── holds 1 ─→ QueryFilters ;  holds N ─→ Turn
```
