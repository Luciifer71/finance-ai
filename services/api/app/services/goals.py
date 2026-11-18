"""Goals and wishlist items with an append-only history (handoff 6.9).

- ``saved`` = contributions - withdrawals, computed from events, never stored.
- A withdrawal that would take ``saved`` below zero is rejected (the goal row
  is locked while checking).
- When ``saved`` reaches the target of an active goal, the service records
  ``status_changed -> achieved`` with actor ``system``.
- Contributions are earmarks: they never touch account balances or reports.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.domain.goals import default_monthly_saving
from app.domain.periods import period_bounds
from app.models import Goal, GoalEvent, Transaction
from app.repositories import reports as report_repo
from app.repositories.common import get_owned_or_404

ZERO = Decimal("0.00")


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _event(
    session: Session,
    goal: Goal,
    event_type: str,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    amount: Decimal | None = None,
    note: str | None = None,
    actor: str = "user",
) -> GoalEvent:
    event = GoalEvent(
        user_id=goal.user_id,
        goal_id=goal.id,
        event_type=event_type,
        amount=amount,
        before={k: _json(v) for k, v in (before or {}).items()},
        after={k: _json(v) for k, v in (after or {}).items()},
        note=note,
        actor=actor,
    )
    session.add(event)
    session.flush()
    return event


def saved_amounts(session: Session, user_id: UUID, goal_ids: list[UUID]) -> dict[UUID, Decimal]:
    signed = case(
        (GoalEvent.event_type == "contribution", GoalEvent.amount),
        (GoalEvent.event_type == "withdrawal", -GoalEvent.amount),
        else_=0,
    )
    rows = session.execute(
        select(GoalEvent.goal_id, func.coalesce(func.sum(signed), 0))
        .where(GoalEvent.user_id == user_id, GoalEvent.goal_id.in_(goal_ids))
        .group_by(GoalEvent.goal_id)
    ).all()
    found = {row[0]: Decimal(row[1]) for row in rows}
    return {goal_id: found.get(goal_id, ZERO) for goal_id in goal_ids}


def saved_amount(session: Session, user_id: UUID, goal_id: UUID) -> Decimal:
    return saved_amounts(session, user_id, [goal_id])[goal_id]


def _auto_achieve(session: Session, goal: Goal, saved: Decimal, now: datetime) -> None:
    if goal.status == "active" and saved >= goal.target_amount:
        _event(
            session,
            goal,
            "status_changed",
            before={"status": "active"},
            after={"status": "achieved"},
            actor="system",
            note="saved amount reached the target",
        )
        goal.status = "achieved"
        goal.updated_at = now


def create_goal(session: Session, user_id: UUID, data: dict[str, Any], now: datetime) -> Goal:
    goal = Goal(user_id=user_id, status="active", created_at=now, updated_at=now, **data)
    session.add(goal)
    session.flush()
    _event(session, goal, "created", after={k: data[k] for k in sorted(data)})
    session.commit()
    return goal


_FIELD_EVENTS = {"target_amount": "target_changed", "target_date": "date_changed"}


def update_goal(
    session: Session, user_id: UUID, goal_id: UUID, changes: dict[str, Any], now: datetime
) -> Goal:
    """One event per kind of change: target, date, status, other details."""
    goal = get_owned_or_404(session, Goal, goal_id, user_id, "goal", for_update=True)
    groups: dict[str, dict[str, tuple[Any, Any]]] = {}
    for name, value in changes.items():
        current = getattr(goal, name)
        if value == current:
            continue
        if name == "status" and value == "achieved" and current == "abandoned":
            raise ProblemError(
                409,
                "goal.invalid_status",
                "Invalid status change",
                "Reactivate an abandoned goal before marking it achieved.",
            )
        kind = _FIELD_EVENTS.get(name) or (
            "status_changed" if name == "status" else "details_changed"
        )
        groups.setdefault(kind, {})[name] = (current, value)
        setattr(goal, name, value)
    for kind, fields in groups.items():
        _event(
            session,
            goal,
            kind,
            before={k: v[0] for k, v in fields.items()},
            after={k: v[1] for k, v in fields.items()},
        )
    if groups:
        goal.updated_at = now
        _auto_achieve(session, goal, saved_amount(session, user_id, goal.id), now)
    session.commit()
    return goal


def add_event(
    session: Session,
    user_id: UUID,
    goal_id: UUID,
    *,
    event_type: str,
    amount: Decimal | None,
    note: str | None,
    now: datetime,
) -> GoalEvent:
    goal = get_owned_or_404(session, Goal, goal_id, user_id, "goal", for_update=True)
    if event_type == "note":
        if not note:
            raise ProblemError(422, "goal.note_required", "Note required", "Write a note.")
        event = _event(session, goal, "note", note=note)
        session.commit()
        return event
    if amount is None or amount <= 0:
        raise ProblemError(
            422,
            "goal.amount_required",
            "Amount required",
            "Contributions and withdrawals need a positive amount.",
        )
    if goal.status == "abandoned":
        raise ProblemError(
            409,
            "goal.abandoned",
            "Goal abandoned",
            "Reactivate the goal before adding money to it.",
        )
    saved = saved_amount(session, user_id, goal.id)
    after = saved + amount if event_type == "contribution" else saved - amount
    if after < 0:
        raise ProblemError(
            422,
            "goal.withdrawal_exceeds_saved",
            "Not enough saved",
            "A withdrawal cannot take the saved amount below zero.",
            extra={"saved": format(saved, "f")},
        )
    event = _event(
        session,
        goal,
        event_type,
        amount=amount,
        note=note,
        before={"saved": saved},
        after={"saved": after},
    )
    goal.updated_at = now
    _auto_achieve(session, goal, after, now)
    session.commit()
    return event


def list_goals(session: Session, user_id: UUID, status: str | None) -> list[Goal]:
    statement = select(Goal).where(Goal.user_id == user_id)
    if status is not None:
        statement = statement.where(Goal.status == status)
    return list(session.scalars(statement.order_by(Goal.priority, Goal.created_at, Goal.id)))


def events_for(session: Session, user_id: UUID, goal_id: UUID) -> list[GoalEvent]:
    return list(
        session.scalars(
            select(GoalEvent)
            .where(GoalEvent.user_id == user_id, GoalEvent.goal_id == goal_id)
            .order_by(GoalEvent.seq)
        )
    )


# --- default monthly saving --------------------------------------------------------------------


def complete_month_cash_flows(session: Session, user_id: UUID, today: date) -> list[Decimal]:
    """Net cash flow of each complete calendar month the user has data for, oldest first.

    A month counts as complete when it ended before today's month and the user's
    data starts on or before its first day (a statement starting mid-month would
    understate that month).
    """
    first = session.scalar(
        select(func.min(Transaction.posted_on)).where(Transaction.user_id == user_id)
    )
    if first is None:
        return []
    month = first.replace(day=1) if first.day == 1 else _next_month(first.replace(day=1))
    current = today.replace(day=1)
    flows = []
    while month < current:
        start, end = period_bounds("month", month)
        flows.append(report_repo.period_totals(session, user_id, start, end).net_cash_flow)
        month = _next_month(month)
    return flows


def _next_month(first_day: date) -> date:
    return date(first_day.year + first_day.month // 12, first_day.month % 12 + 1, 1)


def default_saving(session: Session, user_id: UUID, today: date) -> Decimal | None:
    return default_monthly_saving(complete_month_cash_flows(session, user_id, today))
