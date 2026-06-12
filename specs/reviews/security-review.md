# Security Review — ShopAssistantRAG (Group H) — 2026-06-12

Scope: Group H per `sprint-contracts/H.json` — test suites (unit/integration/e2e),
Docker/deployment files, dependency manifests, init scripts, README, and the
backend services the Group H tests exercise (chat_orchestrator, answer_generator,
hybrid_retriever, filter_extractor, hydrator, query_state) plus the request-path
collaborators they touch (product_repository, db, config, middleware, main, chat route).

## Summary
- BLOCK findings: 1
- WARN findings: 6
- INFO findings: 6
- Overall verdict: BLOCK

## BLOCK Findings

### [VULN-001] Live third-party API keys and DB credentials present in workspace `.env`
File: `.env` lines 7, 8, 16, 19, 35
Severity: BLOCK
Description: The working-tree `.env` file contains real, live-format secret values, not
placeholders: a Google Gemini API key (`GOOGLE_API_KEY=AIza...`), a Pinecone API key
(`PINECONE_API_KEY=pcsk_...`), a Groq API key (`GROQ_API_KEY=gsk_...`), the MySQL root
password (`MYSQL_ROOT_PASSWORD=root`), and the application MySQL password
(`MYSQL_PASSWORD=shoppassword`). These are billable, externally-exploitable credentials.
Mitigating factor: `.env` IS listed in `.gitignore` (line 3) and `git ls-files` /
`git log --all -- .env` confirm it is not tracked and was never committed — so the secrets
have not leaked through git history. However, the secrets are live in the developer
workspace, are trivially captured by any tool/process with filesystem access, and the keys
look genuine (real Gemini/Pinecone/Groq prefixes). Treat them as compromised. The fact that
they were ever written into a real file (rather than the operator filling them in locally
from `.env.example`) is the exploitable condition.
Fix:
1. Immediately rotate/revoke all three API keys (Google AI Studio, Pinecone console, Groq
   console) and the MySQL passwords, since they must now be assumed exposed.
2. Replace the values in the local `.env` with the rotated secrets only on the machine that
   needs them; never distribute a populated `.env`.
3. Confirm the file stays git-ignored (it is) and add a pre-commit secret scanner (e.g.
   gitleaks / detect-secrets) to the CI pipeline so a future `git add -f .env` is blocked.
4. Change the default `MYSQL_ROOT_PASSWORD=root` / weak `shoppassword` to strong,
   unique values; `root`/`shoppassword` are guessable defaults.

## WARN Findings

### [VULN-002] MySQL port published to the host
File: `docker-compose.yml` lines 17-18
Severity: WARN
Description: The MySQL service maps `3307:3306`, exposing the database on the host
interface. Only the backend (on the `shopnet` bridge network) needs MySQL; publishing the
port widens the attack surface to anything that can reach the host, and combined with the
weak default credentials (VULN-001) makes the DB directly reachable.
Fix: Remove the `ports:` mapping for the `mysql` service so it is reachable only over the
internal `shopnet` network. If host access is needed for debugging, bind to loopback only
(`127.0.0.1:3307:3306`) and gate it behind a dev-only compose override.

### [VULN-003] MySQL password passed on the command line in the healthcheck
File: `docker-compose.yml` line 25
Severity: WARN
Description: The healthcheck runs `mysqladmin ping ... -p${MYSQL_PASSWORD}`, embedding the
password as a command-line argument. Process arguments are visible to any other process in
the container/host (`/proc/<pid>/cmdline`, `docker inspect`, `ps`), and `mysql` itself warns
that using `-p<password>` on the CLI is insecure.
Fix: Use a password-file or env-based approach for the healthcheck, e.g. set `MYSQL_PWD` in
the check environment, or use `mysqladmin ping -h localhost` without auth (ping does not
require credentials for a basic liveness check), or a healthcheck script that reads the
password from a file/secret.

