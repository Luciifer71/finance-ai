"""'What if I buy this now?' Nothing is written."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession
from app.api.v1.accounts import balance_out
from app.core.clock import Clock
from app.core.dependencies import get_clock
from app.schemas.goals import BudgetImpactOut, GoalImpactOut, PurchaseIn, PurchaseOut
from app.services import scenarios as service

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
ClockDep = Annotated[Clock, Depends(get_clock)]


@router.post("/purchase", response_model=PurchaseOut)
def purchase(
    body: PurchaseIn, user: CurrentUser, session: DbSession, clock: ClockDep
) -> PurchaseOut:
    result = service.purchase(
        session,
        user.id,
        amount=body.amount,
        account_id=body.account_id,
        category_id=body.category_id,
        today=clock.today(),
    )
    session.rollback()  # belt and braces: a scenario never writes
    balance_after: Decimal | None = None
    if result.balance_before is not None:
        balance_after = result.balance_before.amount - body.amount
    assumptions = [
        "The purchase is paid today, as one payment.",
        "Goal delays treat the amount as money that would otherwise have been saved.",
    ]
    if result.balance_before is not None and result.balance_before.status == "estimated":
        assumptions.append("The account balance is an estimate, so the balance after is too.")
    if result.monthly_saving is None:
        assumptions.append("Not enough history to estimate monthly saving: no goal delays.")
    return PurchaseOut(
        amount=body.amount,
        account_id=body.account_id,
        balance_before=balance_out(result.balance_before) if result.balance_before else None,
        balance_after=balance_after,
        month_net_spending_before=result.month_net_spending_before,
        month_net_spending_after=result.month_net_spending_before + body.amount,
        budgets=[
            BudgetImpactOut(
                budget_id=b.budget_id,
                category_id=b.category_id,
                category_name=b.category_name,
                spent_before=b.before.spent,
                spent_after=b.after.spent,
                amount=b.before.amount,
                status_before=b.before.status,
                status_after=b.after.status,
            )
            for b in result.budgets
        ],
        goals=[
            GoalImpactOut(
                goal_id=g.goal.id,
                name=g.goal.name,
                remaining=g.remaining,
                delay_months=g.delay_months,
                reason=None if g.delay_months is not None else "insufficient_history",
            )
            for g in result.goals
        ],
        monthly_saving=result.monthly_saving,
        assumptions=assumptions,
    )
