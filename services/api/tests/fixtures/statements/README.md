# Synthetic statement fixtures

Every file here is invented. No real names, account numbers or transactions.

| File | Profile | What it tests |
|---|---|---|
| `clean_12_rows.csv` | generic_indian_bank_v1 | 12 rows, Oct 2026, closing balances chain from 10,000.00 to 34,125.00 |
| `overlap_nov.csv` | generic_indian_bank_v1 | last 4 rows of the clean file + 4 new Nov rows; closes at 91,418.50 |
| `preamble_footer.csv` | generic_indian_bank_v1 | bank preamble above the header, opening-balance row, summary footer |
| `malformed.csv` | generic_indian_bank_v1 | bad date, two amounts, no amount, text amount (+2 valid rows) |
| `same_day_identical.csv` | simple_v1 | three identical ₹20 rows on one day (all kept), ₹ with grouping |
| `cp1252_text.csv` | simple_v1 | Windows-1252 encoded text (é, en dash); ₹ cannot exist in cp1252 |
| `empty.csv` | any | empty upload |

The over-the-row-limit file is generated inside the test, not committed.
