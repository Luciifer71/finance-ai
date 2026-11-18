# M3: CSV import pipeline

## 1. What we built
Upload a bank statement CSV and see a preview first: how many rows are new, which are already in
your ledger, which could not be read (with the row number and why). Nothing is added until you
press commit. Importing the same statement twice, or an overlapping one, never adds a row twice.

## 2. Why it matters
Journey 3. Indian banks and UPI apps offer no free real-time API, so statement files are the main
way data gets in. It must be impossible to double-count spending by importing carelessly.

## 3. How it works (read in this order)
1. `services/api/app/importers/profiles.py`: a profile is *data* describing a bank's columns.
2. `services/api/app/importers/parser.py`: bytes -> decoded text -> CSV records -> header found ->
   each row parsed or marked invalid with a code. Also the running-balance check.
3. `services/api/app/domain/fingerprint.py` (from PR #6): the row's identity.
4. `services/api/app/services/imports.py`: `create_import` (preview) and `commit_import`.
5. `services/api/app/api/v1/imports.py`, then `app/jobs/queue.py` (the outbox).
6. Tests: `tests/test_import_parser.py`, `tests/test_imports_api.py`, fixtures in
   `tests/fixtures/statements/` (all invented).

Upload: check the account is yours -> check `.csv` and size -> SHA-256 of the file (an exact repeat
of a completed import is a 409) -> parse -> fingerprint every valid row -> any fingerprint already
in this account means `already_imported` -> save the parsed rows (not the file) in `import_rows`
-> status `previewed`.
Commit: lock the import row -> `INSERT ... ON CONFLICT (account_id, fingerprint) DO NOTHING` for the
valid rows -> the last chronological closing balance becomes a *statement* snapshot -> enqueue a
`categorize_import` job -> status `completed`, all in one database transaction.

## 4. Concepts
- **File hash vs row fingerprint**: the hash catches the identical file; fingerprints catch the
  same *rows* inside a different file (e.g. an overlapping statement or different line endings).
- **Occurrence number**: two identical ₹20 chai rows get occurrence 1 and 2, so both are kept, and
  re-importing gives the same numbers, so neither is added again.
- **Idempotency**: doing something twice has the same effect as once (commit, re-import).
- **Outbox pattern**: the job row is written in the same transaction as the import, so a
  committed import always has its job and a rolled-back one never does.
- **cp1252**: the text encoding Excel on Windows often uses; we fall back to it when UTF-8 fails.
- **Header detection**: banks put lines (account name, period) above the header; we look for the
  profile's column names in the first 30 lines.

## 5. Verify it yourself (PowerShell; `serve` running, `$h` and an account id `$acc.id`)
```powershell
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/imports -H "Authorization: Bearer $token" `
  -F "file=@services/api/tests/fixtures/statements/clean_12_rows.csv" `
  -F "account_id=$($acc.id)" -F "profile_id=generic_indian_bank_v1"
```
Expect `"status":"previewed"`, `"valid":12`, `"closing_balance":"34125.00"`. Then
`POST /api/v1/imports/<id>/commit` and `GET /api/v1/accounts/<id>/balance`: 34125.00, verified.

## 6. Check your understanding
1. Why can't we just compare the file hash to stop duplicates?
2. An overlapping statement has 4 old rows and 4 new rows. What does commit insert, and why?
3. A row has both a withdrawal and a deposit. What happens to the rest of the file?

**Answers:** 1. The same transactions appear in different files (overlapping periods, re-exports
with other line endings), which have different hashes. 2. Only the 4 new rows: the old rows'
fingerprints already exist for this account, so they are `already_imported` and the insert's
`ON CONFLICT DO NOTHING` would skip them anyway. 3. Only that row is marked invalid
(`import.row.two_amounts`); every valid row is still imported.
