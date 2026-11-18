# M7: Export, restore, seed and the end-to-end check

## 1. What we built
`GET /api/v1/export` gives you a zip of everything the app holds about you. A test proves that
export is complete: it loads an export into an empty database, exports again, and the two manifests
match byte for byte. `scripts/dev.py seed` fills the dev database with two synthetic users, and
`scripts/dev.py demo` walks every journey through the API and prints a PASS/FAIL table.

## 2. Why it matters
Journey 12: "Export all of my data; the operator can back up and restore the database". Your data
is never locked in, and a broken laptop or a bad migration is recoverable.

## 3. How it works (read in this order)
1. `services/api/app/services/export.py`: builds each file, then `manifest.json` (rows + SHA-256).
2. `services/api/app/api/v1/exports.py`: the endpoint; writes an `access_audit` row.
3. `services/api/tests/export_restore.py` and `tests/test_export.py`: the round-trip proof.
4. `services/api/app/tools/seed.py`: deterministic synthetic data.
5. `services/api/app/tools/demo.py`: the 26 checked steps; `scripts/dev.py` runs it last in `check`.
6. `scripts/dev.py` `backup` / `restore`: `pg_dump -Fc` / `pg_restore --clean` inside the Docker
   container, so the client tools always match the server version.

## 4. Concepts
- **Manifest with SHA-256**: a fingerprint per file; any change to the data changes the hash.
- **Deterministic export**: rows in a fixed order, fixed zip timestamps, so equal data gives equal
  bytes, which is what makes "export -> restore -> export" comparable.
- **CSV formula injection**: Excel treats a cell starting with `=`, `+`, `-` or `@` as a formula
  (a bank narration could be crafted as `=HYPERLINK(...)`). We prefix such cells with `'`.
- **Idempotent seed**: fingerprints are derived from (user, date, label), so `INSERT ... ON
  CONFLICT DO NOTHING` skips rows that already exist.
- **Logical vs physical backup**: the export is per user and readable; `pg_dump` is the whole
  database for the operator.

## 5. Verify it yourself (PowerShell, repo root)
```powershell
.\.venv\Scripts\python.exe scripts\dev.py seed      # run twice: the second run adds 0
.\.venv\Scripts\python.exe scripts\dev.py demo      # 26/26 checks passed
.\.venv\Scripts\python.exe scripts\dev.py backup    # writes backups\finance-<time>.dump
```
In `/docs`, sign in with a token for `user.a@example.test`, then `GET /api/v1/export` and click
"Download file". Open `manifest.json` inside the zip.

## 6. Check your understanding
1. Why does the export prefix `'` to a cell that already starts with `'`?
2. Why are `pg_dump` and `pg_restore` run inside the Postgres container instead of on Windows?
3. What would the restore test catch that ordinary unit tests would not?

**Answers:** 1. So un-escaping is exact: remove one leading `'` always. Without it, a real
description "'=x" would come back as "=x". 2. `pg_dump` must be the same major version as the
server (17 here); the container always has the matching one. 3. A field that is stored but
forgotten in the export (or restored wrongly); the second export's manifest would differ.
