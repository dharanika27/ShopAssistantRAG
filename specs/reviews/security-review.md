# Security Review — ShopAssistantRAG — Story Group E — 2026-06-12

Reviewer: Security Reviewer (automated scan + manual context read)
Scope: files changed in story group E (`git diff` vs HEAD) plus the group's core
implementation files.

Files reviewed:
- backend/services/chat_orchestrator.py (primary change)
- backend/services/query_state.py
- backend/services/answer_generator.py
- backend/prompts/answer_generation.txt
- backend/services/llm_provider.py, backend/services/groq_client.py (prompt sink)
- backend/api/routes/chat.py, backend/api/schemas.py (input boundary)
- backend/api/main.py, backend/api/middleware.py (edge/CORS/headers)
- backend/repositories/product_repository.py (SQL sink)
- backend/core/config.py, .env.example (secrets)
- docker-compose.yml
- tests/unit/test_chat_orchestrator.py
- frontend/components/placeholders.py (SSRF image guard, recent hardening)

## Summary
- BLOCK findings: 0
- WARN findings: 3
- INFO findings: 5
- Overall verdict: WARN (no merge blockers; three weaknesses should be addressed)

No BLOCK-level findings. SQL access is fully parameterized, secrets are loaded
from environment via `SecretStr` (no hardcoded credentials in code or tests), the
image-URL SSRF guard is correctly implemented, and `.env` is gitignored and not
tracked. The residual risks are prompt-injection hardening, unbounded user input,
and demo-grade exposure/observability defaults.

---

## BLOCK Findings

None.

---

## WARN Findings

### [VULN-001] LLM prompt injection via unescaped user query
File: backend/services/answer_generator.py line 76-80 (`_build_prompt`) and
backend/prompts/answer_generation.txt line 18 (`Customer query: {{QUERY}}`)
Severity: WARN
Description: The raw user `message` is substituted directly into the
`{{QUERY}}` placeholder of the generation prompt with no delimiting, escaping, or
instruction-injection defense. The template places the untrusted query after the
grounding rules and before "Your grounded recommendation:", so a crafted message
(e.g. instructions to ignore prior rules, reveal the system prompt, or invent
products/prices) can attempt to override the grounding constraints. Impact is
bounded — output is conversational text only, there is no tool/function calling,
and product cards are sourced from retrieval, not the model — so the worst case is
a degraded/ungrounded reply rather than data exfiltration or code execution. That
keeps it WARN rather than BLOCK, but it directly undermines the grounding
requirement (BRD risk R-3) the story exists to enforce.
Fix: Wrap the user query in explicit, hard-to-spoof delimiters (e.g. a fenced
`<user_query>...</user_query>` block) and add a prompt instruction that everything
inside the delimiters is data to be answered, never instructions to follow.
Strip or neutralize the delimiter tokens if they appear in the user input. Prefer
chat-role separation (system message for rules, user message for the query) over a
single concatenated prompt where the provider supports it.

### [VULN-002] No maximum length on chat `message` (input validation / cost-DoS)
File: backend/api/schemas.py line 73 (`message: str = Field(min_length=1)`)
Severity: WARN
Description: `ChatRequest.message` enforces only `min_length=1`; there is no
`max_length`. The full message flows into `ChatOrchestrator.handle_turn` and then
verbatim into the LLM prompt (`answer_generator._build_prompt`). An attacker can
submit an arbitrarily large payload, which (a) is billed token-by-token to the
Groq/Gemini provider, enabling a cost-amplification / denial-of-wallet vector, and
(b) enlarges the prompt-injection surface in VULN-001. The endpoint has no rate
limiting (see VULN-006), compounding this.
Fix: Add a `max_length` bound on `ChatRequest.message` (e.g. a few thousand
characters, sized to the realistic longest legitimate query) and on `session_id`.
Reject oversize input at the schema boundary (FastAPI 422) before any LLM call.

### [VULN-003] Raw model response logged at DEBUG
File: backend/services/answer_generator.py line 92-95 (`answer_generator.raw_response`)
Severity: WARN
Description: The model's raw completion is logged (truncated to 1000 chars) under
`raw_content`. The completion is generated from a prompt that embeds the
user-supplied query, so user-influenced content lands in log output. If
`LOG_LEVEL=DEBUG` is ever enabled in a shared or production environment, this can
write back-reflected user input (and any sensitive text a user pastes) into logs,
contrary to the BRD's logging discipline. It is gated behind DEBUG so it stays
WARN, not BLOCK.
Fix: Drop the raw content from the log entry, or log only a length/hash and keep
the full payload out of logs. If full-response logging is needed for debugging,
gate it behind an explicit non-default flag and document that it must never be
enabled in production.

---

## INFO Findings

