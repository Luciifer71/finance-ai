"""Goals and wishlist: create, change, contribute, and project when they will be reached."""

from decimal import Decimal
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.clock import Clock
from app.core.dependencies import get_clock
from app.core.errors import ProblemError
from app.domain.goals import project
from app.domain.money import MoneyFormatError, parse_money
from app.models import Goal
from app.repositories.common import get_owned_or_404
from app.schemas.goals import (
    GoalCreate,
    GoalDetail,
    GoalEventIn,
    GoalEventOut,
    GoalKind,
    GoalList,
    GoalOut,
    GoalProjectionOut,
    GoalStatus,
    GoalUpdate,
)
from app.services import goals as service

router = APIRouter(prefix="/goals", tags=["goals"])
ClockDep = Annotated[Clock, Depends(get_clock)]
ZERO = Decimal("0.00")


def goal_out(goal: Goal, saved: Decimal) -> GoalOut:
    return GoalOut(
        id=goal.id,
        name=goal.name,
        kind=cast(GoalKind, goal.kind),  # the database check constraint guarantees this
        target_amount=goal.target_amount,
        target_date=goal.target_date,
        item_url=goal.item_url,
        priority=goal.priority,
        status=cast(GoalStatus, goal.status),
        saved=saved,
        remaining=max(goal.target_amount - saved, ZERO),
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


def goal_detail(session: DbSession, user_id: UUID, goal: Goal) -> GoalDetail:
    saved = service.saved_amount(session, user_id, goal.id)
    events = service.events_for(session, user_id, goal.id)
    return GoalDetail(
        **goal_out(goal, saved).model_dump(),
        events=[GoalEventOut.model_validate(e) for e in events],
    )


def _fields(body: GoalCreate | GoalUpdate, names: set[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name in names:
        value = getattr(body, name)
        values[name] = str(value) if name == "item_url" and value is not None else value
    return values


@router.get("", response_model=GoalList)
def list_goals(user: CurrentUser, session: DbSession, status: GoalStatus | None = None) -> GoalList:
    goals = service.list_goals(session, user.id, status)
    saved = service.saved_amounts(session, user.id, [g.id for g in goals])
    return GoalList(items=[goal_out(g, saved[g.id]) for g in goals])


@router.post("", response_model=GoalDetail, status_code=status.HTTP_201_CREATED)
def create_goal(
    body: GoalCreate, user: CurrentUser, session: DbSession, clock: ClockDep
) -> GoalDetail:
    goal = service.create_goal(
        session, user.id, _fields(body, set(type(body).model_fields)), clock.now()
    )
    return goal_detail(session, user.id, goal)


@router.get("/{goal_id}", response_model=GoalDetail)
def read_goal(goal_id: UUID, user: CurrentUser, session: DbSession) -> GoalDetail:
    return goal_detail(session, user.id, get_owned_or_404(session, Goal, goal_id, user.id, "goal"))


@router.patch("/{goal_id}", response_model=GoalDetail)
def update_goal(
    goal_id: UUID, body: GoalUpdate, user: CurrentUser, session: DbSession, clock: ClockDep
) -> GoalDetail:
    """Every change is recorded in the goal's history. Send `target_date: null` to remove it."""
    changes = _fields(body, set(body.model_fields_set))
    for name in ("name", "target_amount", "priority", "status"):
        if name in changes and changes[name] is None:
            del changes[name]  # these cannot be cleared
    goal = service.update_goal(session, user.id, goal_id, changes, clock.now())
    return goal_detail(session, user.id, goal)


@router.post("/{goal_id}/events", response_model=GoalEventOut, status_code=201)
def add_event(
    goal_id: UUID, body: GoalEventIn, user: CurrentUser, session: DbSession, clock: ClockDep
) -> GoalEventOut:
    """Contribution, withdrawal or note. Contributions are earmarks: no money moves."""
    event = service.add_event(
        session,
        user.id,
        goal_id,
        event_type=body.event_type,
        amount=body.amount,
        note=body.note,
        now=clock.now(),
    )
    return GoalEventOut.model_validate(event)


@router.get("/{goal_id}/projection", response_model=GoalProjectionOut)
def projection(
    goal_id: UUID,
    user: CurrentUser,
    session: DbSession,
    clock: ClockDep,
    monthly_saving: Annotated[
        str | None, Query(description="Defaults to the median of recent complete months")
    ] = None,
) -> GoalProjectionOut:
    goal = get_owned_or_404(session, Goal, goal_id, user.id, "goal")
    saved = service.saved_amount(session, user.id, goal.id)
    today = clock.today()
    remaining = max(goal.target_amount - saved, ZERO)
    if monthly_saving is not None:
        try:
            rate: Decimal | None = parse_money(monthly_saving)
        except MoneyFormatError as exc:
            raise ProblemError(
                422, "goal.invalid_monthly_saving", "Invalid amount", str(exc)
            ) from exc
        if rate is None or rate <= 0:
            raise ProblemError(
                422,
                "goal.invalid_monthly_saving",
                "Invalid amount",
                "monthly_saving must be greater than zero.",
            )
        source: Literal["given", "median_of_recent_months"] = "given"
    else:
        rate, source = service.default_saving(session, user.id, today), "median_of_recent_months"
    if rate is None:
        return GoalProjectionOut(
            status="insufficient_history",
            monthly_saving=None,
            monthly_saving_source=None,
            saved=saved,
            target_amount=goal.target_amount,
            remaining=remaining,
            months_needed=None,
            projected_date=None,
            target_date=goal.target_date,
            months_until_target=None,
            required_monthly=None,
            on_track=None,
            target_date_passed=None,
            assumptions=[
                "At least 2 complete months with a positive median net cash flow "
                "are needed to estimate how much you save; pass monthly_saving."
            ],
        )
    p = project(
        target=goal.target_amount,
        saved=saved,
        monthly_saving=rate,
        today=today,
        target_date=goal.target_date,
    )
    assumptions = [
        f"You save {rate:.2f} every month from {today.isoformat()}"
        + (
            " (given)."
            if source == "given"
            else " (median net cash flow of your last complete months, up to 3)."
        ),
        "Contributions are counted as saved; account balances are not changed.",
        "A month needed only partly still counts as a whole month.",
    ]
    return GoalProjectionOut(
        status="ok",
        monthly_saving=rate,
        monthly_saving_source=source,
        saved=saved,
        target_amount=goal.target_amount,
        remaining=p.remaining,
        months_needed=p.months_needed,
        projected_date=p.projected_date,
        target_date=p.target_date,
        months_until_target=p.months_until_target,
        required_monthly=p.required_monthly,
        on_track=p.on_track,
        target_date_passed=p.target_date_passed,
        assumptions=assumptions,
    )
