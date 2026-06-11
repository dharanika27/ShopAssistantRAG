# Pinecone Index Design — ShopAssistantRAG

Vector store design for hybrid retrieval. Pinecone is a **derived index** (MySQL is the system of record). Source: BRD §5.3/§6.2/§6.4, stories E4-S1, E4-S2, E5-S2.

---

## 1. Index Configuration

| Property | Value | Rationale |
|----------|-------|-----------|
| Index name | `PINECONE_INDEX_NAME` (env, default e.g. `shopassistant-products`) | Configurable (E1-S2). |
| Dimension | **768** | Must match Gemini `text-embedding-004` output (E4-S1 AC-2/AC-3). Mismatch is rejected as config error. |
| Metric | **cosine** | Text-embedding semantic similarity (E4-S1 AC-2). |
| Vector count | 500–1000 | BRD §2.4 scale. Single namespace, no sharding needed. |
| Namespace | default (single) | Single-tenant demo (BRD §12). |
| Pod/Serverless | Serverless (recommended) | Low/idle traffic demo; cost-efficient. |

Provisioning is **idempotent**: if the index exists with the right dimension/metric, reuse it; otherwise create it (E4-S1 AC-2). Connection failure → typed `RetrievalError` (E4-S1 AC-4).

---

## 2. Vector Record Schema

One vector per product, keyed by `product_id` (1:1 with MySQL PK → enables hydration). E4-S2.

```json
{
  "id": "P1001",
  "values": [0.013, -0.082, "…768 floats…"],
  "metadata": {
    "brand": "Nike",
    "color": "Red",
    "category": "Shoes",
    "gender": "Men",
    "price": 2799.00
  }
}
```

### Metadata fields (retrieval-only)

| Field | Type | Filter operator | Notes |
|-------|------|-----------------|-------|
| `brand` | string | `$eq` | equality pre-filter |
| `color` | string | `$eq` | normalized enum vocab (E5-S1) |
| `category` | string | `$eq` | one of the 5 enum values |
| `gender` | string | `$eq` | one of the 4 enum values |
| `price` | **number** | `$gte` / `$lte` | numeric so range filters work (E4-S2 AC-4) |

**Excluded from metadata** (hydrated from MySQL instead): `description`, `image_url`, `stock`, `tags`, `name`. Keeping metadata minimal keeps the index small and forces a single source of truth for display data (BRD §5.3, design decision D-1).

---

## 3. Embedding Source Text

The vector `values` are produced by `build_embedding_text(product)` (E3-S1) → Gemini `text-embedding-004`. Composed from **Name + Description + Brand + Category + Gender + Color + Tags**. Price, stock, image_url are **not** embedded (E3-S1 AC-2).

Example embedding text: *"Nike Revolution 6. Lightweight everyday running shoes with soft foam cushioning. Brand Nike. Category Shoes. For Men. Color Red. Tags Running, Sports."*

---

## 4. Hybrid Query Construction (E5-S2)

A **single** Pinecone `query` call combines the metadata pre-filter and the semantic vector search (design decision D-3 — one round-trip for <5s budget).

```python
index.query(
    vector=query_embedding,          # 768-dim embedding of the user's intent text
    top_k=5,                          # at most 5 IDs (E5-S2 AC-4)
    include_metadata=True,
    filter=build_pinecone_filter(query_filters)
)
```

### Filter builder (`QueryFilters` → Pinecone filter)

```python
{
  "brand":    {"$eq": filters.brand}       if filters.brand    else (omitted),
  "color":    {"$eq": filters.color}       if filters.color    else (omitted),
  "category": {"$eq": filters.category}    if filters.category else (omitted),
  "gender":   {"$eq": filters.gender}      if filters.gender   else (omitted),
  "price":    { "$gte": min_price?, "$lte": max_price? }   (only the bounds that are set)
}
```

- Equality filters: `brand`, `color`, `category`, `gender` (E5-S2 AC-1).
- Range filters: `min_price`→`$gte`, `max_price`→`$lte` on `price` (E5-S2 AC-2).
- Omit any `None` filter entirely (no empty `$eq`).
- Price-only query: only the `price` range clause is present — pure semantic + price (BRD §9.2).
- If metadata excludes all vectors → empty result → no-match path (E5-S2 AC-5), no error.

Results are returned ordered by similarity score; the orchestrator keeps that rank order through hydration (E5-S3 AC-2).

---

## 5. Upsert Strategy (E4-S2)

- Vector ID = `product_id` → re-upsert overwrites (no duplicates, AC-3).
- **Batched** upserts (e.g., 100/batch) so 500–1000 products load in one ingestion run without exceeding request size limits (AC-5).
- Embeddings produced via `embed_batch` for throughput (E3-S2 AC-2).
- A product whose embedding fails is skipped from upsert, logged, and counted in the ingestion summary (E3-S3 AC-3).

---

## 6. Consistency & Reconciliation

| Concern | Approach |
|---------|----------|
| MySQL ↔ Pinecone drift | Re-run ingestion (idempotent upsert) reconciles both from the CSV seed. |
| ID in Pinecone but not MySQL | Hydrator skips + logs that ID; request still succeeds (E5-S3 AC-3). |
| Index loss / rebuild | Rebuild entirely from MySQL/CSV via ingestion — Pinecone holds no unique source data. |
| Dimension mismatch | Rejected at provisioning (E4-S1 AC-3); index dim is pinned to 768. |
