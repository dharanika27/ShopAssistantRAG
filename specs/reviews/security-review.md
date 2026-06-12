# Security Review — ShopAssistantRAG (Story Group A) — 2026-06-12

## Scope
Changed files since initial commit b4c4a07 plus group-A foundational config:
- backend/services/chat_orchestrator.py
- backend/core/config.py
- backend/repositories/db.py
- frontend/components/placeholders.py
- frontend/components/product_card.py
- frontend/assets/README.md
- data/products.csv
- docker-compose.yml
- .env.example
- .gitignore, .gitattributes
- docs/image-pipeline-audit.md
- tests/unit/test_chat_orchestrator.py
- tests/unit/test_placeholders.py

## Summary
- BLOCK findings: 0
- WARN findings: 2
- INFO findings: 5
- Overall verdict: WARN (no merge blockers; two items should be fixed)

---

## BLOCK Findings
None.

---

## WARN Findings

### [VULN-001] Server-Side Request Forgery (SSRF) in image reachability probe
File: frontend/components/placeholders.py lines 64-76 (`_url_reachable`), reached via line 110 (`image_source_for`)
Severity: WARN
Description: The Streamlit server issues `requests.get(url, allow_redirects=True)`
against the product `image_url` to probe reachability. There is no scheme
allowlist, host allowlist, or private/link-local IP block, and redirects are
followed. Today `image_url` originates from the curated catalog (CSV -> MySQL ->
API), so it is not directly end-user controlled, which keeps this out of BLOCK
range. However, anyone who can influence catalog rows (CSV import, DB write,
future admin/upload feature) gains a server-side fetch primitive: it could be
pointed at internal services (e.g. `http://169.254.169.254/` cloud metadata,
`http://localhost:8000` backend, internal MySQL) and the redirect-following
amplifies it. The probe runs from inside the frontend container, which sits on
the same Docker `shopnet` network as the backend and MySQL.
Fix: Before probing, validate the URL: require `https` (or an explicit
http/https allowlist), resolve the hostname and reject private, loopback,
link-local, and metadata IP ranges, and set `allow_redirects=False` (or
re-validate each redirect hop). Optionally restrict to a host allowlist of
expected image CDNs (e.g. `loremflickr.com`). Cap the response with a size/read
limit since `stream=True` is used.

### [VULN-002] Insecure default for MySQL root password in docker-compose
File: docker-compose.yml line 13
Severity: WARN
Description: `MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-root}` falls back to the
weak, well-known credential `root` when the environment variable is unset. The
MySQL container also publishes port 3307 to the host (line 18), so a missing env
var yields a root account with a guessable password reachable from the host.
This is a config-hygiene weakness, not an exploit in the application code.
Fix: Remove the `:-root` default so compose fails fast when
`MYSQL_ROOT_PASSWORD` is unset, mirroring how `MYSQL_PASSWORD`/`MYSQL_USER` are
required with no default. Document the variable in `.env.example`. Consider not
publishing the MySQL port to the host outside local development.

---

## INFO Findings

### [VULN-003] User-derived token echoed into assistant reply (Markdown sink)
File: backend/services/chat_orchestrator.py lines 257-272; rendered at
frontend/components/chat.py line 114 (`st.markdown(turn.text)`)
Severity: INFO
Description: `_out_of_catalog_reply` interpolates a token from the user message
into the reply string, which is later rendered with `st.markdown`. Two factors
neutralize this to INFO: (1) Streamlit `st.markdown` defaults to
`unsafe_allow_html=False`, so raw HTML/script is escaped; and (2) the echoed
token is produced by `re.findall(r"[a-z]+", message.lower())`, so only lowercase
letters survive — no Markdown metacharacters (`[`, `]`, `(`, `)`, backticks) can
pass through, preventing Markdown link/image injection.
Fix: No action required while both mitigations hold. If the reply ever begins
echoing raw user text (not the `[a-z]+`-filtered token), or any UI switches to
`unsafe_allow_html=True`, treat it as a Markdown/HTML injection sink and escape
or sanitize.

### [VULN-004] Catalog strings rendered via st.markdown
File: frontend/components/product_card.py lines 36, 38
Severity: INFO
Description: `product.name` and the formatted price are rendered with
`st.markdown`. Streamlit's default `unsafe_allow_html=False` escapes HTML, and
the values are catalog-sourced. Low risk, but Markdown control characters in a
product name (e.g. `*`, `_`, backticks) could mildly distort rendering.
Fix: Prefer `st.write`/`st.text` for untrusted display strings, or escape
Markdown metacharacters in `product.name`.

### [VULN-005] Image probe lacks response size / read cap
File: frontend/components/placeholders.py lines 70-73
Severity: INFO
Description: The probe uses `stream=True` and closes the response, so the body is
not fully read — acceptable. Still, no explicit byte cap exists; a malicious or
slow host within the (currently 3s) timeout could tie up a worker.
Fix: Keep the short timeout; optionally add an explicit read cap and avoid
following redirects (see VULN-001).

### [VULN-006] EMBEDDING_MODEL default mismatch between config and compose
File: backend/core/config.py line 52 (`text-embedding-004`) vs
docker-compose.yml line 49 / .env.example line 45 (`gemini-embedding-2`)
Severity: INFO
Description: Not a security issue per se, but inconsistent defaults can produce
surprising production behavior and embedding-dimension mismatches. Noted for
correctness/hardening.
Fix: Align the default embedding model across config, compose, and `.env.example`.

### [VULN-007] Test fixtures use placeholder session IDs only — no real secrets
File: tests/unit/test_chat_orchestrator.py, tests/unit/test_placeholders.py
Severity: INFO
Description: Test code was reviewed specifically for committed credentials,
insecure randomness, and hardcoded tokens (test code ships to version control).
The only literals are non-sensitive session identifiers (`session-001`,
`session-002`) and product fixtures; no API keys, passwords, or RNG seeds are
present. No insecure randomness is used. No action required.

---

## Positive observations (defense in depth confirmed)
- Secrets are loaded via pydantic `BaseSettings` from env/`.env`, stored as
  `SecretStr`, and never hardcoded (backend/core/config.py). `.env` is gitignored;
  only `.env.example` with placeholder values is committed.
- MySQL schema execution (backend/repositories/db.py) runs trusted, file-sourced
  DDL split on `;`; no user input reaches `cursor.execute`, so no SQL injection
  in this layer. (Note: `split_sql_statements` is naive about `;` inside string
  literals, but the input is the trusted `sql/schema.sql`, not user data.)
- CORS origins are explicitly configured via `ALLOWED_ORIGINS`
  (backend/core/config.py line 56) rather than a wildcard.
- The orchestrator's out-of-catalog and intent handling do not execute, eval, or
  shell out on user input; no command injection or unsafe deserialization
  surface in scope.
- data/products.csv contains no embedded secrets/credentials.
- docker-compose mounts catalog and assets read-only (`:ro`) and injects all
  secrets from the host `.env`; nothing is baked into images.
