"""Monthly budgets and their status (handoff 6.8)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.clock import Clock
from app.core.dependencies import get_clock
from app.domain.money import percent_1dp
from app.domain.periods import month_label, parse_month
from app.models import Budget
from app.repositories.common import get_owned_or_404
from app.schemas.budgets import (
    BudgetCreate,
    BudgetList,
    BudgetOut,
    BudgetStatusList,
    BudgetStatusOut,
    BudgetUpdate,
    ProjectionOut,
)
from app.services import budgets as service

router = APIRouter(prefix="/budgets", tags=["budgets"])
ClockDep = Annotated[Clock, Depends(get_clock)]
MonthQuery = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-11"])]


def budget_out(budget: Budget) -> BudgetOut:
    return BudgetOut(
        id=budget.id,
        category_id=budget.category_id,
        month=month_label(budget.month),
        amount=budget.amount,
        warn_at_percent=budget.warn_at_percent,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.get("", response_model=BudgetList)
def list_budgets(user: CurrentUser, session: DbSession, month: MonthQuery = None) -> BudgetList:
    rows = service.list_budgets(session, user.id, parse_month(month) if month else None)
    return BudgetList(items=[budget_out(b) for b in rows])


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create_budget(body: BudgetCreate, user: CurrentUser, session: DbSession) -> BudgetOut:
    budget = service.create_budget(
        session,
        user.id,
        category_id=body.category_id,
        month=parse_month(body.month),
        amount=body.amount,
        warn_at_percent=body.warn_at_percent,
    )
    return budget_out(budget)


@router.get("/status", response_model=BudgetStatusList)
def budget_status(
    user: CurrentUser, session: DbSession, clock: ClockDep, month: MonthQuery = None
) -> BudgetStatusList:
    """Spent so far, warning/over status and, for the current month, a month-end projection."""
    today = clock.today()
    first_day = parse_month(month) if month else today.replace(day=1)
    items = []
    for entry in service.status_for_month(session, user.id, first_day, today):
        ev = entry.evaluation
        items.append(
            BudgetStatusOut(
                budget_id=entry.budget.id,
                category_id=entry.budget.category_id,
                category_name=entry.category_name,
                amount=ev.amount,
                net_spending=ev.net_spending,
                spent=ev.spent,
                warn_threshold=ev.warn_threshold,
                remaining=ev.remaining,
                percent_used=percent_1dp(ev.spent, ev.amount) or "0.0",
                status=ev.status,
                projection=ProjectionOut(
                    projected_spending=ev.projection.projected,
                    may_exceed=ev.projection.may_exceed,
                    reason=ev.projection.reason,
                    days_elapsed=ev.projection.days_elapsed,
                    days_in_month=ev.projection.days_in_month,
                ),
            )
        )
    return BudgetStatusList(month=month_label(first_day), items=items)


@router.get("/{budget_id}", response_model=BudgetOut)
def read_budget(budget_id: UUID, user: CurrentUser, session: DbSession) -> BudgetOut:
    return budget_out(get_owned_or_404(session, Budget, budget_id, user.id, "budget"))


@router.patch("/{budget_id}", response_model=BudgetOut)
def update_budget(
    budget_id: UUID, body: BudgetUpdate, user: CurrentUser, session: DbSession, clock: ClockDep
) -> BudgetOut:
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    return budget_out(service.update_budget(session, user.id, budget_id, changes, clock.now()))


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: UUID, user: CurrentUser, session: DbSession) -> Response:
    service.delete_budget(session, user.id, budget_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
