# Business Requirements Document — ShopAssistantRAG

| Field | Value |
|-------|-------|
| **Project** | Shop Assistant RAG Chatbot |
| **Document** | Business Requirements Document (BRD) |
| **Author** | Dharanika |
| **Date** | 2026-06-02 |
| **Status** | Approved — ready for Spec phase |
| **Version** | 1.0 |

---

## 1. Executive Summary

ShopAssistantRAG is a **conversational AI shopping assistant** that helps users discover products through natural language instead of traditional keyword search. The system grounds every answer in a real product catalog using a **Retrieval-Augmented Generation (RAG)** pipeline: user queries are converted into structured filters and semantic vectors, matched against a product catalog in Pinecone, and answered by Google Gemini using only retrieved products (no hallucination).

This is a **portfolio and learning project** demonstrating production-style RAG, hybrid vector search, and LLM orchestration in an e-commerce context. It is explicitly **not** a production e-commerce platform — there is no cart, checkout, payment, or order management.

---

## 2. Problem Statement & Goals (Why)

### 2.1 Problem
Traditional keyword search forces shoppers to guess exact terms and cannot interpret intent like *"affordable red running shoes for women."* This project demonstrates a conversational alternative where shoppers describe what they want in plain language and receive relevant, catalog-grounded recommendations.

### 2.2 Project Type
Portfolio + learning project to demonstrate hands-on skill with RAG, vector databases, embeddings, and LLM integration. Primary audience for the *artifact* is recruiters/interviewers evaluating GenAI skills; primary *user* of the app is a shopper.

### 2.3 Goals & Success Metrics
| # | Success Metric |
|---|----------------|
| SM-1 | A user can ask natural-language shopping questions and receive relevant product recommendations from the catalog. |
| SM-2 | The RAG pipeline retrieves relevant products from Pinecone and generates contextual responses via Gemini. |
| SM-3 | The full stack runs end-to-end locally (FastAPI + Streamlit + MySQL + Pinecone + Gemini). |

### 2.4 Technical Targets
- Support **500–1000 products**
- **Response time < 5 seconds**
- **Top 5** relevant products returned per query
- End-to-end hybrid RAG workflow functioning correctly

### 2.5 Motivation
Build demonstrable GenAI development skills (RAG, Gemini, Pinecone, FastAPI, Streamlit, vector databases) for interviews and professional growth.

---

## 3. Scope (What)

### 3.1 Feature Priority
1. **AI Shopping Assistant** — *primary* interaction method.
2. **Product Catalog Display** — *secondary*; visual grid browsing.

Both features read from the same product dataset.

### 3.2 In-Scope Features (MVP)
| ID | Feature | Description |
|----|---------|-------------|
| F-1 | Product catalog grid | Visual grid of product cards (image, name, brand, category, price, stock status). |
| F-2 | Traditional filters | Filter catalog by Brand, Category, Gender, Price Range, Color. |
| F-3 | Conversational AI assistant | Natural-language product discovery via chat. |
| F-4 | Conversational filtering | Assistant translates NL ("women's products under ₹3000") into retrieval criteria. |
| F-5 | Semantic retrieval | Hybrid retrieval: structured metadata pre-filter + semantic vector search in Pinecone. |
| F-6 | RAG answer generation | Gemini generates a grounded NL response + product cards. |
| F-7 | Multi-turn session memory | Accumulating filter state across turns ("only red ones" → "cheaper"). |
| F-8 | No-match / grounding handling | Friendly message + category suggestions when nothing matches; no hallucinated products. |
| F-9 | Data ingestion pipeline | Standalone script: CSV → MySQL → Gemini embeddings → Pinecone upsert. |

### 3.3 Out of Scope (Deferred)
User registration, login/authentication, user profiles, shopping cart, wishlist, checkout, payment integration, order management/history, product reviews, product ratings, behavioral recommendations, real-time inventory synchronization, multi-language support, push notifications, external e-commerce integrations, vendor management, analytics dashboard, admin UI, ingestion API, pagination/"show more".

---

## 4. Users & Flows (Who & How)

### 4.1 Personas
| Persona | Role | Needs |
|---------|------|-------|
| **Shopper** (primary) | End user discovering products | Ask NL questions, browse grid, filter, refine results conversationally. |
| **Developer/Admin** (secondary) | Loads catalog & embeddings | Run ingestion scripts. No dedicated UI in MVP. |

### 4.2 Primary User Flow
1. User opens the Streamlit application.
2. Views the product catalog grid.
3. Optionally filters products via UI controls.
4. Asks the chatbot a natural-language question.
5. Assistant extracts filters → hybrid retrieval from Pinecone → hydrate from MySQL.
6. Gemini generates a grounded NL response.
7. Product cards + NL message are displayed; user refines across turns.

