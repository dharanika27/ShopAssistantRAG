# Session Memory & Query State Manager Design — ShopAssistantRAG

The conversational core's state substrate — the highest-risk area (BRD R-1). Source: BRD §8, stories E6-S1, E6-S3.

---

## 1. Goals & Constraints

- **Accumulating filter state** across turns ("Nike shoes" → "only red ones" → "cheaper") — BRD §8.1.
- **Rebuild fresh retrieval each turn** from the accumulated `QueryFilters` — never re-filter the prior result list (D-4, E6-S3 AC-1).
- **Session isolation**: one session's state never affects another (E6-S1 AC-2).
- **In-memory only**, active session — no cross-session persistence, lost on restart (E6-S1 AC-4, BRD §6.3).
- **Bounded history** so long sessions don't grow unbounded (E6-S1 AC-5).
- Low concurrency → a process-local dict is sufficient; **Redis would be over-engineering** (D-2).

---

## 2. Data Structures

```
SessionStore                      # process-global singleton
  sessions: dict[str, SessionState]   # key = session_id

SessionState
  session_id:    str
  filters:       QueryFilters         # accumulating; reset to empty on category change / explicit reset
  history:       deque[Turn]          # bounded (maxlen = N, e.g. 10)
  last_category: Category | None      # used to detect category change → reset

Turn
  role:    "user" | "assistant"
  message: str
```

`QueryFilters` = `{ brand, color, category, gender, min_price, max_price }`, all optional, default `None` (E1-S1 AC-4).

---

## 3. Query State Manager — Operations

| Method | Behavior |
|--------|----------|
| `get_or_create(session_id)` | Returns the session's state; creates an empty one on first contact (AC-1). |
| `merge_or_reset(session_id, extracted: QueryFilters)` | Core transition (see §4). Returns the **effective** filters for this turn. |
| `reset(session_id)` | Clears `filters` to empty, clears `last_category` (explicit "forget previous search"). |
| `append_turn(session_id, role, message)` | Pushes a `Turn`; deque drops the oldest beyond `maxlen` (AC-5). |
| `lower_price_ceiling(session_id)` | "cheaper" rule — reduces `max_price` and re-runs (BRD §8.2). |

Session isolation (AC-2) is guaranteed because each `session_id` maps to an independent `SessionState`; no shared mutable filter object across sessions.

---

## 4. Merge-or-Reset Decision Logic (E6-S3)

The single most important rule set (risk R-1, BRD §8.3).

```
def merge_or_reset(session_id, extracted):
    state = get_or_create(session_id)

    # (a) Explicit reset intent ("forget previous search") -> hard reset
    if reset_intent_detected:                       # E6-S3 AC-3
        state.filters = QueryFilters()              # empty
        state.last_category = None

    # (b) Clear category change ("Now show me bags") -> reset, then apply new category
    elif extracted.category and state.last_category and extracted.category != state.last_category:
        state.filters = QueryFilters(category=extracted.category)   # drop brand/color/gender
        state.last_category = extracted.category

    # (c) Refinement -> MERGE non-None extracted fields onto existing filters
    else:                                            # E6-S3 AC-1
        for field in ("brand","color","category","gender","min_price","max_price"):
            v = getattr(extracted, field)
            if v is not None:
                setattr(state.filters, field, v)
        if extracted.category:
            state.last_category = extracted.category

    # (d) "cheaper" -> lower the price ceiling (BRD §8.2, E6-S3 AC-2)
    if cheaper_intent_detected:
        state.filters.max_price = lower(state.filters.max_price, current_results_floor)

    return state.filters    # effective filters -> HybridRetriever (fresh query)
```

| Intent | Trigger | Effect |
|--------|---------|--------|
| Refine / accumulate | "only red ones", "any Adidas alternatives", price tweak | Merge non-None fields onto existing filters. |
| Cheaper | "cheaper options", "anything less expensive" | Reduce `max_price`, re-run retrieval. |
| Category change | "Now show me bags", "show me accessories" | Reset filters, keep only the new category. |
| Explicit reset | "forget previous search", "start over" | Empty filters and history-derived state. |
| Greeting / small talk | "hi", "what can you do" | No retrieval; scoped conversational reply (E6-S3 AC-5). |
| Invalid ("asdfgh") | extraction yields nothing meaningful | Clarification reply; no retrieval. |

Intent detection is driven by the FilterExtractor's structured output plus light keyword rules in the orchestrator (e.g., "cheaper", "forget"/"start over"). This keeps the logic testable with mocked Gemini (E9-S1 AC-4).

---

## 5. Lifecycle

```
Browser session start  -> Streamlit generates stable session_id (uuid) in st.session_state (E8-S3 AC-3)
First /api/chat        -> QueryStateManager.get_or_create(session_id)  -> empty state
Each turn              -> merge_or_reset -> retrieve(fresh) -> hydrate -> generate -> append_turn(user), append_turn(assistant)
App restart            -> all sessions lost (in-memory only, AC-4)
```

No eviction policy is required for the demo, but an optional TTL/LRU cap on the number of concurrent sessions can be added without changing the interface (scalability hook, BRD NFR-6) — not implemented in MVP to avoid over-engineering.

---

## 6. Testing Hooks (E9-S1 AC-4)

- Construct two sessions, mutate one, assert the other is unchanged (isolation).
- Turn 1 sets `{brand:Nike,category:Shoes}`; turn 2 "only red ones" → assert merged `{brand:Nike,category:Shoes,color:Red}`.
- "Now show me bags" → assert filters reset to `{category:Bags}`.
- "cheaper options" → assert `max_price` decreased.
- All with Gemini/Pinecone/MySQL mocked.
