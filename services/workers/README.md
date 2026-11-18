# Workers

Background jobs live in the API package so one image runs both processes:

- Job table and queue logic: `services/api/app/jobs/`
- Worker loop: `services/api/app/worker.py` (`python -m app.worker`, or `scripts/dev.py worker`)

Jobs are rows in the PostgreSQL `jobs` table (an outbox): they are enqueued in the same database
transaction as the change that needs them, retried with backoff, and marked `dead` after too many
failures. There is no Redis or RabbitMQ. See section 9 of `docs/handoff/BACKEND_HANDOFF.md`.