### [VULN-004] Containers run as root (no non-root user)
File: `docker/backend.Dockerfile` (whole file), `docker/frontend.Dockerfile` (whole file)
Severity: WARN
Description: Neither image creates or switches to a non-root user; the entrypoint/CMD run as
UID 0. A code-execution or container-escape bug then runs with root privileges inside the
container, and the bind mounts (`./data`, `./frontend/assets`) plus any future writable
mounts are accessed as root.
Fix: In each Dockerfile create a dedicated non-root user and `USER` it before the
`ENTRYPOINT`/`CMD`, e.g. `RUN useradd --create-home --uid 10001 appuser` then `USER appuser`.
Ensure `/app` is owned by that user. Consider `read_only: true` plus a tmpfs for scratch dirs
in compose.

### [VULN-005] No request-body size / message length limit on `POST /api/chat`
File: `backend/api/schemas.py` lines 65-81 (`ChatRequest`); reaches
`backend/services/chat_orchestrator.py` and `backend/services/filter_extractor.py`
Severity: WARN
Description: `ChatRequest.message` and `session_id` enforce only `min_length=1`; there is no
`max_length`. The unbounded `message` is interpolated into the LLM prompt
(`filter_extractor.extract`/`answer_generator._build_prompt` via `{{QUERY}}`) and stored in
per-session history (`query_state.append_turn`). An attacker can submit very large bodies to
drive token cost / latency (LLM-billing DoS) and grow in-memory session state. `session_id`
is also unbounded and is the dict key in the in-memory `QueryStateManager`, so a flood of
distinct long IDs grows memory without bound (no eviction of idle sessions).
Fix: Add `max_length` constraints to both fields (e.g. `message` ~2000 chars, `session_id`
~128 chars). Add a global request-body size limit at the ASGI/proxy layer. Bound the number
of live sessions in `QueryStateManager` (LRU/TTL eviction) so distinct-session floods cannot
exhaust memory.

### [VULN-006] No rate limiting and no authentication on the API
File: `backend/api/routes/chat.py` line 27, `backend/api/main.py` lines 78-87
Severity: WARN
Description: `POST /api/chat` (and the catalog GETs) have no throttling and no auth. Each chat
turn fans out to Groq (filter extraction), Gemini (embeddings), Pinecone, and MySQL, so an
unauthenticated request flood translates directly into external API spend and downstream load.
Anyone who can reach port 8000 can drive cost.
Fix: Add per-IP / per-session rate limiting (e.g. `slowapi`, or limits at the reverse proxy)
on `/api/chat`. Consider requiring an API token or putting the backend behind an authenticated
gateway before exposing port 8000 beyond localhost.

### [VULN-007] Untrusted user query interpolated directly into LLM prompts (prompt injection)
File: `backend/services/filter_extractor.py` line 108, `backend/services/answer_generator.py`
lines 80-84
Severity: WARN
Description: The raw user `query` is substituted into the prompt templates via a simple
`.replace("{{QUERY}}", query)` with no delimiting, escaping, or instruction isolation. A
crafted message can attempt to override the system instructions (classic prompt injection),
e.g. coercing the extractor to emit arbitrary JSON or the answer generator to ignore the
grounding rule and invent products/prices. Impact is bounded by the architecture (extractor
output is schema-validated and out-of-vocab values are dropped; the generator output is plain
text shown to the user, not executed), so this is WARN rather than BLOCK — but the grounding
guarantee (BRD R-3) can still be subverted.
Fix: Wrap the user input in a clearly delimited block in the template (e.g. fenced
`<user_query>...</user_query>`) and add a system instruction that content inside the block is
data, never instructions. Keep the existing schema validation on extractor output. Consider
output validation on the generator (verify referenced product names exist in the supplied
context).

## INFO Findings

### [VULN-008] Raw LLM response content logged at DEBUG
File: `backend/services/answer_generator.py` lines 96-99,
`backend/services/filter_extractor.py` line 116
Severity: INFO
Description: `answer_generator._invoke` logs `raw_content` (first 1000 chars of the model
reply) and `filter_extractor.extract` logs the raw model output at DEBUG. The prompt embeds
the user message, so at `LOG_LEVEL=DEBUG` user-supplied content lands in logs. Not a secret
leak (no credentials), but it is user data in logs and could include PII the user typed.
Fix: Keep these at DEBUG (default `LOG_LEVEL` is INFO, so off in prod) and document that DEBUG
must not be enabled in production. Consider truncating further or redacting if logs ship to a
shared sink.

