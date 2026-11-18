# M2: Accounts, categories, balances, transaction reads

## 1. What we built
You can create bank/cash/wallet/credit accounts, set an opening balance, manage categories, record a
manual transaction, and search your transactions page by page. Every balance comes with a label:
**verified** (proven by a bank statement) or **estimated** (with the reason why).

## 2. Why it matters
Journeys 2, 4 and 5: set up accounts, review transactions with honest balance labels, and search.
The product rule "never pretend an estimated balance is verified" lives in `app/domain/balances.py`.

## 3. How it works (read in this order)
1. `services/api/app/domain/balances.py`: the pure balance rules (no database).
2. `services/api/app/repositories/common.py`: `get_owned_or_404`, the only way to fetch by id.
3. `services/api/app/repositories/accounts.py`: one SQL `GROUP BY posted_on` gives the daily net
   movement of an account; snapshots are read separately.
4. `services/api/app/services/accounts.py`, then `app/api/v1/accounts.py`.
5. `services/api/app/repositories/transactions.py` and `app/core/pagination.py`: filters and cursors.
6. `services/api/app/services/transactions.py`: manual transactions.
7. Tests: `tests/test_balances_domain.py` (hand-worked numbers), `tests/test_accounts_api.py`,
   `tests/test_transactions_api.py`, `tests/isolation_registry.py`.

`GET /api/v1/accounts/{id}/balance?as_of=2026-11-18`: load the account (404 if not yours) -> load
snapshots and daily movements up to 18 Nov -> pick the anchor (latest snapshot on or before the
date; a statement beats a typed one on the same day) -> balance = anchor + movements after the
anchor date -> label it: verified only if the anchor is a statement, nothing was posted after it,
and every pair of consecutive statements reconciles.

## 4. Concepts
- **Snapshot / anchor**: a known balance on a date. Statement snapshots come from the bank;
  user-entered ones (opening balance, adjustments) are always estimates.
- **Reconciliation**: statement 1 + everything between = statement 2? If not, report the
  difference and never "fix" it.
- **Signed amount**: amounts are stored positive; `direction` (debit/credit) gives the sign.
- **Keyset (cursor) pagination**: "give me rows *after* (date, id)" instead of `OFFSET`; each row
  appears exactly once even with many rows on the same date.
- **`ILIKE` escaping**: a search for `100%` must not treat `%` as "anything"; we escape it.
- **Archive, don't delete**: transactions point at accounts and categories, so those are hidden,
  never removed.

## 5. Verify it yourself (PowerShell; `serve` running, `$token` from `dev.py token`)
```powershell
$h = @{ Authorization = "Bearer $token" }
$acc = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/accounts -Headers $h `
  -ContentType "application/json" -Body '{"name":"Wallet","account_type":"cash"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/accounts/$($acc.id)/opening-balance" `
  -Headers $h -ContentType "application/json" -Body '{"as_of":"2026-11-01","balance":"2,500.00"}'
```
Expect `balance: 2500.00`, `status: estimated`, `reason: no_statement`.

## 6. Check your understanding
1. A statement says ₹7,342.18 on 15 Nov and a ₹342.18 debit is posted on 16 Nov. Balance and status?
2. Why does the API refuse `"balance": 100.5` (a JSON number)?
3. Why must user B get 404, not 403, for user A's account?

**Answers:** 1. ₹7,000.00, estimated, reason `transactions_after_statement`. 2. JSON numbers are
floats in most clients; money must arrive as a string so no precision is ever lost. 3. 403 would
confirm the account exists; 404 reveals nothing.
