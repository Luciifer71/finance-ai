# ADR-0002: Ledger data model for statement imports

Status: proposed (8 Nov 2026)

## Context
The first schema assumed every transaction has a reference number, an exact
time, and that both sides of a transfer are known at once. Real Indian bank
CSV statements break all three assumptions.

## Decisions
1. **Money** is `NUMERIC(18,2)` in Postgres and `Decimal` in Python, never
   float. This is exact, and it is the "decimal minor units" rule from the
   roadmap: amounts are whole paise, stored with 2 decimal places.
2. **Dates:** `posted_on` (a plain `DATE`) is the statement's date and every
   report groups by it. `occurred_at` is optional, only for sources that give
   a real timestamp. This avoids rows moving to the previous day when a
   midnight IST date is stored in UTC.
3. **Direction vs type:** `direction` (debit/credit) is the bank's fact about
   this account. `transaction_type` (income/expense/transfer/refund) is what
   it means. The database rejects impossible pairs such as a credit expense.
4. **Duplicates:** each row has a SHA-256 `fingerprint` of date, amount,
   direction, reference and description, plus an occurrence number for
   identical rows in the same file (`app/domain/fingerprint.py`). It is
   unique per account, so re-importing a statement adds nothing.
5. **Transfers** between the user's own accounts are two rows, one per
   account, sharing a `transfer_group_id`. Pairing happens after import.
   A UPI payment to another person is an expense, not a transfer.
6. **Refunds** are their own type and may link to the original purchase via
   `refund_of_id` once matched.
7. **Balances** are `balance_snapshots`: a balance on a date, either from a
   statement or entered by the user. "Verified" is calculated from these
   snapshots, never stored, so it cannot go stale.
8. **User isolation in the database:** every link between user-owned rows is
   a composite `(id, user_id)` foreign key, so a row can never reference
   another user's account, import, category or transaction.

## Consequences
- Transfer pairing and refund matching are application logic (later issues).
- The database cannot yet enforce "exactly one debit and one credit per
  transfer group"; the pairing code and its tests must.
- Migration 2b6f0c9d4e71 requires empty `transactions` and
  `transaction_imports` tables.
