# Backend progress

Claude Code: read this at the start of every session and update it after every completed task.
Keep it short and current. Newest entries at the top of each list.

MERGE_POLICY: auto-after-green-ci
<!-- Change to "wait-for-human" if Krishay wants to review each PR before it merges. -->

## Status
- Current milestone: M0 (not started)
- Status: READY
- Last updated: 2026-11-12 (handoff written)

## Milestones
| ID | Name | Status | PR | Learning note |
|---|---|---|---|---|
| pre | Ledger schema v2, fingerprints | done | #6 | (explained in chat) |
| M0 | Foundation and guardrails | todo | | |
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
- 2026-11-12: Auth provider is Supabase Auth, verified locally with JWKS (Krishay's choice).
- 2026-11-12: Money stays NUMERIC(18,2) + Decimal (ADR-0002); JSON money is a string.

## Blockers
(none)

## Evidence log
(Commands run and their results that prove a milestone works, e.g. test counts, timings, backup dry run.)
