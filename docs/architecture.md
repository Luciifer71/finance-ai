# Architecture — ADR-0001 (proposed, Day 1)

## Decision
- iOS-first Expo/React Native, with native Swift extensions only when needed.
- FastAPI modular backend; PostgreSQL as authoritative data store.
- Separate ledger, ingestion, budgeting, goals, analytics, and AI modules with explicit contracts.
- Database-backed durable jobs/outbox in later iterations; no in-memory-only financial tasks.
- AI results are suggestions; financial balances always derive from verified ledger records.

## Boundaries and failure isolation
- Ingestion normalizes allowed inputs and deduplicates before persistence.
- Ledger is authoritative for transaction history, transfers, refunds, and reconciliation.
- Analytics, goals, and AI consume versioned views/events, never mutate ledger history.
- Identity and tenant scoping are enforced on server and database, not merely UI.

## Security constraints
Never store UPI PINs, online banking passwords, OTPs or raw tokens in code. No actual bank data during foundation development. Threat modeling and retention policy are release gates.

## Assumptions to validate
Full automatic Google Pay/BHIM/Paytm/PhonePe and bank ingestion cannot be guaranteed on iOS; approved integration feasibility must be researched, with fallback statement ingestion. For initial development, no paid Apple membership, and campus-only Mac Mini access.
