# M4: Ledger integrity

## 1. What we built
The bank's facts about a transaction (amount, date, description, account...) can never be changed,
not even by a mistaken SQL command. What you *can* change (category, notes, "exclude from
reports", type, transfer pairing, refund link) is recorded in an append-only history. Transfers
between your own accounts and refunds of earlier purchases are handled with strict rules.

## 2. Why it matters
Journey 6: "Edit category and notes. Pair transfers. Match refunds. Every change is audited."
Without this, moving ₹10,000 from savings to your wallet would look like ₹10,000 of spending, and a
refund could be counted twice.

## 3. How it works (read in this order)
1. `services/api/migrations/versions/18b5073358d7_ledger_integrity.py`: three PostgreSQL triggers.
2. `services/api/app/services/ledger.py`: `apply_change` is the only way editable fields change.
3. `services/api/app/services/transfers.py`: suggestions, `pair`, `unpair`, `auto_pair`, cash.
4. `services/api/app/services/refunds.py`: suggestions and `link` with limits.
5. `services/api/app/domain/merchant.py`: normalizes "UPI/AMAZON/4027.../REFUND" to "AMAZON".
6. Tests: `tests/test_ledger_integrity.py`, `tests/test_merchant.py`.

`PATCH /api/v1/transactions/{id}` with `{"category_id": "..."}`: lock the row (`FOR UPDATE`) ->
check the category is yours, active and the right kind -> `apply_change` sets the field and writes
one `transaction_events` row `{before: {category_id: null}, after: {category_id: "..."}}` -> commit
(both together, or neither).

## 4. Concepts
- **BEFORE UPDATE trigger**: database code that runs before each row update; ours raises an error if
  any fact column changes, so even `psql` cannot rewrite history.
- **Append-only table**: inserts only; a trigger rejects UPDATE and DELETE on events.
- **Deferred constraint trigger**: checks "one debit + one credit, equal, different accounts" at
  COMMIT, because the two rows of a pair are updated one after the other.
- **Row lock (`SELECT ... FOR UPDATE`)**: while one request checks "refunds so far + this one <=
  original", nobody else can link a refund to the same original.
- **Audit-based undo**: unpairing reads the pairing event's `before` to restore the old type/category.
- **Conservative automation**: auto-pairing happens only when there is exactly one candidate *and*
  a hint such as "SELF" or the other account's last 4 digits; otherwise it is a suggestion.

## 5. Verify it yourself (PowerShell; Docker running)
```powershell
docker compose -f infra/docker-compose.yml exec postgres psql -U finance -d finance -c "UPDATE transactions SET amount = amount + 1"
```
Expect `ERROR: transaction source facts cannot be changed` (on a database that has transactions).
Then `scripts\dev.py check` and look for `tests/test_ledger_integrity.py`.

## 6. Check your understanding
1. Original ₹1,000. Refunds of ₹600 and ₹400 are linked. Why is a third refund of ₹0.01 refused?
2. Why are excluded transactions still part of the account balance?
3. Why can't the transfer-group check run immediately after each UPDATE?

**Answers:** 1. 600 + 400 + 0.01 = 1,000.01 > 1,000.00; the sum of refunds may equal the original
but never exceed it. 2. Excluding hides a row from reports, but the money really moved; the
balance must match the bank. 3. Pairing updates the debit row first; at that moment the group has
only one row and would look invalid. Checking at commit sees both rows.
