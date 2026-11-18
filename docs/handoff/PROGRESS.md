# Backend progress

Claude Code: read this at the start of every session and update it after every completed task.
Keep it short and current. Newest entries at the top of each list.

MERGE_POLICY: auto-after-green-ci
<!-- Change to "wait-for-human" if Krishay wants to review each PR before it merges. -->

## Status
- Current milestone: M8 (M0-M7 done)
- Status: IN PROGRESS
- Branch: `claude/hopeful-euler-ro7kla` (M0-M4 merged to main in PR #7; M5+ on the same branch)
- Last updated: 2026-11-18

## Milestones
| ID | Name | Status | PR | Learning note |
|---|---|---|---|---|
| pre | Ledger schema v2, fingerprints | done | #6 | (explained in chat) |
| M0 | Foundation and guardrails | done | #7 | docs/learning/M0-foundation.md |
| M1 | Authentication and user isolation | done | #7 | docs/learning/M1-authentication.md |
| M2 | Accounts, categories, balances, transaction reads | done | #7 | docs/learning/M2-accounts-balances.md |
| M3 | CSV import pipeline | done | #7 | docs/learning/M3-csv-import.md |
| M4 | Ledger integrity | done | #7 | docs/learning/M4-ledger-integrity.md |
| M5 | Jobs and categorization | done | (next PR) | docs/learning/M5-jobs-categorization.md |
| M6 | Reports and budgets | done | (next PR) | docs/learning/M6-reports-budgets.md |
| M7 | Week-2 gate: export, restore, isolation, end-to-end | done | (next PR) | docs/learning/M7-export-restore-seed.md |
| M8 | Goals, wishlist, projections, purchase scenario | todo | | |
| M9 | Forecast and insights | todo | | |
| M10 | Assistant | todo | | |
| M11 | Security, reliability, performance | todo | | |
| M12 | Provider matrix and import diagnostics | todo | | |
| M13 | Release candidate and acceptance | todo | | |

## Current task checklist
(Write the current milestone's task list here as you plan it; tick items as they finish.)

## Decisions
(Date, decision, reason. Include every dependency added and every deviation from the handoff.)
- 2026-11-18: From M5 on, commits carry a `Co-Authored-By: Claude` trailer (Krishay's request);
  author stays Krishay. Each milestone is pushed when done.
- 2026-11-18 M7: Export adds `transaction_events.json` (audit history is the user's data too) and
  puts balance snapshots inside `accounts.json`. Not exported: jobs, import staging rows,
  categorization rules, access_audit (operational). The manifest has no timestamp, and the zip uses
  fixed entry timestamps, so identical data gives an identical file.
- 2026-11-18 M7: CSV escaping also prefixes cells that start with `'`, so un-escaping is exact.
- 2026-11-18 M7: The restore function is test-only (`tests/export_restore.py`), restoring as a new
  user into a scratch database `finance_restore_scratch`.
- 2026-11-18 M7: Seed users `user.a@example.test` / `user.b@example.test`: 3 complete months before
  the current one plus the current month up to today; deterministic per user and month; ATM
  withdrawals paired to the wallet; one Amazon order with a linked partial refund; budgets for the
  current month.
- 2026-11-18: `scripts/dev.py demo` (app/tools/demo.py) built early (handoff lists it for M13)
  because manual testing in /docs was tiring and error-prone (Swagger pre-fills placeholder ids).
  It runs journeys 1-7 on a scratch database with 26 checked values; also a pytest, a CI step and
  the last step of `dev.py check`. M13 extends it to journeys 8-12.
- 2026-11-18 fix: found while Krishay tried /docs by hand. (1) Access log showed "/accounts"
  instead of "/api/v1/accounts" (FastAPI 0.16x reports routes without router prefixes); the
  middleware now rebuilds the full template. (2) Redaction mangled our own request ids (hex with 6+
  digits); request_id/user/job_id are exempt. (3) OpenAPI documented FastAPI's `{"detail": [...]}`
  422 shape; it now documents the real `application/problem+json` Problem/ValidationProblem and a
  401 on every /api/v1 operation (`core/openapi.py`).
- 2026-11-18 M6: Reports use SQL aggregation; a test checks SQL totals equal the pure Python
  definitions (`domain/reports.py`) for every day/week/month/year bucket of the fixture.
- 2026-11-18 M6: Timeseries returns every period in the range (empty ones as zeros); the first and
  last buckets are clipped to `from`/`to`; at most 400 buckets (422 `report.too_many_buckets`).
- 2026-11-18 M6: Category share percent is relative to total net spending, `null` when that total
  is 0 or negative. Expenses with no category and those in "Uncategorized" are one bucket.
- 2026-11-18 M6: Budget `spent` = the whole month's net spending (section 6.8 literally), so
  future-dated manual rows in the current month count. Budgets for income categories are refused.
  Budget month and category are fixed after creation (delete and recreate); budgets can be
  deleted (plans, not ledger facts). Projection outside the current month: `not_current_month`.
- 2026-11-18 M6: The isolation harness now treats every `*_id` field as an id (stricter leak check).
- 2026-11-18 M5: A claim counts as an attempt (attempts + 1 when a job starts), so a worker crash
  also uses an attempt; after an exception the job is `failed` until `run_after`, then the next
  poll returns it to `queued` (the handoff's "failed -> back to queued").
- 2026-11-18 M5: Jitter: delay = min(2^attempts, 900 s) x (0.75 + 0.25 x random).
- 2026-11-18 M5: `jobs.last_error` stores only the exception type name (messages may hold user data).
- 2026-11-18 M5: `enqueue` takes `run_after` from the injected clock (not the DB's `now()`); found
  because tests with a frozen clock failed once the real time passed the frozen time.
- 2026-11-18 M5: Rule precedence: user > seed, then lower priority (user 10, seed 100), then longer
  pattern. A rule only applies when its category kind fits the type (expense/refund -> expense,
  income -> income); transfers are never categorized. Rules match whole words of all merchant
  tokens. `create_rule` uses the 3-token normalized merchant as pattern and upserts.
- 2026-11-18 M4: Immutable fact columns (trigger): id, user_id, account_id, amount, direction,
  posted_on, occurred_at, description, source, external_id, fingerprint, import_id,
  import_row_number, created_at. DELETE on transactions is not blocked by a trigger (no code path
  deletes; a future "delete my account" may need it) - recorded as an accepted gap.
- 2026-11-18 M4: Transfer group validity is enforced in the service and by a DEFERRABLE INITIALLY
  DEFERRED constraint trigger (fires at commit; tests use SET CONSTRAINTS ALL IMMEDIATE).
- 2026-11-18 M4: `transaction_events.seq` (identity) orders events; `created_at` is identical for
  every event written in one DB transaction. One PATCH = one event (`category_changed`,
  `notes_changed`, `exclusion_changed`, `type_changed`, or `edited` for several fields); a no-op
  PATCH writes nothing. Other types: transfer_paired/unpaired, refund_linked.
- 2026-11-18 M4: PATCH type changes are limited to income <-> refund on credits; transfers only
  via pairing. If the current category no longer fits the new type it is cleared (in the event).
- 2026-11-18 M4: Auto-pair (actor system) runs inside the import commit transaction and requires
  mutual uniqueness: the new row has exactly one candidate and that candidate has exactly one.
  Manual pairing does not require the 3-day window (bank transfers can be slow).
- 2026-11-18 M4: Cash withdrawal confirmation (`POST /transfers/cash-withdrawals`) creates the cash
  side as a new row (source `cash_withdrawal`) and pairs it. Such a group cannot be unpaired (409):
  rows cannot be deleted, and leaving an "income" row would invent income. Fix via an adjustment.
- 2026-11-18 M4: Refund linking: original must be an expense; refund a non-transfer credit; any of
  the user's accounts (suggestions use the same account and a 60-day window). Linking the same pair
  twice is a no-op; an income-kind category on the refund is cleared.
- 2026-11-18 M4: Merchant normalization (6.12) implemented now for refunds: strips the `@provider`
  part of UPI handles but keeps the name, removes 6+ digit runs, filler words (incl. REFUND/ORDER)
  and repeated tokens, keeps 3 tokens. Number hints (last 4) use digit boundaries ("XX4321" matches).
- 2026-11-18 M3: A failed, cancelled or never-committed import of the same file (same account,
  same hash) is **deleted and replaced** on re-upload (its staging rows cascade); only a completed
  import gives 409 `import.already_imported`. A file rejected while parsing is recorded as a
  `failed` import (hash, size, message only) so the history shows it.
- 2026-11-18 M3: `duplicate_in_file` = an identical row (date, amount, direction, description) that
  also repeats a non-empty, non-placeholder reference number. Identical rows without a reference
  are all kept (occurrence numbers). References of all zeros are treated as "no reference".
- 2026-11-18 M3: CSV references are not written to `transactions.external_id` (banks reuse
  placeholder numbers, and a reversal can share its original's reference, which would hit
  `uq_tx_external_reference`). The reference still feeds the fingerprint and the preview.
- 2026-11-18 M3: Footer handling: rows starting "statement summary", "total", "***" or "end of
  statement" end the data; "opening balance"/"closing balance" rows are skipped. CSV is parsed with
  `strict=True` so an unterminated quote is an error instead of silently swallowing later rows.
- 2026-11-18 M3: Closing balance = balance of the last row in date order (newest-first files are
  detected). A second statement giving a different balance for a date that already has a statement
  snapshot keeps the first and adds warning `import.closing_balance_conflict`.
- 2026-11-18 M3: Accepted upload MIME types: text/csv, application/csv, text/plain,
  application/vnd.ms-excel (Windows labels .csv this way), application/octet-stream, empty.
- 2026-11-18 M3: The handoff's "cp1252 file with ₹" is impossible (₹ is not in cp1252); the fixture
  uses é and an en dash in cp1252, and ₹ is tested in UTF-8 files.
- 2026-11-18 M3: `jobs` and `access_audit` tables created now (handler in M5, rate limits in M11).
- 2026-11-18 M2: Balance reason when the anchor is user-entered: `no_statement` if the account has
  no statement snapshot on or before the date, else `user_entered_anchor`. Reason precedence:
  no_anchor > (user anchor) > reconciliation_mismatch > transactions_after_statement. Verification
  checks every consecutive statement pair up to the requested date.
- 2026-11-18 M2: Excluded transactions (M4) will still count in balances: exclusion hides a row from
  reports, but the money really moved. (Section 6.7 only says "disappears from reports".)
- 2026-11-18 M2: `POST /accounts/{id}/opening-balance` for a date that already has a user-entered
  snapshot replaces it (it is the user's own number, not a ledger fact).
- 2026-11-18 M2: Manual transactions may be income, expense or refund; transfers only come from
  pairing (M4). A category must be active and of matching kind (expense/refund -> expense
  category, income -> income category). `occurred_at` must include a time zone.
- 2026-11-18 M2: `Uncategorized` can be neither archived nor renamed (other code relies on it).
  Category names are unique per user ignoring case (service check; DB keeps the exact-match unique).
- 2026-11-18 M2: Money query parameters (`min_amount`, `max_amount`) use the same strict parser as
  bodies. The transaction DTO does not expose `fingerprint` (internal dedup detail).
- 2026-11-18 M1: Supabase facts checked via search of supabase.com docs (the docs host itself is
  blocked from the cloud session): JWKS at `<project>/auth/v1/.well-known/jwks.json`, issuer
  `<project>/auth/v1`, keys ES256 or RS256, and the JWKS may also list a legacy HS256 secret, which we
  never accept. JWKS cached 10 minutes (`PyJWKClient(lifespan=600)`).
- 2026-11-18 M1: `exp`, `iat`, `nbf` are checked against the injected `Clock` (30 s leeway), not by
  PyJWT against the wall clock, so tests with a frozen clock are deterministic. `nbf` is optional
  (Supabase does not document it as always present); `exp, iat, sub, iss, aud` are required.
- 2026-11-18 M1: Each key is pinned to one algorithm (JWK `alg`), defeating algorithm confusion.
  JWKS outage returns 503 `auth.keys_unavailable`, not 401.
- 2026-11-18 M1: A token without an `email` claim cannot create a user (401
  `auth.email_required`); an email already used by another `sub` gives 409 `auth.email_in_use`.
  Email is stored as first seen (lower-case) and not updated from later tokens.
- 2026-11-18 M1: `categorization_rules` table created in M1 (not M5) because the handoff wants seed
  rules created at provisioning. Rule patterns match whole words of the normalized merchant ("OLA"
  must not match "COCA COLA"); stricter than "substring" in section 10.
- 2026-11-18 M1: Existing `users` rows (dev databases only) get `auth_subject = 'legacy:<id>'` so the
  column can be NOT NULL without requiring an empty table.
- 2026-11-18 M1: The 401 route walk reads the OpenAPI spec (as the handoff says), not FastAPI's route
  objects (FastAPI 0.16x wraps included routers in private classes).
- 2026-11-18 M1: Dev tokens: same email -> same user id (`uuid5`), 24 h lifetime, issuer
  `finance-ai-dev`. The private key lives in `.dev-keys/` (ignored by Git), created on first use.
- 2026-11-18: **Git workflow deviation (Krishay's choice).** The cloud session may only push to
  `claude/hopeful-euler-ro7kla` and must not merge into `main`. All milestones are commits on that
  one branch (commit subjects say which milestone), pushed after each milestone, with ONE pull
  request to `main` at the end for Krishay to review and merge. Commits are authored as Krishay.
- 2026-11-18: Added `tzdata` (runtime): Windows has no system time zone database, and
  `zoneinfo.ZoneInfo("Asia/Kolkata")` fails without it.
- 2026-11-18: Settings read environment variables only; `scripts/dev.py` loads a repo-root `.env`
  into the environment for its subcommands (so `uvicorn` and tests never read `.env` implicitly).
- 2026-11-18: Ruff rules widened for `app/` and `tests/` (bugbear, bandit `S`, pyupgrade, `DTZ`
  naive-datetime ban, `RUF`). `E501` ignored for `migrations/` because merged revisions cannot be
  edited; `UP042` ignored to keep `TransactionType(str, Enum)` behaviour unchanged.
- 2026-11-18: Problem `type` is a URN (`urn:finance-ai:problem:<code>`) and `instance` is
  `urn:finance-ai:request:<request id>`, so errors never echo paths or ids.
- 2026-11-18: Log redaction replaces runs of 6+ digits (account/card/UTR numbers), bearer tokens,
  JWT-shaped strings and secret-named keys. Request ids are limited to `[A-Za-z0-9._-]{1,64}`.
- 2026-11-18: Migration round trip goes further than the handoff's `head -> -1 -> head`: it also
  runs `downgrade base -> upgrade head`, on a `finance_scratch` database (`dev.py
  migration-roundtrip`, also in CI). `dbadmin drop` refuses any database not named `*_scratch`.
- 2026-11-12: Auth provider is Supabase Auth, verified locally with JWKS (Krishay's choice).
- 2026-11-12: Money stays NUMERIC(18,2) + Decimal (ADR-0002); JSON money is a string.

## Blockers
(none)

## Evidence log
(Commands run and their results that prove a milestone works, e.g. test counts, timings, backup dry run.)
- 2026-11-18 M7: `dev.py check` all 10 steps PASS (incl. demo 26/26); 388 tests (~42 s); coverage
  96%. Export -> restore -> export manifests identical (17 transactions, events, refund, transfer,
  budgets). Seed run twice on the dev DB: 105/101 added, then 0/0. Operator backup dry run: backup
  88 KB (pg_dump 17.12), deleted budgets (6 -> 0), restore --yes -> 4 users / 231 transactions /
  179 events / 6 budgets, identical to before.
- 2026-11-18 M6: `dev.py check` all PASS; 371 tests (~35 s); coverage 97%. Feb 2028 fixture: month
  net 4250.00, leap day net -700.50, ISO week 28 Feb-5 Mar net -250.50, year net 6400.00;
  budget boundaries 799.99 ok / 800.00 warning / 1000.00 over; too_early before day 7.
- 2026-11-18 M5: `dev.py check` all PASS; 349 tests (~31 s); coverage 97%. Failing handler -> dead
  after 5 attempts, import still completed, 12 transactions and balance 34125.00 readable; SKIP LOCKED
  test with 3 real sessions; GitHub CI green for PR #7 before merge.
- 2026-11-18 M4: `dev.py check` all PASS; 330 tests (~25 s); coverage 97%. DB rejects raw-SQL
  updates to 7 fact columns; refund boundary 600+400=1000 ok, +0.01 rejected; auto-pair only with
  hint and a single candidate.
- 2026-11-18 M3: `dev.py check` all PASS; 263 tests; coverage 97%. Acceptance: clean import -> 12
  rows, balance 34125.00 verified; re-import -> 0; overlap -> +4, 91418.50 verified, reconciles;
  property test (25 random statements) import twice == import once.
- 2026-11-18 M2: `dev.py check` all PASS; 214 tests; coverage 97%. Isolation harness covers
  accounts (+balance, reconciliation, opening balance), categories, transactions.
- 2026-11-18 M1: `dev.py check` all PASS; 163 tests; coverage 95%. Concurrency test: 4 threads
  first-request the same `sub`, exactly 1 user and 21 categories exist afterwards.
- 2026-11-18 M0: `scripts/dev.py check` all 9 steps PASS on PostgreSQL 17.12 (Docker), Python
  3.12.3, Linux cloud session. 88 tests pass in ~2 s; coverage 92%; mypy --strict clean.
- 2026-11-18 baseline: before any change, the existing 48 tests passed against PostgreSQL 17.
