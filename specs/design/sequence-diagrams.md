# Sequence Diagrams — ShopAssistantRAG

Implementation-ready interaction flows for the critical paths. Actors/components match `system-design.md` and `component-map.md`. Source: BRD §4.3/§4.4/§8, stories E3-S3, E5-*, E6-*, E7-*.

---

## 1. Chat turn — happy path (hybrid retrieval + grounded generation)

`POST /api/chat` → grounded reply + ≤5 product cards. This is the core RAG journey (E6-S3, E7-S2).

```
Streamlit      FastAPI         Chat            Filter         Query          Hybrid         Hydrator        Answer
 (frontend)    /api/chat     Orchestrator    Extractor      StateMgr       Retriever      (MySQL)        Generator
    |  POST {session_id,msg}  |                |              |              |              |               |
    |------------------------>|                |              |              |              |               |
    |                         | chat(sid,msg)  |              |              |              |               |
    |                         |--------------->|              |              |              |               |
    |                         |                | extract(msg) |              |              |               |
    |                         |                |------------->| Gemini JSON + normalize     |               |
    |                         |                |<-------------| QueryFilters (partial)      |               |
    |                         |                | merge_or_reset(sid, filters)|              |               |
    |                         |                |---------------------------->| accumulate / reset           |
    |                         |                |<----------------------------| effective QueryFilters       |
    |                         |                | retrieve(query, filters)    |              |               |
    |                         |                |---------------------------------------->| Pinecone:         |
    |                         |                |                             |   filter + vector search    |
    |                         |                |<----------------------------------------| ≤5 ranked IDs     |
    |                         |                | hydrate(ids)               |              |               |
    |                         |                |------------------------------------------------------->| MySQL
    |                         |                |                             |              |   get_products_by_ids
    |                         |                |<-------------------------------------------------------| Products (rank order)
    |                         |                | generate(msg, products)    |              |               |
    |                         |                |------------------------------------------------------------------->| Gemini flash
    |                         |                |<-------------------------------------------------------------------| grounded reply
    |                         |<---------------| {reply, products[≤5]}      |              |               |
    |  200 {reply, products}  |                |              |              |              |               |
    |<------------------------|                |              |              |              |               |
    |  render reply + cards   |                |              |              |              |               |
```

Latency budget (<5s, BRD §2.4 / E7-S2 AC-5): filter-extract (Gemini) ~0.8s + Pinecone query ~0.3s + MySQL hydrate ~0.05s + generation (Gemini flash) ~1.5s + overhead. Comfortably under 5s.

---

## 2. Multi-turn refinement (accumulate) — "only red ones"

Demonstrates state accumulation and **fresh retrieval rebuild** (not re-filtering prior results — BRD §8.1, R-1, E6-S3 AC-1).

```
Turn 1: "Show me Nike shoes"
  FilterExtractor -> {brand:Nike, category:Shoes}
  QueryStateMgr   -> state.filters = {brand:Nike, category:Shoes}; last_category=Shoes
  Retriever       -> Pinecone filter {brand=Nike, category=Shoes} + vector  -> IDs
  -> reply + cards

Turn 2: "only red ones"   (same session_id)
  FilterExtractor -> {color:Red}                       (partial)
  QueryStateMgr   -> NOT a category change -> MERGE
                     state.filters = {brand:Nike, category:Shoes, color:Red}
  Retriever       -> REBUILD fresh Pinecone query with full accumulated filter set
  -> reply + narrowed cards
```

---

## 3. Multi-turn "cheaper options" (price ceiling adjustment)

E6-S3 AC-2 / BRD §8.2: lower the upper price ceiling and re-run.

```
State before: {brand:Nike, category:Shoes, color:Red, max_price: <current/derived>}
User: "cheaper options"
  ChatOrchestrator detects price-down intent (via FilterExtractor / rule)
  QueryStateMgr.max_price := reduced ceiling (e.g., min(current results' price floor, prior max * factor))
  Retriever -> rebuild with $lte max_price -> lower-priced Nike red shoes
  -> reply + cheaper cards
```

---

## 4. Context reset — category change / explicit reset

E6-S3 AC-3 / BRD §8.3.

```
State before: {brand:Nike, category:Shoes, color:Red}
User: "Now show me bags"   OR   "forget previous search"
  FilterExtractor -> {category:Bags}   (or reset intent)
  QueryStateMgr   -> category changed (Shoes -> Bags)  => RESET
                     state.filters = {category:Bags}   (drop brand/color)
                     last_category = Bags
  Retriever -> fresh query for Bags
  -> reply + bag cards
```

---

## 5. No-match path (grounded, no hallucination)

E6-S3 AC-4 / E6-S2 AC-3 / BRD §9.2.

```
ChatOrchestrator -> retrieve -> Pinecone returns []  (filters excluded all vectors, E5-S2 AC-5)
                 -> hydrate([]) -> [] (no MySQL query, E5-S3 AC-4)
                 -> AnswerGenerator.generate(msg, [])  -> friendly no-match + category suggestions
                 -> {reply:"...we carry Shoes, Clothing, Accessories, Sportswear, Bags...", products:[]}
```

---

## 6. Service-failure path (graceful degradation)

BRD §9.1 / E7-S1 AC-4 / E6-S2 AC-5. Typed errors map to user messages in middleware.

```
Streamlit --POST /api/chat--> FastAPI --> ChatOrchestrator --> HybridRetriever --> PineconeClient
                                                                                       | raises
                                                                                       v
                                                                          RetrievalError (typed)
   <-- 503 {error:{code:PINECONE_UNAVAILABLE, message:"Product search is temporarily unavailable..."}}
   (error middleware maps typed error -> envelope; no stack trace, BRD NFR-3)
```

Mapping: `EmbeddingError`/`GenerationError` → `GEMINI_UNAVAILABLE` (503); `RetrievalError` → `PINECONE_UNAVAILABLE` (503); `RepositoryError` → `MYSQL_UNAVAILABLE` (503); validation → 422; anything else → `INTERNAL_ERROR` (500).

---

## 7. Ingestion pipeline (batch, standalone CLI)

E3-S3 / BRD §4.3. Embedding failures are non-fatal; a summary is printed.

```
scripts/ingest.py
  -> CSVLoader.load(csv)            -> (valid_products[], failures[])      (E2-S3)
  for batch in valid_products:
     -> ProductRepository.upsert_product(p)      -> MySQL (system of record, E2-S2)
     -> build_embedding_text(p)                  -> text (E3-S1)
     -> GeminiEmbeddingClient.embed_batch(texts) -> 768-dim vectors (E3-S2)
            | on embedding failure: log + record failure, skip from Pinecone, CONTINUE
     -> PineconeClient.upsert_products(products, vectors, metadata)  (E4-S2, batched)
  -> print Ingestion Summary {total_processed, successful, failed, failures[]}   (E3-S3 AC-4)
  Re-run = idempotent upsert (no duplicates in MySQL or Pinecone, E3-S3 AC-5)
```

---

## 8. Catalog browse + traditional filters

E7-S3 / E8-S1 / E8-S2.

```
Streamlit on load -> GET /api/filters -> ProductRepository (distinct brand/category/gender/color + price min/max)
                                       -> {brands, categories, genders, colors, price_range}
User selects filters -> GET /api/products?brand=&category=&...&min_price=&max_price=
                     -> ProductRepository.list_products(filters) -> Product[] (200, [] if none)
                     -> grid re-renders
```
