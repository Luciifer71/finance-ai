# Backend handoff: Finance AI private beta

Written 11 Nov 2026 for Claude Code. Owner: Krishay Shah (backend). This is the **source of truth**
for all backend work up to `v0.1-private-beta`. `CLAUDE.md` holds the short rules; this file holds
the detail. If this file and the code disagree, the code shows what exists and this file shows what
to build. Record any deliberate deviation in `docs/handoff/PROGRESS.md` with the reason.

---

## 0. How to use this document

1. Read `CLAUDE.md`, then this file in full, then `docs/handoff/PROGRESS.md`.
2. Find the first milestone that is not marked done in `PROGRESS.md`. Continue from there.
3. For each milestone: create its branch from up-to-date `main`, build it, test it, write its learning
   note, update `PROGRESS.md`, open the PR, wait for green CI, merge, then pull `main`.
4. Section 6 (financial rules) is **normative**. Every rule there needs at least one test whose
   expected value was calculated by hand and written into the test as a literal.

---

## 1. Product

**One sentence:** a private place for each of us to see where our money goes, without recording
every UPI payment by hand, and to know what we can afford next.

Core user journeys the backend must support (from the project roadmap):
1. Sign in to a **separate, private** account. User A can never see anything of user B's.
2. Create bank/cash/wallet/credit accounts and set an opening balance.
3. **Import a CSV bank statement**: upload, preview, confirm. Re-importing adds nothing.
4. Review normalized transactions with clear **verified / estimated** balance labels.
5. See totals by **day / week / month / year** and by category; search transactions.
6. Edit a transaction's category and notes. Pair transfers. Match refunds. Every change is audited.
7. Set **monthly budgets** and get warnings before and after overspending.
8. Keep a **wishlist** and **savings goals** with target price and deadline, a full history of
   changes and contributions, a projected completion date and "what if I buy this now?" scenarios.
9. See a transparent **cash-flow forecast** with assumptions and confidence.
10. Read **explainable insights** (top categories, unusual spending, upcoming recurring payments).
11. Ask a **read-only assistant** questions answered only from real records, with citations.
12. Export all of my data; the operator can back up and restore the database.

Reality check that shapes everything: Indian banks and UPI apps do not offer a lawful,
free, real-time API for an app like this. **CSV statement import is the primary data source for the
beta.** Never claim an account is "connected" or a balance is "live".

---

## 2. Current state of `main` (11 Nov 2026)

Merged PRs #1-#6. Verified: 48 tests pass locally (about 2 s) and in CI.

