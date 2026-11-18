"""The one place the app asks "what time is it?".

Code never calls ``datetime.now()`` or ``date.today()`` directly. It asks a
``Clock`` that FastAPI injects, so tests can freeze time and check month-end
rules, budget projections and "days elapsed" exactly.

Reporting uses India time (Asia/Kolkata): a payment at 00:30 IST on 1 Dec is in
December even though it is still 30 Nov in UTC.
"""

from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

REPORTING_TZ = ZoneInfo("Asia/Kolkata")


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, timezone-aware, in UTC."""
        ...

    def today(self) -> date:
        """Current calendar date in the reporting time zone (Asia/Kolkata)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().astimezone(REPORTING_TZ).date()


class FixedClock:
    """A clock that always returns the same instant. Used by tests and the demo."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._instant = instant.astimezone(UTC)

    @classmethod
    def at_date(cls, day: date, hour: int = 12) -> "FixedClock":
        """Noon India time on ``day`` (safely inside that calendar date)."""
        return cls(datetime(day.year, day.month, day.day, hour, tzinfo=REPORTING_TZ))

    def now(self) -> datetime:
        return self._instant

    def today(self) -> date:
        return self._instant.astimezone(REPORTING_TZ).date()
