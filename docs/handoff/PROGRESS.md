# Backend progress

Claude Code: read this at the start of every session and update it after every completed task.
Keep it short and current. Newest entries at the top of each list.

MERGE_POLICY: auto-after-green-ci
<!-- Change to "wait-for-human" if Krishay wants to review each PR before it merges. -->

## Status
- Current milestone: M3 (M0-M2 done)
- Status: IN PROGRESS
- Branch: `claude/hopeful-euler-ro7kla` (all milestones; see Decisions)
- Last updated: 2026-11-18

## Milestones
| ID | Name | Status | PR | Learning note |
|---|---|---|---|---|
| pre | Ledger schema v2, fingerprints | done | #6 | (explained in chat) |
| M0 | Foundation and guardrails | done | branch (PR at end) | docs/learning/M0-foundation.md |
| M1 | Authentication and user isolation | done | branch (PR at end) | docs/learning/M1-authentication.md |
| M2 | Accounts, categories, balances, transaction reads | done | branch (PR at end) | docs/learning/M2-accounts-balances.md |
| M3 | CSV import pipeline | todo | | |
| M4 | Ledger integrity | todo | | |
| M5 | Jobs and categorization | todo | | |
| M6 | Reports and budgets | todo | | |
| M7 | Week-2 gate: export, restore, isolation, end-to-end | todo | | |
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
- 2026-11-18 M2: `dev.py check` all PASS; 214 tests; coverage 97%. Isolation harness covers
  accounts (+balance, reconciliation, opening balance), categories, transactions.
- 2026-11-18 M1: `dev.py check` all PASS; 163 tests; coverage 95%. Concurrency test: 4 threads
  first-request the same `sub`, exactly 1 user and 21 categories exist afterwards.
- 2026-11-18 M0: `scripts/dev.py check` all 9 steps PASS on PostgreSQL 17.12 (Docker), Python
  3.12.3, Linux cloud session. 88 tests pass in ~2 s; coverage 92%; mypy --strict clean.
- 2026-11-18 baseline: before any change, the existing 48 tests passed against PostgreSQL 17.