| Area | What exists |
|---|---|
| App | `app/main.py`: FastAPI app with only `GET /health`. No auth, no routers, no settings module. |
| DB access | `app/database.py`: `create_db_engine`, `create_session_factory`, `get_session(factory)` (not yet usable as a FastAPI dependency). |
| Domain | `app/domain/finance.py`: frozen `Transaction` dataclass with amount validation, `TransactionType` (income, expense, transfer, refund), `calculate_net_cashflow`, `is_duplicate`. `app/domain/fingerprint.py`: `StatementRow`, `transaction_fingerprint`, `fingerprint_rows` (occurrence-numbered SHA-256). |
| Schema | Alembic `1173a26c2b83` (initial) and `2b6f0c9d4e71` (ledger v2). Tables: `users`, `financial_accounts`, `categories`, `transaction_imports`, `transactions`, `balance_snapshots`. Composite `(id, user_id)` foreign keys on every cross-table link. See `docs/adr-0002-ledger-data-model.md`. |
| Tests | `test_finance.py`, `test_fingerprint.py`, `test_health.py`, `test_database.py`, `test_postgres_integrity.py` (savepoint-isolated, refuses to run unless the URL is `finance_test` on 127.0.0.1:5432 and differs from `DATABASE_URL`). |
| CI | `api-checks.yml` (Postgres 17 service, `alembic upgrade head`, `alembic check`, pytest, ruff lint + format), `secret-scanning.yml` (Gitleaks, full history), `mobile-checks.yml` (partner's). |
| Other | `infra/docker-compose.yml` (Postgres 17, bound to 127.0.0.1). `.env.example`. README says the venv lives in `services/api`; on Krishay's machine it lives at the repo root (fix the README in M0). |
| Branches | `feat/account-service` holds an unmerged `AccountCreate` schema; it is **superseded by M2**. Do not merge or delete it. `feat/mobile-foundation` belongs to the partner. Do not touch. |

Existing columns you must know (do not change their meaning):
- `transactions`: `id, user_id, account_id, import_id, category_id, amount (>0), direction
  (debit|credit), transaction_type (income|expense|transfer|refund), description, source, external_id,
  fingerprint (unique per account), posted_on (DATE), occurred_at (nullable), transfer_group_id,
  refund_of_id, created_at`. DB checks: expense must be debit; income and refund must be credit;
  `transfer_group_id` only on transfers; `refund_of_id` only on refunds and never self.
- `transaction_imports`: `account_id, source, file_sha256 (unique per account), status
  (pending|processing|completed|failed), rows_total, rows_imported, rows_skipped, rows_failed,
  error_message, completed_at`.
- `balance_snapshots`: `account_id, import_id, as_of, balance (may be negative), source
  (statement|user_entered)`; a statement snapshot must reference an import.

---

## 3. Scope

### Backend (you build this)
Everything in milestones M0-M13 below, plus stretch items only after M13 is done.

### Partner (do NOT build)
The Expo / React Native app in `apps/mobile`: screens, navigation, design, on-device token storage,
offline SQLite cache, accessibility, mobile CI, device testing. Do not edit `apps/mobile/**` or
`.github/workflows/mobile-checks.yml`.

### What the backend owes the partner (build this so she can work independently)
- A stable, versioned API at `/api/v1` with complete OpenAPI, committed as
  `packages/contracts/openapi.json` and kept in sync by a CI check.
- `packages/contracts/README.md` explaining auth, money-as-string, dates, errors and pagination,
  with one example request/response per endpoint group.
- A **seed script** that creates two synthetic users (A and B) with accounts, three months of
  realistic transactions, budgets and goals, so the UI can be built against real API responses.
- A **dev token** command so the app can call the API before Supabase is configured (section 7.2).
- CORS configured from an environment variable (allow Expo dev origins in development only).

### Out of scope for the beta (do not build)
Live bank or UPI connections, credential storage, scraping, notification reading, Account Aggregator
integration, PDF statement parsing (stretch), email receipt ingestion, push notifications, payments,
multi-currency, shared/family accounts, App Store work.

---

## 4. Technology

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (typed `Mapped`), Alembic, PostgreSQL 17,
psycopg 3, pytest, ruff. Keep these.

Add these runtime dependencies (pin with compatible ranges in `pyproject.toml`):
- `pydantic-settings`: typed configuration from environment variables.
- `PyJWT[crypto]`: JWT verification with JWKS (`PyJWKClient`).
- `python-multipart`: file uploads.

Add these dev dependencies: `pytest-cov`, `hypothesis` (property tests for money and fingerprints),
`mypy` (strict for `app/`), and `freezegun` or an injectable clock (prefer the clock; see 5.4).

Anything else needs a one-line justification in `PROGRESS.md` (Decisions). Prefer the standard
library. **No** ORMs besides SQLAlchemy, no task queues that need Redis or RabbitMQ (the jobs queue
is PostgreSQL), no pandas in the API path (stretch ML may use scikit-learn in an optional extra).

---

## 5. Architecture and code conventions

### 5.1 Layout (inside `services/api/app/`)
```
core/        config.py (Settings), security.py (JWT), errors.py (problem details), logging.py,
             clock.py, rate_limit.py, ids.py
api/v1/      one router per module: accounts.py, categories.py, transactions.py, imports.py,
             transfers.py, refunds.py, reports.py, budgets.py, goals.py, forecasts.py,
             insights.py, assistant.py, exports.py, me.py; router.py mounts them
services/    one module per use-case area; owns DB transactions (commit/rollback)
repositories/ user-scoped data access; every public function takes `user_id` first
domain/      pure functions and value objects; no I/O; Decimal only
schemas/     Pydantic request/response models
importers/   CSV reading, mapping profiles, normalization
jobs/        job handlers (categorize_import, detect_recurring, ...)
worker.py    `python -m app.worker`: polls the jobs table
main.py      app factory `create_app(settings)`; module-level `app = create_app()`
```
`services/workers/` and `services/ai/` stay as READMEs pointing to these modules (one deployable
API image runs both `uvicorn` and the worker command). Update those READMEs in M0.

### 5.2 Rules
- Type hints everywhere; `mypy --strict` passes for `app/`.
- Routers do no SQL and no business rules. Services do no HTTP. Domain does no I/O.
- Every repository query on a user-owned table filters `user_id == current_user.id`. A helper such as
  `get_owned_or_404(session, Model, id, user_id)` is the only way to fetch by id.
- Write money with `Decimal`, quantize to `Decimal("0.01")` with `ROUND_HALF_EVEN` only at defined
  boundaries (section 6.1). Never construct `Decimal` from a float.
- No `print`; use the logger. Never log request bodies, tokens, full descriptions or amounts at INFO.
- Docstrings explain **why**. Keep functions short. Name things after the domain (posted_on, not date1).

### 5.3 Database
- New tables follow the existing patterns: UUID primary keys, `user_id` FK, composite `(id, user_id)`
  unique + composite FKs for every link to another user-owned row, `created_at timestamptz default now()`.
- Every new constraint gets an explicit name. `alembic check` must stay green.
- Migrations must upgrade and downgrade cleanly. For each new revision, add a test (or a `dev.py`
  step) that runs `upgrade head -> downgrade -1 -> upgrade head` on a scratch database.
- Never edit `1173a26c2b83` or `2b6f0c9d4e71` or any other merged revision.

### 5.4 Time
- Inject a `Clock` (`now() -> datetime` in UTC, `today() -> date` in `Asia/Kolkata`) through FastAPI
  dependencies so tests can freeze time. **Reporting timezone is `Asia/Kolkata`.**
- `posted_on` is a calendar date and is never converted between time zones.
- Weeks are ISO weeks (Monday to Sunday). Months and years are calendar months and years.

---

## 6. Financial rules (normative)

### 6.1 Money
- Storage `NUMERIC(18,2)`; Python `Decimal`; JSON string with exactly two decimals (`"20.00"`).
- Input parsing accepts `"1,23,456.70"` (Indian grouping), `"123456.7"`, `"₹ 1,200"`; rejects
  anything with more than two decimals, scientific notation, NaN/Infinity, or empty strings.
- Amounts on transactions are always **positive**; the sign lives in `direction`.
- Sums are exact. Averages, projections and rates are computed in `Decimal` and quantized to 2 dp
  with `ROUND_HALF_EVEN` only when returned. Percentages are returned as strings with 1 dp.

### 6.2 Signed amount and balances
- `signed_amount = +amount` for `credit`, `-amount` for `debit` (from the account's point of view).
- **Computed balance on date D** for an account = balance of the latest snapshot with `as_of <= D`
  (statement snapshots win over user-entered on the same date) + sum of `signed_amount` for
  transactions with `snapshot.as_of < posted_on <= D`. With no snapshot at all: start from zero and
  mark the result as having no anchor.
- **Statement snapshot semantics:** a statement closing balance on `as_of` already includes every
  transaction posted on or before `as_of`.
- **Balance status** (returned with every balance as `status` + `reason`):
  - `verified`: the anchor is a statement snapshot, no transactions exist after `as_of`, and the
    reconciliation check below passes. Also return `verified_as_of`.
  - `estimated`: anything else. Reasons: `no_statement`, `transactions_after_statement`,
    `user_entered_anchor`, `no_anchor`, `reconciliation_mismatch`.
- **Reconciliation:** for two consecutive statement snapshots S1 < S2 on the same account,
  `S1.balance + sum(signed_amount, S1.as_of < posted_on <= S2.as_of)` must equal `S2.balance`.
  A mismatch is reported (with the difference) and forces `estimated`. Never "fix" it silently.

### 6.3 What counts as spending and income
For any period [start, end] (inclusive, by `posted_on`):
- `gross_spending` = sum of `expense` amounts.
- `refunds` = sum of `refund` amounts.
- `net_spending` = `gross_spending - refunds` (may be negative if refunds exceed spending).
- `income` = sum of `income` amounts.
- `net_cash_flow` = `income + refunds - gross_spending` (equals `calculate_net_cashflow`).
- **Transfers are excluded from all of the above.** Cash withdrawals paired to a cash account are
  transfers; spending then happens when cash expenses are recorded.
- A refund counts in the period of **its own** `posted_on`.
- **By category:** an expense counts in its category (`Uncategorized` if none). A refund linked via
  `refund_of_id` reduces the **original transaction's** category; an unlinked refund reduces its own
  category, or `Uncategorized`.

### 6.4 Default classification on import
- `debit` rows become `expense`, `credit` rows become `income`, unless a rule below or the user says
  otherwise. Reclassification later is an audited event (6.7).
- Classification suggestions (never auto-applied unless stated):
  - **Transfer pair:** same user, two different accounts, opposite directions, equal amounts,
    `posted_on` within 3 days of each other, neither already paired. If exactly one candidate exists
    for a row **and** either description contains a self-transfer hint (`SELF`, `OWN A/C`, `OWN ACCOUNT`,
    the other account's last 4 digits if the user stored them), the pair **is** applied automatically
    with event actor `system`. Otherwise it is only suggested.
  - **ATM / cash withdrawal:** description matches `ATM`, `CASH WDL`, `CASH WITHDRAWAL`, `NWD`. If the
    user has exactly one `cash` account, suggest a transfer into it; if they have none, suggest
    category "Cash withdrawal".
  - **Refund:** a `credit` whose normalized merchant matches a prior `expense` in the same account
    within 60 days, with `amount <= original amount`, is suggested as a refund of the most recent match.
- Confirming a suggestion changes `transaction_type` (and the debit side of a transfer stays
  `debit`); the DB checks from migration `2b6f0c9d4e71` must hold.

### 6.5 Refund limits
- A refund's amount must be `<=` the original's amount, and the **sum** of all refunds linked to one
  original must be `<=` the original's amount. Enforce in the service (with a row lock on the original)
  and test the boundary (exactly equal is allowed; one paisa more is rejected).

### 6.6 Transfer integrity
- A `transfer_group_id` has exactly one `debit` and one `credit` row, equal amounts, different
  accounts, same user. Enforce in the service; add a DB constraint trigger if feasible; test it.
- Unpairing restores each side's previous type (from the audit event) and is itself audited.

### 6.7 Immutability and audit
- **Source facts never change after insert:** `account_id, amount, direction, posted_on,
  occurred_at, description, source, external_id, fingerprint, import_id`. Enforce with a PostgreSQL
  `BEFORE UPDATE` trigger that raises if any of these change, and test that the DB rejects it.
- **User-editable fields:** `category_id, transaction_type, transfer_group_id, refund_of_id, notes`
  (add `notes VARCHAR(1000)` and `category_source` = `rule|user|system|none`).
- Every change to an editable field writes an append-only `transaction_events` row in the **same DB
  transaction**: `id, user_id, transaction_id, event_type, before (jsonb), after (jsonb),
  actor (user|system|rule), reason, created_at`. Events are never updated or deleted (trigger).
- **Manual transactions** (`source = 'manual'`) are allowed; their fingerprint is
  `sha256("manual" + uuid)`. **Adjustments** are recorded as a `user_entered` balance snapshot, never
  as a fake transaction.
- Deleting a transaction is not supported in the beta. A user can mark one `excluded` (add
  `is_excluded BOOLEAN`, audited) so it disappears from reports while the fact remains.

### 6.8 Budgets
- A budget = user + category (or `NULL` for "all spending") + month (`YYYY-MM`) + amount, plus
  `warn_at_percent` (default 80) . Unique per (user, category, month).
- `spent` = `net_spending` for that category and month (6.3), floored at 0 for status purposes.
- `status`: `ok` if `spent < warn_threshold`; `warning` if `warn_threshold <= spent < amount`;
  `over` if `spent >= amount`. `warn_threshold = amount * warn_at_percent / 100`.
  Boundary tests: exactly at warn threshold is `warning`; exactly at amount is `over`.
- **Month-end projection** (only for the current month): if fewer than 7 days have elapsed, return
  `projection: null, reason: "too_early_in_month"`. Otherwise
  `projected = spent / days_elapsed * days_in_month` (days_elapsed includes today), and
  `may_exceed = projected >= amount`. Return the formula inputs.

### 6.9 Goals and wishlist
- Goal: `name, kind (wishlist|savings), target_amount, target_date (nullable), item_url (nullable,
  http/https only), priority (1-5), status (active|achieved|abandoned)`.
- Append-only `goal_events`: `created, target_changed, date_changed, contribution, withdrawal,
  status_changed, note`, each with `amount` where relevant, `before/after` jsonb, `created_at`.
- `saved = sum(contributions) - sum(withdrawals)`; can never go below zero (reject the event).
  Contributions are **earmarks**, not ledger transactions; they never change account balances.
- When `saved >= target_amount` and status is `active`, the service records `status_changed ->
  achieved` (actor `system`).
- **Projection (fixed saving rate):** input `monthly_saving > 0`.
  `remaining = max(target - saved, 0)`; `months_needed = ceil(remaining / monthly_saving)`;
  `projected_date = today + months_needed months` (same day-of-month, clamped to month end).
  If `target_date` is set: `required_monthly = ceil_to_paisa(remaining / months_until_target)`, where
  `months_until_target` = whole months from today to target_date, minimum 1; `on_track =
  monthly_saving >= required_monthly`. Return all inputs as assumptions.
- **Default monthly_saving** when not given: the median of the last 3 complete months'
  `net_cash_flow`, if at least 2 complete months exist and the median is positive; else return
  `insufficient_history`.
- **"What if I buy this now?"** input `amount`, optional `account_id`. Output: the account's
  computed balance after purchase (with its status), the change to the current month's net spending
  and every affected budget's new status, and for each active goal the delay in months, treating the
  purchase as money that would otherwise have been saved:
  `delay = ceil((remaining + amount) / rate) - ceil(remaining / rate)` where `rate` is the goal's
  monthly saving (6.9 default). Purely hypothetical: **nothing is written.**

### 6.10 Cash-flow forecast (v1, transparent baseline)
- Needs at least **60 days** of transactions spanning at least **2 complete calendar months**; else
  `status: "insufficient_history"` with what is missing.
- For the next N months (default 3, max 6): per category, baseline = median of the last 3 complete
  months (or 2 if only 2 exist) of `net_spending`; income baseline the same way.
  `projected_net = income_baseline - sum(category baselines)`.
- Range: `low/high = projected_net -/+ k * MAD` where MAD is the median absolute deviation of the
  last complete months' net cash flow and k = 1.5. State k and MAD in the assumptions.
- Confidence: `low` with 2 complete months, `medium` with 3-5, `high` with 6 or more and MAD below
  25% of the mean absolute net.
- Seasonality: only if 12+ complete months exist, multiply each category baseline by
  `same_month_last_year / mean_of_last_12_months` (capped between 0.5 and 2.0); otherwise state
  `seasonality: "not_applied_insufficient_history"`.
- Always return `assumptions` (list of plain sentences) and `data_window`.

### 6.11 Insights (deterministic rules; each cites source transaction ids)
- **Top categories:** this month vs last month, top 5 by net spending, with change amounts and
  percentages (percentage is `null` when last month was 0).
- **Unusual transaction:** an expense whose amount > `median + 3 * MAD` of the same category's
  expenses over the previous 90 days, with at least 5 samples, and MAD > 0.
- **Recurring payment due:** same normalized merchant, amounts within 10% of their median, at least
  3 occurrences, consecutive gaps between 26 and 35 days; `next_expected = last + median_gap`.
  Report those due in the next 14 days.
- **Budget at risk:** any budget with `may_exceed = true`.
- Each insight: `type, title, explanation (plain sentence with the numbers), amount fields,
  source_transaction_ids, generated_at`.

### 6.12 Merchant normalization (shared by rules, refunds, recurring)
Uppercase; strip UPI handles and reference numbers (`UPI/`, `@ybl`, `@okaxis`, digit runs of 6+),
collapse spaces; keep the first meaningful 3 tokens. Pure function with table-driven tests on at
least 20 synthetic descriptions.

---

## 7. API conventions

### 7.1 General
- Base path `/api/v1`. JSON only (except the upload and export endpoints).
- Errors: RFC 9457 `application/problem+json` with `type, title, status, detail, instance` and a
  stable `code` (e.g. `import.file_too_large`). Never include stack traces, SQL or user data.
- Validation errors: 422 problem with a list of `{field, message}`.
- Pagination: cursor-based on `(posted_on DESC, id DESC)`; `limit` 1-200 (default 50); response
  `{items, next_cursor}`. Cursors are opaque base64url strings.
- Dates `YYYY-MM-DD`; timestamps ISO 8601 UTC with `Z`. Money strings as 6.1.
- Request id: accept `X-Request-ID` or generate one; return it; include it in every log line.

### 7.2 Authentication (Supabase Auth, verified locally)
- Every `/api/v1` endpoint requires `Authorization: Bearer <JWT>`; only `/health`, `/health/ready`
  and the OpenAPI docs (development only) are public.
- **`AUTH_MODE=jwks` (default, used with Supabase):** verify with `PyJWKClient(AUTH_JWKS_URL)` (cached), allowed algorithms from
  `AUTH_ALGORITHMS` (default `ES256,RS256`), and check `iss == AUTH_ISSUER`, `aud == AUTH_AUDIENCE`
  (default `authenticated`), `exp`, `nbf`, `iat` with 30 s leeway, and that `sub` is a UUID. Supabase
  publishes keys at `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` and the issuer
  is `https://<project-ref>.supabase.co/auth/v1`. Confirm against Supabase's current docs before
  implementing; reject `HS256` and `none`.
- **Dev mode** (`AUTH_MODE=dev`): a local ES256 key pair generated into an ignored file
  (`.dev-keys/`), served through the same verification path, and `scripts/dev.py token <email>` mints
  a token. The app **refuses to start** with `AUTH_MODE=dev` unless `APP_ENV=development`; test this.
- **Tests** mint tokens with a test key pair injected via dependency override. No network in tests.
- **Just-in-time provisioning:** first valid request for a new `sub` creates the `users` row (store
  `auth_subject` = `sub`, unique; email lower-cased from the token) and seeds default categories, in
  one transaction, safe under concurrent first requests (use `INSERT ... ON CONFLICT DO NOTHING`).
- `GET /api/v1/me` returns the user's id, email and created_at.
- Tokens and the `Authorization` header never appear in logs or errors (test with `caplog`).

### 7.3 Endpoints to build (minimum; add only what a journey needs)
```
GET    /health                          liveness, no DB
GET    /health/ready                    DB reachable + migrations at head
GET    /api/v1/me
GET|POST            /api/v1/accounts            list (include computed balance + status) / create
GET|PATCH           /api/v1/accounts/{id}       detail / rename, archive (no delete)
POST                /api/v1/accounts/{id}/opening-balance
GET                 /api/v1/accounts/{id}/balance?as_of=
GET                 /api/v1/accounts/{id}/reconciliation
GET|POST            /api/v1/categories ; PATCH /api/v1/categories/{id} (rename, archive)
GET                 /api/v1/transactions        filters: account_id, category_id, type, from, to,
                                                q (description search), min_amount, max_amount,
                                                include_excluded; cursor pagination
POST                /api/v1/transactions        manual transaction
GET|PATCH           /api/v1/transactions/{id}   detail with events / category, notes, excluded, type
GET                 /api/v1/transactions/{id}/events
GET                 /api/v1/import-profiles     available CSV mapping profiles
POST                /api/v1/imports             multipart: file, account_id, profile_id
GET                 /api/v1/imports ; GET /api/v1/imports/{id}   status, counts, preview rows
POST                /api/v1/imports/{id}/commit
POST                /api/v1/imports/{id}/cancel
GET                 /api/v1/transfers/suggestions ; POST /api/v1/transfers (pair) ;
DELETE              /api/v1/transfers/{group_id} (unpair, audited)
GET                 /api/v1/refunds/suggestions ; POST /api/v1/refunds (link)
GET                 /api/v1/reports/summary?period=day|week|month|year&date=
GET                 /api/v1/reports/timeseries?granularity=day|week|month|year&from=&to=
GET                 /api/v1/reports/categories?from=&to=
GET|POST            /api/v1/budgets ; GET|PATCH|DELETE /api/v1/budgets/{id}
GET                 /api/v1/budgets/status?month=
GET|POST            /api/v1/goals ; GET|PATCH /api/v1/goals/{id}
POST                /api/v1/goals/{id}/events   contribution | withdrawal | note
GET                 /api/v1/goals/{id}/projection?monthly_saving=
POST                /api/v1/scenarios/purchase  "what if I buy this now?"
GET                 /api/v1/forecasts/cashflow?months=
GET                 /api/v1/insights
POST                /api/v1/assistant/ask
GET                 /api/v1/jobs/{id}           status of background work the user started
GET                 /api/v1/export              zip of JSON + CSV of all the user's data
```

---

## 8. CSV import (the main data path)

### 8.1 Upload validation
- Max 5 MB (configurable), extension `.csv`, content must decode as UTF-8 (accept BOM) or fall back
  to cp1252 only if UTF-8 fails; reject files containing NUL bytes; max 20,000 data rows; reject
  empty files and files with no recognizable header (within the first 30 lines; banks put
  preamble lines above the header).
- The raw file is **never stored**. Store only `file_sha256`, size, profile, row results.
- Uploading a file whose hash already has a **completed** import for that account returns 409
  `import.already_imported` with the existing import id. A failed or cancelled import with the same
  hash may be retried (reuse or replace the row; record which in the decision log).

### 8.2 Mapping profiles (data, not code branches)
A profile describes: header detection keywords, column names for date, value date, narration,
reference, debit amount, credit amount (or single amount + Dr/Cr column), closing balance, date
formats to try (`%d/%m/%y`, `%d/%m/%Y`, `%d-%b-%Y`, `%d-%m-%Y`), rows to ignore (blank, "Opening
Balance", totals footer).

Ship two profiles:
1. `generic_indian_bank_v1`: Date, Narration, Chq./Ref.No., Value Dt, Withdrawal Amt., Deposit Amt.,
   Closing Balance (the layout most Indian bank CSV exports resemble). **Label it "synthetic, not yet
   verified against a real export"** in the API response until Krishay confirms it with a real
   redacted file (see `HUMAN_TODO.md`).
2. `simple_v1`: date, description, amount (negative = debit), reference (optional), balance (optional),
   for manual spreadsheets and tests.

### 8.3 Preview and commit
- `POST /imports` parses everything immediately (files are small) into a staging table
  `import_rows` (`import_id, row_number, raw_hash, parsed fields or null, status valid|invalid|
  duplicate_in_file|already_imported, error_code, error_message`). Store parsed fields only, not the
  raw line. Status of the import becomes `previewed` (extend the status check constraint:
  `pending, previewed, processing, completed, failed, cancelled`).
- Fingerprints use `app/domain/fingerprint.py` with the import's account id. Rows whose fingerprint
  already exists for the account are `already_imported`.
- Preview response: counts per status, first 50 rows, date range, detected closing balance, and
  warnings (e.g. "closing balances do not chain").
- `POST /imports/{id}/commit`: in **one DB transaction** insert all `valid` rows with
  `INSERT ... ON CONFLICT (account_id, fingerprint) DO NOTHING`, set `import_id` and `import_row_number`
  (new column), update counts (`rows_imported` = actually inserted), create a **statement balance
  snapshot** from the last row's closing balance if present, mark `completed`, and enqueue a
  `categorize_import` job (outbox: same transaction). Commit is idempotent: committing a completed
  import returns the same result.
- Running balance check: when every row has a closing balance, verify each row's
  `prev_closing + signed_amount == closing`; report mismatches as warnings in preview; never alter data.

### 8.4 Fixtures (synthetic only)
In `services/api/tests/fixtures/statements/`: a clean 12-row statement; one with preamble lines and a
totals footer; one with malformed rows (bad date, two amounts, no amount, text in amount); one with
identical same-day rows; two **overlapping** statements; a cp1252 file with `₹`; an empty file; a
file over the row limit (generated in the test, not committed). The acceptance test imports the clean
file, re-imports it (zero new rows), imports the overlapping one (only new rows added) and checks the
resulting balance and status by hand-calculated values.

---

## 9. Background jobs (PostgreSQL outbox)

- Table `jobs`: `id, user_id (nullable for system jobs), kind, payload jsonb, status
  (queued|running|succeeded|failed|dead), attempts, max_attempts (default 5), run_after, locked_by,
  locked_at, last_error (truncated, no user data), idempotency_key (unique), created_at, updated_at`.
- Enqueue inside the same DB transaction as the change that needs it.
- Worker: `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` where `status='queued' AND run_after <= now()`;
  mark running; run handler in its own transaction; on success `succeeded`; on exception increment
  attempts, `run_after = now() + backoff` (2^attempts seconds, capped at 15 minutes, with jitter),
  `failed` -> back to `queued`, and `dead` after `max_attempts`. Stale `running` jobs older than
  10 minutes are re-queued.
- Handlers must be idempotent. First handler: `categorize_import` (apply rules to that import's
  `category_source = none` rows; record events with actor `rule`).
- **Failure isolation test:** a handler that always raises leaves transactions readable, reports
  working, the job `dead` after 5 attempts, and the import `completed`.
- `python -m app.worker` runs the loop; `--once` processes available jobs and exits (used by tests).

## 10. Categorization
- Seed default categories per user on provisioning: Food & Dining, Groceries, Transport, Fuel,
  Shopping, Bills & Utilities, Rent, Entertainment, Subscriptions, Health, Education, Travel,
  Personal Care, Gifts & Donations, Fees & Charges, Cash withdrawal, Uncategorized (expense);
  Salary, Interest, Refunds & Cashback, Other income (income).
- `categorization_rules`: `user_id, pattern (normalized merchant substring), category_id, priority,
  created_from (seed|user)`. Ship a small synthetic seed rule set (e.g. SWIGGY, ZOMATO -> Food &
  Dining; UBER, OLA, RAPIDO -> Transport; NETFLIX, SPOTIFY -> Subscriptions).
- When a user changes a category in `PATCH /transactions/{id}` with `create_rule: true`, create a user
  rule for that merchant; user rules beat seed rules.
- Rules never override `category_source = user`.

## 11. Assistant (read-only, grounded)
- `POST /assistant/ask {question}` -> `{answer, intent, data, citations, limitations, declined}`.
- A deterministic **intent parser** (keywords + regex for periods like "this month", "last month",
  "in October", "this week", amounts like "₹45,000", category names from the user's categories) maps to
  allowed intents only: `spending_summary, category_breakdown, compare_periods` ("why did I spend
  more"), `budget_status, goal_status, affordability` ("can I afford X"), `forecast, top_merchants,
  find_transactions, balance`.
- Each intent calls the **same services** as the REST endpoints and fills an answer template with
  their numbers. `compare_periods` explains the difference using the top 3 category changes and
  cites the largest transactions behind them.
- **Decline** (with `declined: true` and suggestions) anything that asks to create, change, delete,
  move, pay or transfer, anything about other people's data, and anything unparseable. Never guess.
- `balance` answers include the balance status; an `estimated` balance is always called an estimate.
- Optional LLM (stretch S3) must sit behind a `LanguageModel` protocol, be **off by default**, and may
  only (a) map a question to an allowed intent as schema-validated JSON and (b) rephrase a computed
  answer; every number in the final text must appear in the computed data or the system falls back
  to the template answer. Tests use a fake model.

---

## 12. Security and reliability requirements
- Upload limits and validation as in 8.1. Request body limit on all other endpoints (1 MB).
- **CSV formula injection:** every exported CSV cell starting with `=`, `+`, `-`, `@`, tab or CR is
  prefixed with `'`. Test it.
- Only SQLAlchemy parameterized queries; no string-built SQL with user input (the one dynamic table
  name in tests is allowed).
- Rate limiting (in-process token bucket keyed by user id; per-IP for unauthenticated routes):
  defaults 120 requests/min general, 10 imports/hour, 5 exports/hour, 30 assistant asks/hour; 429
  problem with `Retry-After`. Configurable; documented as single-instance only.
- `access_audit` table: who exported data, imported files, or failed auth repeatedly (no tokens, no
  amounts). Export and import write an audit row.
- CORS from `CORS_ALLOW_ORIGINS`; security headers (`X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on `/api/v1`).
- Structured JSON logs with `request_id`, method, path template (not raw path with ids), status,
  duration, user id hash. A log filter redacts `authorization`, `token`, `password`, and long digit runs.
- `/health/ready` checks DB connectivity and that the Alembic revision equals head.
- Export: `GET /export` returns a zip with `transactions.csv`, `accounts.json`, `categories.json`,
  `budgets.json`, `goals.json` (with events), `imports.json`, `manifest.json` (counts + sha256 per file).
- **Restore test:** export user A, import the export into an empty database through a test-only
  restore function, re-export, and assert both manifests are identical.
- Operator backup: `scripts/dev.py backup` and `restore` using `docker compose exec postgres pg_dump
  -Fc` / `pg_restore` (container versions match). Do one real dry run locally and record it in
  `PROGRESS.md`.

---

## 13. Milestones (do them in this order)

Each milestone lists its roadmap days, the work, and **acceptance tests that must exist and pass**.
"Done" = acceptance tests pass, `dev.py check` green, CI green, learning note written, PROGRESS updated,
PR merged.

### M0: Foundation and guardrails (Day 2, 7)
- Dependencies from section 4; `core/config.py` (pydantic-settings; `APP_ENV`, `DATABASE_URL`,
  `AUTH_*`, `CORS_ALLOW_ORIGINS`, limits); app factory; problem-details errors; JSON logging with
  request id and redaction; `Clock`; session dependency (`get_db`) with commit/rollback in services.
- `services/api/tests/conftest.py`: shared fixtures (savepoint session reused from the integrity tests'
  pattern, API client with DB override, token factory, `user_a`/`user_b`).
- `/health` and `/health/ready`.
- `scripts/dev.py` (repo root, standard library only) with subcommands: `up` (docker compose up -d and
  wait for readiness), `createdb-test`, `migrate` (dev and test), `check` (migrate test db, alembic check,
  migration round-trip on a scratch db, pytest with coverage, ruff lint, ruff format check, mypy,
  OpenAPI drift check), `seed`, `token`, `backup`, `restore`, `export-openapi`. Use `127.0.0.1`.
- `packages/contracts/openapi.json` generated by `export-openapi`; a test fails if it is stale.
- CI: add mypy, coverage (`--cov-fail-under=85` overall; aim for 95%+ on `domain/`), OpenAPI drift.
  Keep every existing step.
- README: correct venv location, `dev.py` usage, Windows `127.0.0.1` note. Update `services/workers`
  and `services/ai` READMEs.
- **Acceptance:** existing 48 tests still pass; `GET /health/ready` returns 200 with DB up and 503 with
  a bad URL; a test proves logs never contain an `Authorization` header value; mypy strict passes.

### M1: Authentication and user isolation (Day 4)
- Migration: `users.auth_subject` (unique, not null for new rows; backfill not needed: tables are
  empty), email stored lower-case with a unique index on `lower(email)`.
- JWT verification (7.2), dev mode, JIT provisioning with default categories and seed rules,
  `get_current_user` dependency, `GET /me`.
- An **isolation test harness**: a registry or fixture that, for every user-scoped route, creates a
  resource as user A and asserts user B gets 404 on read, update and delete, and that list endpoints
  never include it. Every later milestone adds its routes to this harness.
- A test that walks the OpenAPI spec and asserts every `/api/v1` route returns 401 without a token.
- **Acceptance:** expired, wrong-issuer, wrong-audience, wrong-algorithm, tampered and unsigned tokens
  are rejected (401, no detail leakage); concurrent first requests create exactly one user; dev mode
  refuses to start outside development.

### M2: Accounts, categories, balances, transaction reads (Day 5, 8)
- Account CRUD (archive instead of delete; store optional `last4`), categories CRUD (archive; cannot
  archive `Uncategorized`), opening balance (user-entered snapshot), balance + status (6.2),
  reconciliation endpoint, transaction list/search/detail with cursor pagination, manual transaction
  create, transaction DTOs.
- **Acceptance:** hand-calculated balance tests for: no anchor; opening balance only; statement
  snapshot with no later rows (`verified`); statement then later rows (`estimated`,
  `transactions_after_statement`); two statements that reconcile; two that do not (difference reported);
  negative credit-card balance. Pagination returns every row exactly once across pages, including ties
  on `posted_on`. Transfers do not inflate spending (with the reports helper or a domain test).

### M3: CSV import pipeline (Day 6, 9, 10)
- Section 8 in full: validation, profiles, staging, preview, commit, statement snapshot, outbox enqueue
  (the jobs table may be created here with the handler arriving in M5), audit row.
- **Acceptance:** all fixtures from 8.4 behave as specified; re-import adds 0; overlapping import adds
  only new rows; identical same-day rows are both kept; malformed rows are reported with row numbers
  and codes and do not block valid rows; oversized and binary files are rejected with stable codes;
  user B cannot see or commit user A's import; property test: for random valid statements, import
  twice == import once.

### M4: Ledger integrity (Day 11)
- Immutability trigger, `transaction_events` + its append-only trigger, editable fields, `notes`,
  `is_excluded`, `category_source`, transfer suggestions/pair/unpair (6.4, 6.6), refund
  suggestions/link with limits (6.5), cash-withdrawal suggestion.
- **Acceptance:** DB rejects an UPDATE to `amount` even through raw SQL; every edit produces exactly one
  event with correct before/after; refund sum boundary tests; transfer pair of unequal amounts or same
  account rejected; unpair restores types; auto-pair only with the self-transfer hint and exactly one
  candidate; nothing in this milestone changes a source fact.

### M5: Jobs and categorization (Day 20, moved earlier on purpose)
- Section 9 and 10: worker, backoff, dead letters, stale lock recovery, `categorize_import`, rules,
  user rules from edits, `GET /jobs/{id}`.
- **Acceptance:** failure-isolation test (9); two workers never process the same job (test with two
  sessions and `SKIP LOCKED`); re-running a succeeded job is a no-op; user-categorized rows are never
  overwritten by rules.

### M6: Reports and budgets (Day 12, 13)
- Aggregations in SQL (`GROUP BY` on `posted_on` buckets), definitions from 6.3, summary/timeseries/
  categories endpoints, budgets CRUD + status + month-end projection (6.8).
- **Acceptance:** a fixture month with income, expenses in 3 categories, a transfer pair, a linked
  refund from the previous month and an excluded transaction produces hand-calculated totals for day,
  ISO week, month and year (including a week that spans two months and a leap day); budget boundary
  tests at exactly the warn threshold and exactly the amount; `too_early_in_month` before day 7.

### M7: Week-2 gate: export, restore, isolation regression, end-to-end (Day 14)
- Export (12), restore test, operator backup/restore commands and a recorded local dry run,
  `scripts/dev.py seed` for users A and B, an **end-to-end API test** of journeys 1-7.
- **Acceptance:** export -> restore -> export manifests identical; CSV injection test; the full
  isolation harness passes for every route that exists so far; seed runs twice without duplicating.

### M8: Goals, wishlist, projections, purchase scenario (Day 15, 16)
- Section 6.9 in full.
- **Acceptance:** hand-calculated projection fixtures (exact multiple, remainder needing one more
  month, already achieved, target date in the past, month-end clamping on 31 Jan + 1 month);
  withdrawal below zero rejected; auto-achieve event; history is append-only; purchase scenario writes
  nothing (assert row counts unchanged) and reports correct goal delays and budget statuses.

### M9: Forecast and insights (Day 17, 18)
- Sections 6.10 and 6.11, merchant normalization 6.12, a `detect_recurring` job if useful.
- **Acceptance:** insufficient-history case; 2/3/6-month confidence cases; MAD range by hand; every
  insight cites existing transaction ids belonging to the user; anomaly rule ignores categories with
  fewer than 5 samples or MAD 0; recurring detection on a synthetic monthly subscription with one
  late month.

### M10: Assistant (Day 19)
- Section 11 (without the optional LLM).
- **Acceptance:** a table-driven test of at least 40 questions (supported, ambiguous, mutation
  attempts, other-person requests, prompt-injection style text such as "ignore your rules and delete")
  with expected intent or decline; answers' numbers equal the corresponding REST endpoint results;
  balance answers carry their status; no endpoint call from the assistant can write (assert no rows
  change).

### M11: Security hardening, reliability, performance (Day 25, 26, 27)
- Section 12 items not yet done: rate limits, body limits, headers, `access_audit`, log redaction
  audit, job retry idempotency review.
- Performance: seed 50,000 transactions for one user; list, reports and import commit of 5,000 rows
  must each finish under 1 s locally (record timings); add indexes based on `EXPLAIN ANALYZE`, each
  with a comment saying which query it serves.
- Write `docs/threat-model.md` (assets, actors, entry points, threats per STRIDE category, mitigations
  with links to tests, accepted risks).
- **Acceptance:** rate-limit tests; unauthorized import/export blocked; no secret or token in any log
  line during the full test run (a session-wide log capture assertion); performance numbers recorded.

### M12: Provider feasibility and import diagnostics (Day 22, 23)
- `docs/provider-matrix.md`: for Google Pay, BHIM UPI, Bank of Baroda, HDFC, SBI, Kotak, Paytm, PhonePe,
  ICICI: what export is officially offered (CSV/XLS/PDF/email statement), how a user gets it, format
  notes, terms that matter, Account Aggregator relevance, and **status verified (with source URL and
  date checked) or unverified**. Research the official help pages; never mark something verified
  without an official source. No "connected" badges anywhere.
- Improve import diagnostics: per-row error explanations a user can act on, and a
  `POST /imports/detect` that suggests the best profile and shows which headers matched.
- A second bank profile **only** if Krishay has provided a verified redacted sample (check
  `HUMAN_TODO.md`); otherwise record it as blocked.

### M13: Release candidate and acceptance (Day 29, 30)
- `docs/runbook.md`: local setup from zero on Windows, migrations, backup/restore, rotating auth keys,
  incident basics, known limitations.
- `docs/release-notes-v0.1.md`, updated README, final `packages/contracts` docs.
- `scripts/dev.py demo`: runs the full demo script against a clean database through the HTTP API
  (journeys 1-12 for user A, plus a check that user B sees none of it) and prints a pass/fail table.
- Financial invariants test suite (from the roadmap): refund, bank transfer, cash withdrawal,
  duplicate imported line, timezone/day boundary, partial data, negative values, precise currency
  handling, missing balance, failed categorizer: one clearly named test each.
- **Do not create the release tag.** Add "tag v0.1-private-beta after review" to `HUMAN_TODO.md`.

### Stretch (only after M13, in this order; each its own PR)
- S1 Rule classifier vs lightweight model (TF-IDF + logistic regression in an optional `ml` extra) on a
  synthetic labeled set; report precision/recall per category in `docs/classifier-report.md`; ship
  only if it beats rules and keeps rules as fallback.
- S2 Receipt metadata schema and parser prototype on synthetic receipts; no product claims without a
  linked receipt.
- S3 Optional LLM for the assistant per section 11.
- S4 PostgreSQL row-level security as defense in depth (app role without BYPASSRLS, `SET LOCAL
  app.user_id`), with tests.
- S5 Second CSV profile when a verified sample exists.

---

## 14. Testing strategy
- **Domain:** pure unit tests plus `hypothesis` properties (e.g. sums never lose paise; fingerprints
  stable under whitespace/case changes; import twice == import once).
- **Repositories/services:** real PostgreSQL via the savepoint fixture. No mocking of the database.
- **API:** `TestClient` with dependency overrides for DB session, clock and auth keys.
- **Every financial expected value is a literal calculated by hand**, with a comment showing the
  arithmetic, never recomputed with the code under test.
- Name tests as behavior: `test_refund_exceeding_original_is_rejected`.
- Keep the suite fast (target under 60 s locally). Mark anything slower `@pytest.mark.slow` and run it
  in CI anyway.

## 15. Git and PR workflow
1. `git switch main && git pull` then `git switch -c feat/m<N>-<name>`.
2. Small commits; full `dev.py check` before each one.
3. Push and open a PR with `gh pr create` (title: conventional; body: What / Why / How verified /
   Learning note link). End PR bodies with a line saying they were generated with Claude Code.
4. Wait for CI (`gh pr checks --watch`). If a failure is infrastructure (HTTP 5xx, runner outage),
   re-run (`gh run rerun --failed`) up to 3 times with a few minutes between, then record a blocker.
   If it is your code, fix it.
5. Merge with a merge commit: `gh pr merge --merge --delete-branch`. Pull `main`.
6. If `gh` is unavailable or not authenticated: push the branch, record the PR as "to open" in
   `PROGRESS.md`, continue the next milestone on a branch created **from the previous milestone
   branch**, and note the stacking. Add "open and merge stacked PRs" to `HUMAN_TODO.md`.
7. If `PROGRESS.md` says `MERGE_POLICY: wait-for-human`, do steps 1-4, then stop and report instead
   of merging.

## 16. Learning notes (for Krishay)
After each milestone create `docs/learning/M<N>-<name>.md` (plain, simple English, about one page):
1. **What we built**, in two or three sentences a non-expert understands.
2. **Why** it matters for the app (connect it to a user journey).
3. **How it works**: the main files to read, in reading order, and the flow of one request.
4. **Concepts and tech** used (e.g. "JWKS", "outbox pattern", "ISO week"), each explained in 1-2 lines.
5. **How to verify it yourself**: exact commands (Windows PowerShell) and what output to expect.
6. **Three questions to test your understanding**, with short answers at the bottom.
Do not pad. Accuracy over length.

## 17. When to stop (otherwise keep going)
Stop, update `PROGRESS.md` (Status: BLOCKED) and summarize for Krishay only when:
- a step would require a secret, account or real data you do not have **and** no fake/dev path exists;
- a required check fails three times for reasons you cannot fix without weakening it;
- an instruction here conflicts with a non-negotiable in `CLAUDE.md`;
- `main` has moved in a way that conflicts with your branch and resolving it means changing someone
  else's work (for example the partner's files).
Anything needing a human but not blocking (Supabase project, real CSV sample, hosting, branch
protection, tagging) goes into `HUMAN_TODO.md` and you continue.

## 18. Definition of done for the backend beta
- M0-M13 merged; CI green on `main`; coverage gate met; mypy strict clean.
- `scripts/dev.py demo` passes on a clean database.
- `packages/contracts/openapi.json` current and documented.
- `docs/runbook.md`, `docs/threat-model.md`, `docs/provider-matrix.md`, release notes, and one
  learning note per milestone exist.
- `PROGRESS.md` shows every milestone done with links to PRs, and `HUMAN_TODO.md` lists exactly what
  Krishay must do before tagging.
