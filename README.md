# Finance AI — private iOS-first finance companion

Day 1 foundation for a two-developer, 30-day private beta (27 Oct – 25 Nov 2026).

## Product principles
- Strictly separate accounts for each user; no shared financial data.
- Financial calculations are deterministic and auditable; AI never invents balances.
- Modular services with durable asynchronous work planned for later checkpoints.
- Bank/UPI integrations use consented, permitted sources. Never request credentials/OTP.
- The UI is iOS-first (React Native / Expo); optional native Swift modules later.

## Project layout
- `apps/mobile`: Expo / React Native mobile shell
- `services/api`: FastAPI API, health endpoint, tests
- `services/workers`: background processing boundary (placeholder)
- `services/ai`: classification and forecasting boundary (placeholder)
- `packages/contracts`: API and model contracts
- `infra`: local dependencies
- `docs`: architecture, scope, decisions, development practices

## Prerequisites
- Node.js 22 LTS and npm
- Python 3.12+
- Docker Desktop (optional today; required for PostgreSQL later)
- Git and GitHub CLI (`gh`) optional

## Start mobile on Windows
```powershell
cd apps/mobile
npm install
npx expo start
```
Expo Go can preview the initial UI; native functionality will require a development build. Free iPhone build/signing requires campus Mac access; do not assume EAS physical-device deployment is free.

## Start API on Windows
```powershell
cd services/api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```
Visit http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs.

## Repo safety
Do not commit .env files, statements, receipts, bank identifiers, credentials, tokens, or user data. Use fabricated data only until authentication, storage isolation, and threat-model review are in place.

## Daily checkpoint
1. Each developer works in a feature branch and runs relevant tests.
2. Commit meaningful changes; push your branch to GitHub **every day**.
3. Open/review a PR; merge only once checks pass.
4. Post a two-line handoff note in the issue/PR: completed, blocked, next.

## Status
Day 1 scaffold only. No live bank connections, authentication, PostgreSQL persistence, ML model, financial predictions, or production-ready security implemented yet.
