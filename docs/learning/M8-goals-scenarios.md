# M8: Goals, wishlist, projections and "what if I buy this now?"

## 1. What we built
Wishlist items and savings goals with a target amount, optional deadline and link. You "put money
aside" by recording contributions (and take it back with withdrawals); every change is kept in a
history that cannot be rewritten. The app projects when you will reach a goal, whether you are on
track for its deadline, and how much later each goal gets if you buy something now.

## 2. Why it matters
Journey 8: "Keep a wishlist and savings goals with target price and deadline, a full history of
changes and contributions, a projected completion date and 'what if I buy this now?' scenarios."

## 3. How it works (read in this order)
1. `services/api/app/domain/goals.py`: `add_months`, `project`, `purchase_delay`, default saving.
2. `services/api/app/services/goals.py`: events, the zero floor, auto-achieve, complete months.
3. `services/api/app/api/v1/goals.py`: endpoints and the projection's assumptions.
4. `services/api/app/services/scenarios.py` and `app/api/v1/scenarios.py`.
5. Migration `c4396ad9d251_goals.py` (append-only trigger on `goal_events`).
6. Tests: `tests/test_goals_domain.py` (math by hand), `tests/test_goals_api.py`.

`GET /api/v1/goals/{id}/projection` with no `monthly_saving`: saved = contributions - withdrawals
-> monthly saving = median net cash flow of the last up-to-3 complete months (needs at least 2) ->
remaining / saving, rounded up, months -> today + that many months.

## 4. Concepts
- **Derived, not stored**: "saved" is computed from the event history every time, so the number
  and the history can never disagree.
- **Earmark**: a contribution says "this money is for the phone"; it does not move money between
  accounts, so balances and reports are unchanged.
- **Ceiling**: 5.5 months of saving means 6 months; `required_monthly` rounds *up* to the paisa so
  following it always reaches the target.
- **Clamping month ends**: 31 Jan + 1 month is 28 Feb (29 in a leap year).
- **Median**: the middle value; one unusual month (a bonus) barely moves it, unlike an average.
- **Pure scenario**: the purchase endpoint only reads; a test counts rows in every table before
  and after.

## 5. Verify it yourself
Run `scripts\dev.py demo`: steps marked `8` create a goal, project it and run a purchase scenario.
Or in `/docs` (signed in as `user.a@example.test` after `dev.py seed`): `GET /api/v1/goals`, then
`GET /api/v1/goals/{id}/projection` and `POST /api/v1/scenarios/purchase` with
`{"amount": "5000.00"}`.

## 6. Check your understanding
1. Target ₹45,000, saved ₹15,000, saving ₹5,000 a month. Months needed?
2. Saved ₹12,500.50. Can you withdraw ₹12,500.51?
3. Remaining ₹20,000, saving ₹5,000 a month. How much later is the goal if you spend ₹7,000 now?

**Answers:** 1. (45,000 - 15,000) / 5,000 = 6 months. 2. No: saved can never go below zero;
₹12,500.50 exactly is allowed. 3. Before: 20,000 / 5,000 = 4 months; after: 27,000 / 5,000 = 5.4
-> 6 months; so 2 months later.