### [VULN-004] MySQL port published to host
File: docker-compose.yml line 17-18 (`ports: - "3307:3306"`)
Severity: INFO
Description: The database container publishes MySQL to the host on 3307. The
backend reaches MySQL over the internal `shopnet` bridge by service name, so the
host port mapping is not required for the app to function and widens the attack
surface (anything able to reach the host on 3307 can attempt to authenticate).
Acceptable for a single-developer demo, but unnecessary exposure.
Fix: Remove the `ports` mapping for the `mysql` service (rely on the internal
network), or bind it to loopback only (`127.0.0.1:3307:3306`) if host access is
needed for debugging.

### [VULN-005] CORS allows credentials with wildcard request headers
File: backend/api/main.py line 93-99 (`_install_cors`)
Severity: INFO
Description: CORS is configured with `allow_credentials=True` and
`allow_headers=["*"]`. Origins are correctly restricted (never wildcarded, read
from config) and methods are limited to GET/POST, which keeps this low risk.
However, allowing all request headers alongside credentialed requests is broader
than needed, and the app currently uses no cookies/auth, so the credentialed-CORS
setting is also unnecessary today.
Fix: Set `allow_credentials=False` (no credentialed cross-origin requests are
used) and restrict `allow_headers` to the headers actually required (e.g.
`Content-Type`).

### [VULN-006] No authentication or rate limiting on POST /api/chat
File: backend/api/routes/chat.py line 27-33
Severity: INFO
Description: `/api/chat` (and the catalog endpoints) are unauthenticated and
unthrottled. Per BRD §7 this is a low-concurrency single-user/small-group demo with
no stated auth requirement, so this is in-scope-by-design rather than a defect.
Recorded for awareness because it amplifies VULN-002 (cost-DoS): without throttling
the unbounded-input issue can be driven in a tight loop.
Fix: For any non-demo deployment, add a rate limit on `/api/chat` (per-IP or
per-session) and front the service with authentication. No action required for the
current demo scope.

### [VULN-007] No HTTP security response headers
File: backend/api/main.py (middleware stack) / backend/api/middleware.py
Severity: INFO
Description: Responses do not set `X-Content-Type-Options`, `X-Frame-Options` /
frame-ancestors CSP, or related hardening headers. The backend serves JSON to a
Streamlit client rather than rendering HTML, so the practical XSS/clickjacking
exposure is minimal, but the headers are still a cheap best-practice addition.
Fix: Add a small middleware (or extend `RequestIdMiddleware`) to set
`X-Content-Type-Options: nosniff` and a restrictive `Content-Security-Policy` /
`X-Frame-Options: DENY` on responses.

### [VULN-008] `session_id` is fully client-controlled (cross-session access)
File: backend/api/routes/chat.py line 31; backend/services/query_state.py line 78
Severity: INFO
Description: Conversation state is keyed by the client-supplied `session_id` with
no binding to any authenticated identity. Any caller that guesses or reuses another
client's `session_id` would read/extend that session's accumulated filter state and
transcript. State is in-memory only, non-persistent, and holds no secrets or PII by
design (just product-filter preferences and the message transcript), and the demo
is single-user, so real-world impact is negligible. Noted as an IDOR-shaped pattern
to revisit if the app ever multi-tenants or stores user data.
Fix: When auth is introduced, derive or namespace `session_id` from the
authenticated principal (e.g. server-issued, signed session tokens) rather than
trusting a raw client string.

---

## Categories checked and found clean

- SQL injection: `product_repository.py` uses parameterized queries throughout
  (`%s` placeholders + params tuple for upsert, IN-list, and filter clauses; column
  names are static constants, not user input). No string interpolation of user data
  into SQL.
- Command injection: no shell/`subprocess`/`os.system` calls in scope.
- Hardcoded secrets (incl. test files): none. Secrets load from env via `pydantic`
  `SecretStr` (`config.py`); `repr` is safe; `.env.example` contains only
  placeholders; `.env` is gitignored and not git-tracked (verified). The test file
  uses only product fixtures, no credentials. docker-compose injects every secret
  from the host `.env` (`${...}`), nothing baked in.
- SSRF: image-URL handling (`frontend/components/placeholders.py`) enforces
  https-only, an explicit host allowlist, and blocks non-global IP literals
  (loopback/private/link-local incl. 169.254.169.254 metadata), and refuses to probe
  disallowed URLs. Correctly hardened.
- Path traversal: placeholder asset path is derived from a fixed category→filename
  map, not raw user input; the prompt-template path is a static module-relative path.
- Insecure deserialization: `_parse_tags` uses `json.loads` on DB-sourced data only
  (no pickle/yaml on untrusted input).
- Insecure dependencies: no manifest change in this group; not re-audited here.
- Stack-trace leakage (BRD NFR-3): the error middleware maps typed/unexpected errors
  to a generic envelope and logs detail server-side only — compliant.
