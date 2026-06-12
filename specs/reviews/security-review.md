# Security Review — ShopAssistantRAG (Story Group A: Foundation Layer) — 2026-06-12

Scope: stories E1-S1, E1-S2, E1-S3, E2-S1 and features F001-F016. Files reviewed:
`backend/domain/models.py`, `backend/domain/enums.py`, `backend/core/config.py`,
`backend/core/logging.py`, `backend/core/errors.py`, `sql/schema.sql`,
`scripts/init_db.py`, `scripts/ingest.py`, `backend/repositories/db.py`,
`backend/repositories/product_repository.py`, `.env.example`, `.gitignore`,
`docker-compose.yml`, `requirements.txt`, `pyproject.toml`, and the foundation
test files `tests/unit/test_config.py`, `tests/unit/test_db.py`.

## Summary
- BLOCK findings: 0
- WARN findings: 3
- INFO findings: 5
- Overall verdict: WARN (no BLOCK; merge may proceed, address WARN items next sprint)

The foundation layer is solid. All SQL uses parameterized queries, secrets are
loaded from the environment via `SecretStr` and masked in `repr`, `.env` is
gitignored and not tracked, `.env.example` contains only placeholders, and no
unsafe deserialization (`pickle`/`yaml.load`/`eval`/`exec`/shell) is present.
No BLOCK-level issues found. The WARN items are hardening recommendations that
do not block the merge.

## BLOCK Findings

None.

## WARN Findings

### [VULN-001] Required secrets accepted as empty strings (incomplete input validation)
File: backend/core/config.py lines 43-49, 116-124
Severity: WARN
Description: `Settings` declares `GOOGLE_API_KEY`, `PINECONE_API_KEY`, and
`MYSQL_PASSWORD` as `SecretStr` and the host/user/database as `str`. Pydantic's
"missing" detection only fires when a key is fully absent; an empty string
(`MYSQL_PASSWORD=`) or whitespace passes validation. `_missing_required_keys`
only inspects errors of type `"missing"`, so a present-but-empty required secret
is silently accepted and propagated to the DB driver and SDK clients. This
weakens the NFR-3 guarantee that all secrets are supplied. The `groq_api_key_value`
accessor (lines 87-95) does correctly reject an empty value, but the seven core
required fields do not get the same treatment.
Fix: Add a `min_length=1` constraint (or a `field_validator`/`model_validator`
that rejects blank/whitespace-only values after `.strip()`) to the seven required
fields so an empty required secret raises `ConfigError` naming the key, matching
the existing missing-key behavior.

### [VULN-002] CORS origins parsed but not validated; misconfiguration can widen exposure
File: backend/core/config.py lines 56, 64-70
Severity: WARN
Description: `ALLOWED_ORIGINS` is a free-form comma-separated string fed directly
into `allowed_origins_list()` with no validation. A deployment that sets
`ALLOWED_ORIGINS=*` (or includes an unintended origin) would be accepted verbatim
and, once consumed by the API CORS middleware (E7-S1), could allow cross-origin
credentialed requests from arbitrary sites. The foundation layer owns config
parsing and is the correct place to constrain this value.
Fix: Validate each parsed origin against a scheme+host allowlist (reject bare `*`
when credentials are enabled, reject entries without an `http(s)://` scheme). At
minimum document and assert in the consuming API layer that `*` is never combined
with credentialed CORS.

