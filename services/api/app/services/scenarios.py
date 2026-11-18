"""'What if I buy this now?' (handoff 6.9). Purely hypothetical: nothing is written.

For an amount (and optionally the account it would be paid from and its category):
- the account's balance after the purchase, with the base balance's status;
- this month's net spending before and after, and every affected budget's new status
  (the all-spending budget always; a category budget when a category is given);
- for each active goal, how many months later it would be reached, treating the
  purchase as money that would otherwise have been saved.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.balances import Balance
from app.domain.budgets import BudgetEvaluation, evaluate
from app.domain.goals import purchase_delay
from app.domain.periods import period_bounds
from app.models import Category, FinancialAccount, Goal
from app.repositories import reports as report_repo
from app.repositories.common import get_owned_or_404
from app.services import accounts as account_service
from app.services import budgets as budget_service
from app.services import goals as goal_service


@dataclass(frozen=True)
class BudgetImpact:
    budget_id: UUID
    category_id: UUID | None
    category_name: str | None
    before: BudgetEvaluation
    after: BudgetEvaluation


@dataclass(frozen=True)
class GoalImpact:
    goal: Goal
    remaining: Decimal
    monthly_saving: Decimal | None
    delay_months: int | None


@dataclass(frozen=True)
class PurchaseScenario:
    amount: Decimal
    account: FinancialAccount | None
    balance_before: Balance | None
    month_net_spending_before: Decimal
    budgets: list[BudgetImpact]
    goals: list[GoalImpact]
    monthly_saving: Decimal | None


def purchase(
    session: Session,
    user_id: UUID,
    *,
    amount: Decimal,
    account_id: UUID | None,
    category_id: UUID | None,
    today: date,
) -> PurchaseScenario:
    account = balance = None
    if account_id is not None:
        account = get_owned_or_404(session, FinancialAccount, account_id, user_id, "account")
        balance = account_service.balance_of(session, user_id, account, today)
    if category_id is not None:
        get_owned_or_404(session, Category, category_id, user_id, "category")

    month = today.replace(day=1)
    start, end = period_bounds("month", month)
    month_net = report_repo.period_totals(session, user_id, start, end).net_spending

    impacts = []
    for entry in budget_service.status_for_month(session, user_id, month, today):
        budget = entry.budget
        if budget.category_id is not None and budget.category_id != category_id:
            continue
        before = entry.evaluation
        after = evaluate(
            budget.amount, budget.warn_at_percent, before.net_spending + amount, month, today
        )
        impacts.append(
            BudgetImpact(budget.id, budget.category_id, entry.category_name, before, after)
        )

    rate = goal_service.default_saving(session, user_id, today)
    goals = goal_service.list_goals(session, user_id, "active")
    saved = goal_service.saved_amounts(session, user_id, [g.id for g in goals])
    goal_impacts = []
    for goal in goals:
        remaining = max(goal.target_amount - saved[goal.id], Decimal("0.00"))
        delay = purchase_delay(remaining, amount, rate) if rate is not None else None
        goal_impacts.append(GoalImpact(goal, remaining, rate, delay))

    return PurchaseScenario(
        amount=amount,
        account=account,
        balance_before=balance,
        month_net_spending_before=month_net,
        budgets=impacts,
        goals=goal_impacts,
        monthly_saving=rate,
    )
