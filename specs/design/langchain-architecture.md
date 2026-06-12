# LangChain Architecture — ShopAssistantRAG

How LangChain orchestrates the RAG pipeline: retriever chain, Pinecone + Gemini integration, prompt construction, context injection, and session memory. Source: BRD §6.3/§6.4, stories E5-S1, E5-S2, E6-S1, E6-S2, E6-S3.

---

## 1. Orchestration Overview

LangChain wires **retrieval → context assembly → generation**. It does *not* own the session store (that is the in-process `QueryStateManager`, design D-2) — LangChain components are invoked per turn with the already-resolved `QueryFilters`.

```
User Query
   │
   ▼
FilterExtractor (LLM structured output)      ──►  QueryFilters (normalized)
   │
   ▼
QueryStateManager.merge_or_reset             ──►  effective QueryFilters
   │
   ▼
HybridRetriever  (LangChain Retriever)       ──►  ≤5 product_ids (rank-ordered)
   │   ├─ Pinecone metadata filter ($eq / $gte / $lte)
   │   └─ semantic vector search (cosine, top_k=5)
   ▼
Hydrator (MySQL get_products_by_ids)         ──►  Product[] (rank-preserving)
   │
   ▼
Context Assembly (prompt template)           ──►  grounded prompt
   │
   ▼
AnswerGenerator (Groq llama-3.3-70b-versatile)           ──►  grounded NL reply
   │
   ▼
{ reply, products[≤5] }
```

---

## 2. Component → LangChain Mapping

| Pipeline component | LangChain primitive | Module |
|--------------------|---------------------|--------|
| Gemini embeddings | `GoogleGenerativeAIEmbeddings` (model `text-embedding-004`, 768-dim) | `backend/services/embedding_client.py` |
| LLM generation | Groq client (model `llama-3.3-70b-versatile`, `LLM_PROVIDER`-selectable; Gemini legacy) | `backend/services/answer_generator.py` |
| Filter extraction | LLM + structured-output parser (`PydanticOutputParser` / JSON parser over `QueryFilters`) | `backend/services/filter_extractor.py` |
| Hybrid retrieval | Custom `BaseRetriever` wrapping `PineconeVectorStore` with `search_kwargs={"filter": ..., "k": 5}` | `backend/services/hybrid_retriever.py` |
| Prompt construction | `ChatPromptTemplate` + `prompts/*.txt` | `backend/prompts/` |
| Chain wiring | LCEL (`prompt | llm | parser`) for extraction and generation chains | service modules |
| Session memory | **Not** LangChain memory — custom `QueryStateManager` (filter-state, not raw transcript) | `backend/services/query_state.py` |

> Note: Session memory is deliberately a custom accumulating **filter-state** object, not LangChain `ConversationBufferMemory`. BRD §8.1 requires rebuilding a fresh structured retrieval from accumulated filters each turn, which a raw chat-buffer memory does not model. This is design decision D-4.

---

## 3. Chains

### 3.1 Filter-Extraction Chain (E5-S1)

```
filter_extraction_prompt (prompts/filter_extraction.txt)
   | Groq(llama-3.3-70b-versatile, response as JSON)
   | JSON/Pydantic parser -> raw filters
   | normalize_enums()      # Crimson->Red, Trainers->Shoes; drop out-of-vocab -> None (R-2)
   -> QueryFilters
```

- Structured-output enforcement; malformed/non-JSON → empty `QueryFilters` (E5-S1 AC-5), never crash.
- Normalization layer maps synonyms onto canonical `Category`/`Gender`/color vocab and discards unknowns (E5-S1 AC-2/AC-3).

### 3.2 Hybrid Retrieval Chain (E5-S2)

```
HybridRetriever.retrieve(query_text, query_filters):
   query_vec = embedding_client.embed_text(query_text)      # 768-dim
   pinecone_filter = build_pinecone_filter(query_filters)   # $eq + $gte/$lte
   results = vectorstore.similarity_search_by_vector(
       query_vec, k=5, filter=pinecone_filter)
   return [r.id for r in results]    # rank-ordered, ≤5
```

Single Pinecone round-trip (D-3). Empty filter set → pure semantic; over-restrictive filters → `[]` (no-match path, AC-5).

### 3.3 Grounded Generation Chain (E6-S2)

```
answer_generation_prompt (prompts/answer_generation.txt)
   context = format_products(hydrated_products)   # name, brand, category, price, color, stock...
   | Groq(llama-3.3-70b-versatile)
   -> grounded NL reply
```

- Prompt instructs: **use only the supplied products**; never invent products/prices/attributes (E6-S2 AC-1/AC-2, grounding).
- Empty context → friendly no-match + category suggestions, not invented products (E6-S2 AC-3).

---

## 4. Prompt Construction & Context Injection

| Prompt file | Purpose | Key instructions |
|-------------|---------|------------------|
| `prompts/filter_extraction.txt` | NL → structured filters | Output strict JSON for `QueryFilters`; only use the known Category/Gender/color/brand vocabulary; omit unknowns. |
| `prompts/answer_generation.txt` | Grounded reply | "Recommend ONLY from the products below. If the list is empty, say nothing matched and suggest categories: Shoes, Clothing, Accessories, Sportswear, Bags. Never invent products, prices, or stock." |

Context injected into generation is the **hydrated `Product[]`** (rank-ordered), formatted as a compact list. No external knowledge is permitted into the answer (grounding / anti-hallucination, BRD glossary, R-3).

---

## 5. Integration Points & Settings

- Both Gemini chains read model names and `GOOGLE_API_KEY` from centralized settings (E1-S2), never hardcoded (E5-S1/E6-S2 reference E3-S2 AC-4).
- The Pinecone vector store is constructed from the shared `PineconeClient` (E4-S1) so the index handle is reused.
- All LLM calls are wrapped to raise **typed errors** (`EmbeddingError`, `GenerationError`) on SDK failure (E3-S2 AC-3, E6-S2 AC-5) → mapped to BRD user messages in API middleware.

---

## 6. Testability (E9-S1)

- Each chain is a discrete service with the LLM/vector store injected → tests substitute mocks (no live Gemini/Pinecone).
- FilterExtractor tested by feeding canned model JSON and asserting normalization.
- HybridRetriever tested by asserting the constructed Pinecone `filter` dict and `k=5` against a mocked store.
- AnswerGenerator tested by asserting the prompt contains only supplied products and the empty-context branch returns the no-match message.