### [VULN-003] Verbose driver exception text echoed to stderr by CLI entrypoints
File: scripts/init_db.py line 28; scripts/ingest.py line 55; backend/repositories/db.py lines 84-86; backend/repositories/product_repository.py line 118
Severity: WARN
Description: On failure, `RepositoryError` is constructed with the full underlying
driver exception text (`f"Failed to initialize MySQL schema on {host}: {exc}"`)
and the CLI entrypoints `print(...)` that message to stderr. mysql-connector
exception strings can include host, user, and connection parameters. These are
CLI/dev tools (not an HTTP surface) and the structured logger deliberately omits
the password (good), but verbose driver errors echoed to a console can leak
connection topology into terminal output / CI logs.
Fix: Keep the wrapped `RepositoryError` message high-level (e.g. "MySQL schema
init failed; see logs") and log the detailed `exc` only via the structured logger.
Do not interpolate raw driver exception text into messages printed to stdout/stderr.

## INFO Findings

### [VULN-004] `.env` present on disk but correctly untracked — verified clean
File: .gitignore lines 1-4; working-tree `.env`
Severity: INFO
Description: A local `.env` exists on disk. It is correctly listed in `.gitignore`
(`.env`, `.env.local`); `git ls-files` shows only `.env.example` is tracked, and
`git status` / `git diff --cached` show `.env` is neither tracked nor staged. No
real secret is committed. Informational confirmation, not a defect.
Fix: No action required. Optionally add a pre-commit secret scanner (gitleaks /
detect-secrets) to enforce this in CI.

### [VULN-005] `.env.example` contains only placeholders — verified clean
File: .env.example lines 15-30
Severity: INFO
Description: The committed template uses obvious placeholders
(`your-google-api-key-here`, `your-groq-api-key-here`,
`your-pinecone-api-key-here`, `MYSQL_PASSWORD=change-me`). No real credential
present.
Fix: No action required. The documented default `change-me` must never reach a
real deployment; a reinforcing comment is optional.

### [VULN-006] Hardcoded test credentials in fixtures (acceptable; not used in prod)
File: tests/unit/test_config.py lines 12-20; tests/unit/test_db.py lines 19-27
Severity: INFO
Description: Test fixtures define literal credentials (`test-google-key`,
`shop_password`, etc.). Per review policy these were inspected as in-scope: they
are test-only fixtures, not referenced by any production config path, and the same
values do not appear in `docker-compose.yml`, `.env.example`, or source modules.
Fix: No action required. Optionally centralize fixture env in a shared factory.

### [VULN-007] `EMBEDDING_MODEL` default mismatch between code and template (config hygiene)
File: backend/core/config.py line 52 vs .env.example line 45
Severity: INFO
Description: `config.py` defaults `EMBEDDING_MODEL` to `"text-embedding-004"`
while `.env.example` documents `EMBEDDING_MODEL=gemini-embedding-2`. Not a
security vulnerability, but an inconsistency that can confuse which model/dimension
is authoritative (embedding-dimension drift can have downstream correctness impact).
Fix: Align the code default and the template to a single documented value.

### [VULN-008] MySQL multi-statement execution disabled by design — verified safe
File: backend/repositories/db.py lines 49-58, 71-74
Severity: INFO
Description: `init_schema` splits the schema file into individual statements via
`split_sql_statements` and calls `cursor.execute(statement)` once per statement
(no `multi=True`). The schema text is a trusted static asset, not user input, and
all runtime queries in `product_repository.py` use `%s` placeholders with values
passed separately. Column names and placeholder counts derive only from hardcoded
constants. No SQL injection vector in the foundation layer.
Fix: No action required. If future stories load externally-provided SQL, do not
reuse this splitter on untrusted input.

## Checks that passed (no finding)
- SQL injection: not present — all queries parameterized (`product_repository.py`
  lines 73-75, 92, 106, 137-160; `db.py` 71-74). Dynamic SQL fragments derive only
  from hardcoded constants.
- Unsafe deserialization / RCE: none — no `pickle`, `yaml.load`, `eval`, `exec`,
  `os.system`, `subprocess`, or `shell=True` in scope. `json.loads` in
  `_parse_tags` consumes DB-origin column data only.
- Secret masking: `SecretStr` for all secrets; `test_repr_does_not_leak_api_keys`
  asserts `repr(settings)` hides them. Structured logger only serializes
  caller-supplied `extra` fields and `connection_params` documents no password
  logging.
- Path traversal: `_SCHEMA_PATH` resolved from `__file__` (static). `scripts/ingest.py`
  takes a CSV path from argv — operator-run CLI, not a network attack surface.
- Auth/Authz: Group A has no exposed network surface (pure domain/config/logging/DB
  bootstrap). Nothing to bypass at this layer.
- Insecure randomness: no `random`/`secrets` usage in scope.
- Dependencies (requirements.txt): all pinned — fastapi 0.136.3, uvicorn 0.48.0,
  pydantic 2.12.5, pydantic-settings 2.13.1, python-dotenv 1.2.2, google-genai
  1.68.0, groq 1.4.0, pinecone 9.0.1, mysql-connector-python 9.1.0. No automated
  CVE scanner available in this environment; recommend running `pip-audit` in CI.

---

# Security Review — ShopAssistantRAG (Story Group B: Backend RAG) — 2026-06-12

## Summary
- BLOCK findings: 0
- WARN findings: 4
- INFO findings: 6
- Overall verdict: WARN (no BLOCK; merge may proceed, address WARN items before any
  non-local/public deployment)

Scope reviewed (all files in the Group B contract):
- backend/repositories/ (product_repository.py, pinecone_client.py, db.py)
- backend/services/ (csv_loader.py, embedding_text.py, embedding_client.py, answer_generator.py,
  chat_orchestrator.py, filter_extractor.py, groq_client.py, hybrid_retriever.py, hydrator.py,
  ingestion.py, llm_provider.py, query_state.py)
- backend/core/ (errors.py, config.py, logging.py)
- backend/api/ (main.py, middleware.py, dependencies.py, routes/*.py, schemas.py)
- backend/domain/ (models.py, enums.py)
- sql/schema.sql; backend/prompts/*.txt
- supporting: .env, .env.example, requirements.txt, pyproject.toml

### Positive observations (verified mitigations)
- SQL is fully parameterized. `product_repository.py` uses `%s` placeholders for all values,
  builds `IN (...)` placeholders by count (never interpolating values), and whitelists filter
  column names from a fixed code constant. No SQLi.
- Secrets load via pydantic `Settings` from env/`.env`, wrapped in `SecretStr`; nothing hardcoded
  in source. `connection_params` excludes the password from logs.
- Error middleware maps every typed error to a generic public envelope; no stack trace reaches the
  client (NFR-3). CORS restricted to configured origins (no wildcard), methods limited to GET/POST.
- No `eval`/`exec`/`pickle`/`yaml.load`/`os.system`/`subprocess` anywhere in the backend.
- Every external SDK/driver boundary catches raw exceptions and re-raises typed domain errors.
- The chat orchestrator's filter extraction validates LLM output against fixed enums and falls back
  to empty filters on malformed output — a prompt-injection attempt cannot inject SQL or arbitrary
  structured filters downstream.

## BLOCK Findings

None.

## WARN Findings

### [VULN-B01] Real live-format API keys present in local `.env`
File: .env (GOOGLE_API_KEY, PINECONE_API_KEY, GROQ_API_KEY, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD)
Severity: WARN
Description: The on-disk `.env` contains real, live-format credentials — a Google API key
(`AIzaSy...`, 39 chars), a Pinecone key (`pcsk_...`, 75 chars), a Groq key (`gsk_...`, 56 chars),
plus MySQL user and root passwords. The file is correctly gitignored and is NOT in git history, so
it does not leak through the repository. It is flagged because real keys sitting in plaintext on a
workstation are an exposure risk (backups, screen-shares, accidental copy into a tracked file). Not
a BLOCK because nothing secret is committed.
Fix: Confirm these are throwaway/dev keys, not production; rotate any production-grade or shared key.
Prefer a secret manager or per-developer local injection over a long-lived plaintext `.env`. Add a
pre-commit secret-scanning hook (gitleaks/detect-secrets) to prevent future accidental commits.

### [VULN-B02] No authentication / authorization / rate limiting on any API route
File: backend/api/routes/chat.py line 27; backend/api/routes/catalog.py lines 32, 56; backend/api/main.py lines 78-99
Severity: WARN
Description: `POST /api/chat`, `GET /api/products`, and `GET /api/filters` have no auth dependency,
API key, or rate limiting. CORS is not a server-side access control, so any non-browser client can
drive `/api/chat`, which fans out to paid Groq (LLM), Gemini (embedding), and Pinecone calls on
every request. This is an unauthenticated cost-amplification / abuse and rate-limit-exhaustion
vector. The design documents a single-user demo, so it is WARN rather than BLOCK, but it must not
ship to a public/production deployment as-is.
Fix: Before any non-local deployment, add server-side authentication (API key or session token) on
`/api/chat` and the catalog routes, and add per-client rate limiting/throttling on `/api/chat`. If
it stays a closed demo, enforce network-level restriction (bind to localhost / private network).

### [VULN-B03] User input concatenated into LLM prompts without delimiting (prompt injection)
File: backend/services/filter_extractor.py line 108; backend/services/answer_generator.py lines 80-84; backend/prompts/filter_extraction.txt line 26; backend/prompts/answer_generation.txt lines 16-18
Severity: WARN
Description: The raw user message is substituted into prompts via plain
`str.replace("{{QUERY}}", query)` with no escaping or structural delimiting, and product fields
(name/brand/color) are inlined into the answer-generation context. A crafted message can attempt to
override the system instructions ("ignore previous instructions..."). Impact is bounded: filter
extraction validates output against fixed enums and degrades to empty filters, so a jailbreak cannot
inject SQL or arbitrary filters; answer generation only returns text (no tool/code execution). The
realistic risk is reputational — coercing off-brand/misleading replies, or laundering injected text
from poisoned catalog data into a user-facing reply.
Fix: Wrap user-supplied and catalog-derived content in clearly delimited blocks (e.g. fenced
`<<<USER_QUERY>>> ... <<<END>>>`) and instruct the model to treat that block strictly as data, never
instructions. Keep the existing output validation; consider a length/format guard on the reply.

### [VULN-B04] Raw LLM responses logged (untrusted content in logs)
File: backend/services/filter_extractor.py lines 116, 127, 132; backend/services/answer_generator.py line 98
Severity: WARN
Description: Raw LLM responses (truncated to 200-1000 chars) are logged at DEBUG and WARNING. These
echo content derived from untrusted user input and model output. No secret is leaked (verified: the
logger only serializes caller-supplied `extra` and the DB password is excluded), but echoing raw
model output at WARNING in production can leak prompt content / user PII into log aggregation and
inflate logs. Lower severity because it is not a secret leak.
Fix: Keep raw-response logging at DEBUG only (filter_extractor lines 127/132 currently log
`raw[:200]` at WARNING), redact/hash the raw content or gate it behind an explicit debug flag, and
ensure production `LOG_LEVEL` is not DEBUG.

## INFO Findings

### [VULN-B05] `image_url` from CSV stored and returned unvalidated
File: backend/services/csv_loader.py line 87; backend/domain/models.py line 31; backend/api/schemas.py line 36
Severity: INFO
Description: `image_url` is accepted as a free-form optional string from the catalog CSV, persisted,
and returned verbatim in `ProductOut`, never validated as a URL/scheme. A poisoned catalog row could
carry a `javascript:`/`data:` URL — a stored-XSS vector only if a frontend renders it unsafely
(out of Group B scope, hence INFO). The backend never fetches this URL, so there is no SSRF.
Fix: Validate `image_url` against an `http(s)` scheme (pydantic `HttpUrl` or explicit scheme check)
at the domain/schema boundary; document that the frontend must treat it as untrusted.

### [VULN-B06] CSV path is caller-controlled (no traversal sanitization; not currently exposed)
File: backend/services/csv_loader.py line 45; backend/services/ingestion.py line 103
Severity: INFO
Description: `load_products_from_csv(csv_path)` opens whatever `Path` it is given. The path comes
from the operator running the ingestion CLI, not an HTTP request, so this is not a path-traversal
vulnerability in the current wiring (no web route reaches it). Flagged only so it is not later wired
to user input without sanitization.
Fix: If the CSV path is ever exposed via an API or untrusted config, restrict it to an allowlisted
base directory and reject `..` traversal before opening.

### [VULN-B07] CORS `allow_credentials=True` with wildcard headers
File: backend/api/main.py lines 93-99
Severity: INFO
Description: CORS allows credentials and `allow_headers=["*"]`. Origins are correctly restricted (no
wildcard origin), so risk is low, but credentialed requests combined with a wildcard header allowlist
is broader than needed for an API that uses no cookies/credentials today.
Fix: Since the API has no auth/cookies yet, set `allow_credentials=False` and enumerate the specific
headers actually needed (e.g. `Content-Type`).

### [VULN-B08] Service metadata exposed via health endpoint and startup log
File: backend/api/routes/health.py lines 14-15, 27-29; backend/api/main.py lines 63-72
Severity: INFO
Description: `/api/health` returns service name and version, and startup logs the active LLM provider,
models, embedding dimension, and Pinecone index name. None is secret, but it is fingerprinting
metadata. Acceptable for a demo.
Fix: Optional hardening — omit version from unauthenticated responses in production.

### [VULN-B09] No max length on chat input (cost/resource amplification)
File: backend/api/schemas.py lines 65-81; backend/api/routes/chat.py line 28
Severity: INFO
Description: `ChatRequest.message` enforces only `min_length=1`; no `max_length`. A very large message
is forwarded into the LLM prompt and embedding call, enabling token/cost amplification and resource
pressure (compounded by the lack of rate limiting in VULN-B02).
Fix: Add a reasonable `max_length` (e.g. a few thousand chars) to `message` and `session_id`, and/or
a body-size limit at the server/proxy.

### [VULN-B10] Test fixtures contain placeholder credentials (benign)
File: tests/unit/test_pinecone_client.py (multiple lines); tests/unit/test_groq_client.py (multiple); tests/unit/test_llm_provider.py lines 30, 35
Severity: INFO
Description: Test files use literal fixture keys such as `api_key="x"` and `GROQ_API_KEY="gsk-test"`.
These are obvious non-production placeholders used to construct fakes; they are not real credentials
and are not used in any production config path.
Fix: None required. Reported per policy; benign.

## Dependency note (Group B)
File: requirements.txt
All runtime deps pinned (fastapi 0.136.3, uvicorn 0.48.0, pydantic 2.12.5, pydantic-settings 2.13.1,
python-dotenv 1.2.2, google-genai 1.68.0, groq 1.4.0, pinecone 9.0.1, mysql-connector-python 9.1.0).
No automated CVE scan (`pip-audit`/`safety`) available in this environment; recommend running one in
CI against these pins. No obviously vulnerable pin identified by inspection.
