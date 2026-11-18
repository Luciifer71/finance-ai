# M5: Background jobs and categorization

## 1. What we built
After you commit an import, a background worker gives each new transaction a category using merchant
rules ("SWIGGY" -> Food & Dining). If you re-categorize something yourself you can tick "create
rule", and future imports from that merchant follow your choice. If the worker breaks, your
transactions, balances and imports keep working; the job just ends up marked `dead`.

## 2. Why it matters
Journeys 3 and 6: imports should arrive mostly categorized, and your own corrections must stick.
It also proves the system's failure isolation: a broken "AI" step never breaks the ledger.

## 3. How it works (read in this order)
1. `services/api/app/jobs/queue.py`: `enqueue` (written in the same DB transaction as the import).
2. `services/api/app/jobs/runner.py`: `release_ready`, `claim_next`, `run_one`, backoff.
3. `services/api/app/jobs/handlers.py`: `categorize_import`.
4. `services/api/app/services/categorization.py`: rule order and matching, `create_user_rule`.
5. `services/api/app/worker.py`: the loop (`python -m app.worker`, `--once` to drain and exit).
6. Tests: `tests/test_jobs.py`.

One job's life: import commit inserts `jobs(status=queued)` -> worker: re-queue retry-ready and
stale jobs -> `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` -> `running`, attempts + 1, commit ->
new transaction: handler categorizes rows with `category_source = 'none'` (one audit event each,
actor `rule`) and the job becomes `succeeded` in the same commit. On an exception: rollback, then
`failed` with `run_after = now + 2^attempts s` (max 15 min, jitter), or `dead` after 5 attempts.

## 4. Concepts
- **Outbox pattern**: the job is a row written with the change that needs it; no message broker.
- **`FOR UPDATE SKIP LOCKED`**: a worker locks one job row; other workers skip it instead of waiting,
  so two workers never run the same job.
- **Exponential backoff with jitter**: wait 2, 4, 8... seconds between retries, slightly randomized
  so failures do not retry in lockstep.
- **Dead letter**: a job that failed too often stops retrying and is visible for a human to inspect.
- **Stale lock recovery**: a job stuck `running` for 10+ minutes (worker crashed) is re-queued.
- **Idempotent handler**: it only touches rows nobody has categorized, so running it twice is safe.
- **Rule precedence**: user rules > seed rules; then lower priority number; then longer pattern.

## 5. Verify it yourself (PowerShell, repo root)
```powershell
.\.venv\Scripts\python.exe scripts\dev.py serve     # terminal 1
.\.venv\Scripts\python.exe scripts\dev.py worker    # terminal 2
```
Import and commit `clean_12_rows.csv` (see M3 note). Within ~2 seconds
`GET /api/v1/jobs/<categorize_job_id>` shows `"status":"succeeded"` and the Swiggy transaction has
`"category_source":"rule"`. Tests: `scripts\dev.py check` (look for `tests/test_jobs.py`).

## 6. Check your understanding
1. Why is "succeeded" written in the same transaction as the handler's changes?
2. You set Swiggy to Groceries by hand before the worker ran. What does the worker do to that row?
3. Why does the job store only the exception's type, not its message?

**Answers:** 1. So either both happen or neither: no "succeeded" job whose work was lost, and no
work done twice because the status update failed. 2. Nothing: rules only fill rows with
`category_source = 'none'`; yours is `user`. 3. Messages can contain user data (descriptions,
amounts); the type name ("RuntimeError") is enough to debug and leaks nothing.
