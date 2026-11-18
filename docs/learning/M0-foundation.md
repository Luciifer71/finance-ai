# M0: Foundation and guardrails

## 1. What we built
The skeleton every later feature plugs into: settings read from environment variables, one error
format for the whole API, JSON logs that scrub secrets, a fake-able clock, a database session per
request, health checks, and one script (`scripts/dev.py`) that runs every check CI runs.

## 2. Why it matters
Every user journey (sign in, import, reports...) depends on this. Most importantly for a finance
app: logs never contain tokens or account numbers, errors never leak SQL or another user's data,
and "today" is always India's date, so a payment at 00:30 IST on 1 Dec lands in December.

## 3. How it works (read in this order)
1. `services/api/app/core/config.py`: `Settings` (pydantic-settings). `validate_for_startup()`
   refuses unsafe combinations, e.g. dev login outside development.
2. `services/api/app/main.py`: `create_app(settings)` builds the app; tests build their own.
3. `services/api/app/core/middleware.py`: per request, assigns an id (`X-Request-ID`), adds security
   headers, enforces the 1 MB body limit, and writes one access log line with the *route template*
   (`/accounts/{account_id}`), never the real id.
4. `services/api/app/core/errors.py`: every error becomes `application/problem+json` with a stable
   `code`.
5. `services/api/app/core/logging.py`: JSON formatter plus a redaction filter.
6. `services/api/app/core/clock.py`, `app/database.py` (`get_db`), `app/api/health.py`.
7. `scripts/dev.py` and `.github/workflows/api-checks.yml`.

Flow of `GET /health/ready`: middleware sets the request id -> router -> the handler opens a DB
connection, reads `alembic_version`, compares it with the newest migration file -> 200 or 503 ->
middleware logs `{"msg": "request", "path": "/health/ready", "status": 200, ...}`.

## 4. Concepts
- **RFC 9457 problem details**: a standard JSON shape for HTTP errors.
- **ASGI middleware**: code wrapped around every request; written "raw" so context variables
  (the request id) are visible in all log lines of that request.
- **Context variable**: a per-request global; safe with concurrent requests.
- **Dependency injection (FastAPI `Depends`)**: handlers ask for a DB session or the clock; tests
  swap them for test versions.
- **Savepoint test isolation**: each test runs inside a transaction that is rolled back, so tests
  never leave data behind even when code calls `commit()`.
- **mypy --strict**: checks every type hint; catches whole classes of bugs before running.
- **OpenAPI drift check**: the committed `openapi.json` must equal what the code generates.

## 5. Verify it yourself (PowerShell, repo root)
```powershell
.\.venv\Scripts\python.exe -m pip install -e "services/api[dev]"
.\.venv\Scripts\python.exe scripts\dev.py up
.\.venv\Scripts\python.exe scripts\dev.py check
```
Expect a table at the end with nine `PASS` lines. Then `scripts\dev.py serve` and open
http://127.0.0.1:8000/health/ready: `{"status":"ready","database":"ok","migrations":"at_head"}`.
Stop Docker (`docker compose -f infra/docker-compose.yml stop`) and reload: you get 503.

## 6. Check your understanding
1. Why does the access log record `/api/v1/accounts/{account_id}` instead of the real URL?
2. A test calls a service that runs `session.commit()`. Why is the database still clean afterwards?
3. Why must `AUTH_MODE=dev` refuse to start when `APP_ENV=production`?

**Answers:** 1. The real URL contains ids (and could contain other identifiers); templates are
enough for debugging and leak nothing. 2. The test session is bound with
`join_transaction_mode="create_savepoint"`, so `commit()` only releases a savepoint inside an outer
transaction that the fixture rolls back. 3. Dev mode trusts a key pair on the developer's disk;
anyone who can mint dev tokens could sign in as anyone, so it must never run in production.
