# Finance AI: guidance for Claude Code

## What we are building (read this first, every session)
A **private, iPhone-first personal finance app** for two people (Krishay and his partner). Each person
signs in to their own completely separate financial space. The app imports bank statements, keeps an
accurate ledger, shows spending by day/week/month/year, tracks budgets, wishlist items and savings
goals, forecasts cash flow, and answers questions like "Why did I spend more this month?" using only
the user's real records.

- **Krishay owns the backend** (`services/api`, plus `services/workers`, `services/ai`, `packages/contracts`).
  You are building his part. **His partner owns the mobile app** (`apps/mobile`). Never build or edit it.
- Krishay is a third-year CS student who wants to **learn** from this code. Clarity beats cleverness.
- Target: a dependable **private beta** (`v0.1-private-beta`), not an App Store release.

## Where the plan lives
- `docs/handoff/BACKEND_HANDOFF.md`: the full specification and milestone plan. **Source of truth.**
- `docs/handoff/PROGRESS.md`: what is done, what is next, decisions, blockers. **Read it before any
  work and update it after every completed task.** A future session must be able to resume from it alone.
- `docs/handoff/HUMAN_TODO.md`: things only Krishay can do. Add to it instead of stopping.
- `docs/adr-0002-ledger-data-model.md`: why the ledger schema looks the way it does.

## Non-negotiables (never break these)
1. **Money is `Decimal` / `NUMERIC(18,2)`. Never `float`.** In JSON, money is a string: `"1234.50"`.
2. **Every query on user data is scoped by `user_id`** through the repository layer. Another user's
   record returns **404**, never 403 and never the data.
3. **AI and heuristics never change ledger facts.** Numbers are computed by tested Python/SQL code.
   AI may only choose which report to run and phrase results that already exist.
4. **Never invent accuracy.** A balance is "verified" only when the rules in the handoff say so.
   Forecasts always return their assumptions and say "insufficient history" when data is thin.
5. **No secrets, tokens, real bank data or personal data in Git, logs, fixtures or error messages.**
   All fixtures are synthetic. Never read `.env`; use `.env.example`.
6. **Never edit a migration that is already on `main`.** Add a new Alembic revision instead.
7. **Never weaken a check to make it pass**: no skipped tests, no lowered coverage, no `# type: ignore`
   without a written reason, no disabled CI steps.
8. **Git safety:** never push to `main` directly, never force-push, never rewrite pushed history,
   never delete remote branches you did not create. Work on `feat/...` branches and merge through PRs.

## Environment facts (Windows laptop, Git Bash for your shell)
- The virtualenv is at the **repo root**: `.venv/`. Call Python explicitly:
  `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (Linux/macOS). Activation does not persist
  between your shell calls.
- PostgreSQL 17 runs in Docker: `docker compose -f infra/docker-compose.yml up -d`.
- **Always use `127.0.0.1`, never `localhost`** in database URLs. On this machine `localhost` tries
  IPv6 first and each connection hangs about 130 seconds (measured; see PR #6).
- Dev database: `postgresql+psycopg://finance:finance@127.0.0.1:5432/finance`
- Test database: `postgresql+psycopg://finance:finance@127.0.0.1:5432/finance_test`
  (the tests refuse to run if both URLs are equal; this is deliberate).
- After milestone M0 exists, run **all** checks with one command from the repo root:
  `.venv/Scripts/python.exe scripts/dev.py check`

## How to work
- Follow the milestone order in the handoff. Finish one milestone completely before the next.
- **Test first where it matters:** for money logic, write the failing test with a hand-calculated
  expected value, then the code.
- Small conventional commits (`feat(imports): ...`, `fix(ledger): ...`, `test(...)`, `docs(...)`),
  each one green. Run the full check before every commit.
- One branch and one PR per milestone: `feat/m<N>-<short-name>`. Merge only when every CI check is
  green (merge commit, not squash). If CI fails because of infrastructure (for example HTTP 5xx while
  downloading a tool), re-run it before touching code.
- When something is ambiguous: pick the most conservative option that keeps money correct and data
  private, record the decision in `PROGRESS.md`, and continue. Stop only for the reasons listed in the
  handoff's "When to stop" section.
- When you need current external facts (library APIs, Supabase auth, provider export options), check
  the official documentation instead of relying on memory.
- After each milestone, write the learning note described in the handoff (`docs/learning/`), in simple
  language, for Krishay.

## Architecture in one picture
```
HTTP request
  -> app/api/v1/<module>.py       (FastAPI router: parse input, call service, shape output)
  -> app/services/<module>.py     (use cases, DB transactions, rules; no HTTP objects)
  -> app/repositories/<module>.py (SQLAlchemy queries, ALWAYS user-scoped)
  -> app/models.py + Alembic      (PostgreSQL schema)
  app/domain/                     (pure, deterministic money logic; no database; heavily unit-tested)
  app/schemas/                    (Pydantic request/response models = the API contract)
  app/worker.py                   (background jobs from the PostgreSQL jobs table)
```
