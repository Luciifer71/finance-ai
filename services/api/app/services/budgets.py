"""Budgets: create, change, delete, and their status for a month."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.domain.budgets import ZERO, BudgetEvaluation, evaluate
from app.domain.periods import period_bounds
from app.models import Budget, Category
from app.repositories import reports as report_repo
from app.repositories.common import get_owned_or_404


def _check_category(session: Session, user_id: UUID, category_id: UUID | None) -> None:
    if category_id is None:
        return
    category = get_owned_or_404(session, Category, category_id, user_id, "category")
    if category.kind != "expense":
        raise ProblemError(
            422,
            "budget.category_not_expense",
            "Not a spending category",
            "Budgets limit spending, so they need an expense category.",
        )


def _duplicate() -> ProblemError:
    return ProblemError(
        409,
        "budget.already_exists",
        "Budget already exists",
        "There is already a budget for this category and month.",
    )


def create_budget(
    session: Session,
    user_id: UUID,
    *,
    category_id: UUID | None,
    month: date,
    amount: Decimal,
    warn_at_percent: int,
) -> Budget:
    _check_category(session, user_id, category_id)
    budget = Budget(
        user_id=user_id,
        category_id=category_id,
        month=month,
        amount=amount,
        warn_at_percent=warn_at_percent,
    )
    session.add(budget)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise _duplicate() from exc
    return budget


def update_budget(
    session: Session, user_id: UUID, budget_id: UUID, changes: dict[str, object], now: datetime
) -> Budget:
    budget = get_owned_or_404(session, Budget, budget_id, user_id, "budget", for_update=True)
    for name, value in changes.items():
        if value is not None:
            setattr(budget, name, value)
    budget.updated_at = now
    session.commit()
    return budget


def delete_budget(session: Session, user_id: UUID, budget_id: UUID) -> None:
    """Budgets are plans, not ledger facts, so they can be deleted."""
    budget = get_owned_or_404(session, Budget, budget_id, user_id, "budget", for_update=True)
    session.delete(budget)
    session.commit()


def list_budgets(session: Session, user_id: UUID, month: date | None) -> list[Budget]:
    statement = select(Budget).where(Budget.user_id == user_id)
    if month is not None:
        statement = statement.where(Budget.month == month)
    return list(session.scalars(statement.order_by(Budget.month.desc(), Budget.created_at)))


@dataclass(frozen=True)
class BudgetWithStatus:
    budget: Budget
    category_name: str | None
    evaluation: BudgetEvaluation


def status_for_month(
    session: Session, user_id: UUID, month: date, today: date
) -> list[BudgetWithStatus]:
    start, end = period_bounds("month", month)
    budgets = list_budgets(session, user_id, month)
    if not budgets:
        return []
    by_category = {
        row.category_id: row
        for row in report_repo.spending_by_category(session, user_id, start, end)
    }
    total = report_repo.period_totals(session, user_id, start, end).net_spending
    result = []
    for budget in budgets:
        if budget.category_id is None:
            net, name = total, None
        else:
            row = by_category.get(budget.category_id)
            net = row.net_spending if row else ZERO
            category = session.get(Category, budget.category_id)
            name = category.name if category else None
        result.append(
            BudgetWithStatus(
                budget=budget,
                category_name=name,
                evaluation=evaluate(budget.amount, budget.warn_at_percent, net, month, today),
            )
        )
    return result