### 4.3 Data Ingestion Flow (Admin)
```
CSV File → MySQL Product Table → Gemini Embeddings → Pinecone Upsert
```
- **MySQL is the system of record.**
- Pinecone stores embeddings + retrieval metadata.
- Ingestion is via standalone script (no admin UI, no ingestion API).

### 4.4 Retrieval Flow
```
User Query → Filter Extraction (Gemini) → Pinecone Metadata Filter + Vector Search
          → Product IDs → Fetch full records from MySQL → Return to user
```

---

## 5. Data Model

### 5.1 Product Attributes
| Field | Type | Notes |
|-------|------|-------|
| Product ID | string/int (PK) | Unique identifier. |
| Product Name | string | **Required.** |
| Description | text | Used in embedding. |
| Brand | string | e.g., Nike, Adidas, Puma. |
| Category | enum | **Required.** Shoes, Clothing, Accessories, Sportswear, Bags (extensible). |
| Gender | enum | Men, Women, Unisex, Kids. |
| Color | string | Single primary color (MVP): Red, Black, Blue, White, … |
| Price | decimal | **Required.** INR (₹), e.g., 2999.00. |
| Image URL | string | Display only; not embedded. |
| Stock | integer | Quantity; stock=0 shown as "out of stock"; no inventory enforcement. |
| Tags | list/string | Keywords (Running, Casual, Sports, Formal, Sneaker) to boost retrieval. |

### 5.2 Enums
- **Gender**: Men, Women, Unisex, Kids
- **Category**: Shoes, Clothing, Accessories, Sportswear, Bags

### 5.3 Embedding Strategy
- **One embedding per product**, generated from: Name + Description + Brand + Category + Gender + Color + Tags.
- **Not embedded** (kept as Pinecone metadata): Price, Stock, Image URL.
- Example embedding text: *"Nike Air Zoom running shoes for men. Black sports shoes designed for running and fitness. Category Shoes. Tags Running, Sports."*

---

## 6. Technical Architecture & Constraints

### 6.1 Tech Stack
| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit |
| Backend API | FastAPI |
| Database (source of truth) | MySQL |
| Vector store | Pinecone (768-dim index) |
| Embeddings | Google Gemini `text-embedding-004` (768-dim) |
| Generation | Google Gemini `gemini-1.5-flash` |
| Orchestration | LangChain |

### 6.2 Gemini Usage
- **Embeddings**: `text-embedding-004`, 768 dimensions (Pinecone index dimension must match 768).
- **Generation**: `gemini-1.5-flash` (low latency, low cost; target <5s).
- **Filter extraction**: Gemini structured JSON output, e.g.:
```json
{ "brand": "Nike", "color": "Red", "category": "Shoes", "max_price": 3000 }
```

### 6.3 LangChain Orchestration
```
User Query → LangChain → Filter Extraction → Pinecone Retrieval
          → Context Assembly → Gemini Generation → Response
```
Responsibilities: retriever chain management, Pinecone + Gemini integration, prompt construction, context injection, session conversation memory (active session only — no cross-session persistence).

### 6.4 Retrieval Strategy — Hybrid
1. Extract structured filters from query.
2. Apply Pinecone metadata filters (brand, color, category, price).
3. Execute semantic vector search on remaining intent.
4. Return top-5 ranked products, hydrated from MySQL.

