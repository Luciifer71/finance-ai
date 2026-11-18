# Finance AI — private iOS-first finance companion

A private place for each of us to see where our money goes, without recording every UPI payment
by hand, and to know what we can afford next. Two-developer private beta (27 Oct – 25 Nov 2026).

## Product principles
- Strictly separate accounts for each user; no shared financial data.
- Financial calculations are deterministic and auditable; AI never invents balances.
- Modular services with durable asynchronous work (a PostgreSQL job table, no Redis).
- Bank/UPI data comes from statement files the user downloads. Never credentials, OTPs or scraping.
  No account is ever shown as "connected" and no balance as "live".
- The UI is iOS-first (React Native / Expo); optional native Swift modules later.

## Project layout
- `apps/mobile`: Expo / React Native app (partner-owned)
- `services/api`: FastAPI backend: API, domain logic, migrations, background worker, tests
- `services/workers`, `services/ai`: pointers to where that code lives inside `services/api`
- `packages/contracts`: the API contract (`openapi.json`) and how to use it
- `scripts/dev.py`: one command for every developer task
- `infra`: local PostgreSQL (Docker)
- `docs`: architecture, decisions (ADRs), handoff plan, learning notes

## Prerequisites
- Python 3.12+, Docker Desktop, Git (GitHub CLI `gh` optional)
- Node.js 22 LTS and npm (mobile only)

## Backend quick start (Windows PowerShell)
The virtualenv lives at the **repository root** (`.venv`), not inside `services/api`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "services/api[dev]"
Copy-Item .env.example .env          # local settings; .env is never committed
.\.venv\Scripts\python.exe scripts\dev.py up        # PostgreSQL in Docker + test database
.\.venv\Scripts\python.exe scripts\dev.py migrate   # create tables in dev and test databases
.\.venv\Scripts\python.exe scripts\dev.py check     # everything CI checks
.\.venv\Scripts\python.exe scripts\dev.py serve     # http://127.0.0.1:8000/docs
```
On Linux/macOS use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`.

**Always use `127.0.0.1`, never `localhost`, in database URLs.** On Windows `localhost` tries IPv6
first and every connection hangs for about two minutes because Docker listens on IPv4 only.

`scripts/dev.py` commands: `up`, `createdb-test`, `migrate`, `check`, `migration-roundtrip`, `serve`,
`worker`, `seed`, `token <email>`, `export-openapi`, `backup`, `restore <file> --yes`, `demo`.
Run `python scripts/dev.py --help` for details.

## Start mobile on Windows
```powershell
cd apps/mobile
npm install
npx expo start
```
Expo Go can preview the UI; native functionality needs a development build. Free iPhone builds need
campus Mac access; do not assume EAS physical-device deployment is free.

## Repo safety
Do not commit `.env` files, statements, receipts, bank identifiers, credentials, tokens, or user
data. All test fixtures are synthetic. Gitleaks scans the full history on every push.

## Where to read next
- `CLAUDE.md` and `docs/handoff/BACKEND_HANDOFF.md`: the plan and the rules
- `docs/handoff/PROGRESS.md`: what is done
- `docs/learning/`: one plain-English note per backend milestone
- `packages/contracts/README.md`: how the mobile app talks to the API