### [VULN-009] CORS configured with `allow_credentials=True` and `allow_headers=["*"]`
File: `backend/api/main.py` lines 90-99
Severity: INFO
Description: `allow_credentials=True` is paired with a header wildcard. Origins are correctly
restricted (no `*` origin — good), so this is not exploitable today. But the API uses no
cookies/credentials (the frontend is a server-side Streamlit client), so `allow_credentials`
is unnecessary and `allow_headers=["*"]` is broader than needed.
Fix: Set `allow_credentials=False` (the API needs no credentialed cross-origin requests) and
list the specific headers the frontend sends (e.g. `["Content-Type"]`).

### [VULN-010] No HTTP security response headers
File: `backend/api/middleware.py` (whole module), `backend/api/main.py` lines 78-99
Severity: INFO
Description: Responses carry no `X-Content-Type-Options`, `X-Frame-Options` /
`Content-Security-Policy`, or `Strict-Transport-Security`. The API returns JSON only and the
UI is Streamlit (which sets its own headers), so direct risk is low, but defense-in-depth is
missing on the backend.
Fix: Add a small middleware (or extend `RequestIdMiddleware`) to set
`X-Content-Type-Options: nosniff` and, where appropriate, `X-Frame-Options: DENY` on API
responses. Terminate TLS and add HSTS at the proxy.

### [VULN-011] Unpinned base image tags
File: `docker/backend.Dockerfile` line 2, `docker/frontend.Dockerfile` line 2,
`docker-compose.yml` line 11
Severity: INFO
Description: `python:3.11-slim` and `mysql:8.0` are floating tags — rebuilds can pull a
changed image, undermining reproducibility and making it hard to know which CVE-patched base
is deployed. Application Python deps in `requirements.txt`/`frontend-requirements.txt` are
pinned (good).
Fix: Pin base images by digest (`python:3.11-slim@sha256:...`, `mysql:8.0.x`) and refresh on a
schedule.

### [VULN-012] No dependency vulnerability scanning of the pinned manifests
File: `requirements.txt` (all lines), `frontend-requirements.txt` (all lines)
Severity: INFO
Description: Dependencies are pinned to specific versions but there is no evidence of a CVE
scan (`pip-audit` / Dependabot). Pinned-but-stale versions accumulate known CVEs over time.
`npm audit` is N/A (no Node manifest in scope). Versions could not be cross-checked against a
live advisory DB in this offline review.
Fix: Add `pip-audit` (or Dependabot/Renovate) to CI against both manifests and triage
HIGH/CRITICAL findings each sprint.

### [VULN-013] Test fixtures contain dummy credentials (verified non-production)
File: `tests/unit/test_groq_client.py` lines 74-123, `tests/unit/test_llm_provider.py`
lines 30, 35
Severity: INFO
Description: Test files pass `GROQ_API_KEY="gsk-test"` to fixtures. These are obvious
non-functional placeholders, are not the production values, and are confined to unit tests.
Recorded per the test-file scanning rule; no action required.
Fix: None required. Optionally centralize the dummy value in a shared fixture constant.

## Notes on areas reviewed and found clean
- SQL access (`backend/repositories/product_repository.py`, `backend/repositories/db.py`):
  all queries are parameterized (`%s` placeholders; the `IN (...)` placeholder list is built
  from the count of IDs, not their values); no string interpolation of user data into SQL.
  SQL injection: clean.
- Schema application (`db.init_schema`, `scripts/init_db.py`) reads a fixed bundled
  `sql/schema.sql`; no user input reaches statement construction.
- Entrypoint/init scripts (`docker/entrypoint-backend.sh`, `init.sh`) use `set -euo pipefail`
  and quote variables; the Python socket-wait uses operator-controlled env vars, not
  request-controlled input — no command injection from end-user input.
- Config (`backend/core/config.py`) stores secrets as `SecretStr`; `connection_params` does
  not log the password; error middleware (`backend/api/middleware.py`) never leaks stack
  traces or internal detail to clients (verified by integration tests).
- No `eval`/`pickle`/`yaml.load`/`subprocess` on untrusted data; no SSRF (server fetches only
  fixed cloud SDK endpoints, not user-supplied URLs); no path traversal (file paths are
  module-relative constants, not request-derived).