### 6.5 Configuration & Secrets
- All secrets via `.env` (gitignored). No secrets committed.
- Required: `GOOGLE_API_KEY`, `PINECONE_API_KEY`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`.

### 6.6 Deployment
- **Dev mode (manual)**: `uvicorn backend.main:app --reload` + `streamlit run frontend/app.py` + local MySQL.
- **Demo mode**: `docker-compose up` — FastAPI + Streamlit + MySQL containers; Gemini + Pinecone remain external cloud services.

### 6.7 Modular Architecture
Clear separation: Frontend · API · Services · Retrieval · Database · Embedding pipeline.

---

## 7. Non-Functional Requirements (Prioritized)

| Rank | NFR | Requirement |
|------|-----|-------------|
| 1 | **Modular architecture** | Clean separation of frontend, API, services, retrieval, database, embedding pipeline. |
| 2 | **Clean RAG pipeline** | Query → Retrieval → Context → Generation, easily understandable to reviewers. |
| 3 | **Error handling** | Graceful failures for Gemini, Pinecone, and database errors; never expose stack traces. |
| 4 | **Logging** | Structured logs for retrieval operations, API requests, embedding generation. |
| 5 | **Unit testing** | Critical-path coverage with external services mocked. |
| 6 | **Scalability** | Design allows future scaling without over-engineering the MVP. |

### Performance & Scale
500–1000 products · <5s response · low concurrency (single user / small-group demos). No large-scale production optimization required.

---

## 8. Multi-Turn Conversation Behavior

### 8.1 Accumulating Filter State
The assistant maintains a **session-level query state object** and rebuilds a fresh hybrid retrieval on each turn (does **not** merely filter the previous result list).

```
"Show me Nike shoes"  → { brand: Nike, category: Shoes }
"Only red ones"       → { brand: Nike, category: Shoes, color: Red }
"Cheaper options"     → { brand: Nike, category: Shoes, color: Red, price_adjustment: lower }
```

### 8.2 "Cheaper" Rule
"Cheaper" = reduce the current upper price ceiling and re-run retrieval for lower-priced alternatives.

### 8.3 Context Reset Rules
- **Reset** on: clear category change ("Now show me bags", "Show me accessories") or explicit reset ("Forget previous search").
- **Continue/accumulate** on: refinements ("Only black ones", "Cheaper options", "Any Adidas alternatives?").

---

## 9. Edge Cases & Failure Handling

### 9.1 Service Failures (log + user-friendly message; never expose internals)
| Failure | User Message |
|---------|--------------|
| Gemini unavailable | "The AI assistant is temporarily unavailable. Please try again in a few moments." |
| Pinecone unavailable | "Product search is temporarily unavailable. Please try again later." |
| MySQL unavailable | "We are unable to load product details right now. Please try again later." |

### 9.2 Query Edge Cases
| Case | Behavior |
|------|----------|
| Empty result set | Friendly no-match + suggest available categories. |
| Out-of-catalog category ("laptops") | No-match + category suggestions. |
| Invalid query ("asdfgh") | Ask for clarification. |
| Greetings / small talk | Conversational scoped response explaining capabilities. |
| Price-only ("under ₹500") | Valid — apply price filter + semantic retrieval. |

### 9.3 Ingestion Data Quality
| Case | Behavior |
|------|----------|
| Missing required field (Name, Price, Category) | Skip row, log validation failure, continue. |
| Duplicate Product ID | Upsert (update existing). |
| Embedding failure | Log failed product, continue, include in summary. |
| Every run | Produce summary: total processed, successful, failed, failure reasons. |

---

## 10. Acceptance Criteria (Definition of Done)

With ~500–1000 seeded products, the MVP is complete when:

1. User opens the Streamlit application.
2. User can browse a product catalog grid.
3. Product cards show image, name, brand, category, price, stock status.
4. User can filter by Brand, Category, Gender, Price Range, Color (correct results).
5. User can submit natural-language product queries (e.g., "Show me red Nike shoes under ₹3000").
6. System returns an NL response + up to 5 matching product cards, grounded in the catalog.
7. Response time remains < 5 seconds.
8. User can refine results across turns ("only red ones", "cheaper options", "show Adidas alternatives").
9. System correctly maintains session context (accumulating filter state).
10. Unsupported / unavailable products produce graceful no-match responses.
11. The entire application runs via `docker-compose up`.
12. Critical-path unit tests pass.
13. Integration tests pass.
14. No blocking errors exist in the core user journey.

---

## 11. Risks & Mitigations

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R-1 | **Multi-turn query refinement** — context tracking, query state, query rewriting, session memory. | Highest | Explicit filter-state object; context-aware retrieval that rebuilds queries; reset rules. |
| R-2 | **Filter extraction reliability** — wrong Gemini JSON, enum mismatches (Crimson→Red, Trainers→Shoes), ambiguous wording. | High | Validation layer; enum normalization; structured-output enforcement. |
| R-3 | **Retrieval relevance** — poor embedding text, weak metadata filtering, irrelevant ranking. | High | Hybrid retrieval; rich embedding content; metadata pre-filtering; retrieval evaluation testing. |

---

## 12. Assumptions

1. Single-deployment demo application (not multi-tenant).
2. Product discovery and recommendation only — no cart, checkout, payment, or orders.
3. Catalog seeded manually via CSV / DB scripts (no external e-commerce integration).
4. Single currency: INR (₹).
5. Low-concurrency, demo-level workload.
6. No corporate/external secret-management constraints.

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **RAG** | Retrieval-Augmented Generation — grounding LLM responses in retrieved data. |
| **Hybrid retrieval** | Combining structured metadata filtering with semantic vector search. |
| **Embedding** | Numeric vector representation of product text for semantic search. |
| **Grounding** | Constraining generated answers to actual catalog data (no hallucination). |
| **Session memory** | Conversation context retained only for the active session. |
