# M6: Reports and budgets

## 1. What we built
Totals of spending, refunds, income and cash flow for any day, ISO week, month or year; a time
series for charts; spending per category; and monthly budgets that say `ok`, `warning` or `over`
and, in the current month, project where you will end up.

## 2. Why it matters
Journeys 5 and 7: "See totals by day/week/month/year and by category" and "Set monthly budgets and
get warnings before and after overspending". These are the numbers the home screen shows.

## 3. How it works (read in this order)
1. `services/api/app/domain/reports.py` (from M2): the definitions in plain Python.
2. `services/api/app/domain/periods.py`: period boundaries (ISO weeks start Monday).
3. `services/api/app/repositories/reports.py`: the same definitions as SQL `SUM(CASE ...)` and
   `GROUP BY date_trunc(...)`.
4. `services/api/app/api/v1/reports.py`.
5. `services/api/app/domain/budgets.py`: status thresholds and projection.
6. `services/api/app/services/budgets.py`, `app/api/v1/budgets.py`.
7. Tests: `tests/test_reports_budgets.py` (the fixture month is written at the top of the file).

`GET /api/v1/reports/summary?period=week&date=2028-03-01`: the week containing 1 Mar 2028 is Mon
28 Feb to Sun 5 Mar -> one SQL query sums expenses, refunds and income for those dates, skipping
excluded rows and transfers -> net spending and cash flow are computed from those three sums.

## 4. Concepts
- **Net spending** = expenses - refunds (can be negative). **Net cash flow** = income + refunds -
  expenses. Transfers between your own accounts are never in either.
- **ISO week**: Monday to Sunday; a week can belong to two months.
- **Linked refund**: reduces the *original purchase's* category, in the month the refund happened.
- **Floor at zero**: a budget's "spent" is never below 0, even if refunds exceed spending.
- **Projection**: spent / days elapsed x days in month, only from day 7 of the current month.
- **NULLS NOT DISTINCT**: PostgreSQL 15+ option that makes "only one all-spending budget per month"
  enforceable by a unique constraint even though its category is NULL.
- **Cross-checking SQL against Python**: a test computes every period both ways and compares.

## 5. Verify it yourself (PowerShell; `serve` running, `$h` from M2)
```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/reports/summary?period=month" -Headers $h
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/budgets -Headers $h `
  -ContentType "application/json" -Body '{"month":"2026-11","amount":"20000.00"}'
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/budgets/status" -Headers $h
```

## 6. Check your understanding
1. In February you spend ₹3,000 on Shopping and get ₹800 back for a January Shopping purchase. What
   is February's Shopping net spending?
2. A ₹1,000 budget warns at 75%. Spent is exactly ₹750. Status?
3. Why is moving ₹5,000 from your bank to your wallet not in "gross spending"?

**Answers:** 1. ₹2,200: the refund counts in its own month (February) and reduces the original's
category (Shopping). 2. `warning`: exactly at the threshold counts as warning. 3. It is a transfer
between your own accounts; your money did not leave you.
