# Backend progress

Claude Code: read this at the start of every session and update it after every completed task.
Keep it short and current. Newest entries at the top of each list.

MERGE_POLICY: auto-after-green-ci
<!-- Change to "wait-for-human" if Krishay wants to review each PR before it merges. -->

## Status
- Current milestone: M1 (M0 done)
- Status: IN PROGRESS
- Branch: `claude/hopeful-euler-ro7kla` (all milestones; see Decisions)
- Last updated: 2026-11-18

## Milestones
| ID | Name | Status | PR | Learning note |
|---|---|---|---|---|
| pre | Ledger schema v2, fingerprints | done | #6 | (explained in chat) |
| M0 | Foundation and guardrails | done | branch (PR at end) | docs/learning/M0-foundation.md |
| M1 | Authentication and user isolation | todo | | |
| M2 | Accounts, categories, balances, transaction reads | todo | | |
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
- 2026-11-18 M0: `scripts/dev.py check` all 9 steps PASS on PostgreSQL 17.12 (Docker), Python
  3.12.3, Linux cloud session. 88 tests pass in ~2 s; coverage 92%; mypy --strict clean.
- 2026-11-18 baseline: before any change, the existing 48 tests passed against PostgreSQL 17.
