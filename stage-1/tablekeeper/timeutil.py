"""Local wall-clock times, IANA zones and DST (§9).

Instants are held as aware UTC datetimes. Local times are naive datetimes interpreted in a
restaurant's zone. A local time inside a spring-forward gap does not exist; a repeated
fall-back time resolves to its first occurrence (fold=0, the pre-transition offset).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from .errors import invalid

UTC = timezone.utc
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_LOCAL_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_HHMM_RE = re.compile(r"([0-9]{2}):([0-9]{2})")
# Dates far enough from datetime's limits that offset and duration arithmetic cannot overflow.
MIN_YEAR, MAX_YEAR = 1000, 9000


@lru_cache(maxsize=None)
def zone(name: str) -> ZoneInfo:
    """The IANA zone `name`; raises ValueError when it is not a known zone."""
    if not isinstance(name, str) or not name or name.startswith(("/", ".")) or ".." in name:
        raise ValueError(f"unknown timezone {name!r}")
    try:
        return ZoneInfo(name)
    except Exception as exc:  # ZoneInfoNotFoundError, ValueError, IsADirectoryError, ...
        raise ValueError(f"unknown timezone {name!r}") from exc


def parse_local_datetime(text: str, field: str = "starts_at_local") -> datetime:
    """A bare local `YYYY-MM-DDTHH:MM`; anything else is 422 validation_failed."""
    m = _LOCAL_RE.fullmatch(text)
    if not m:
        raise invalid(f"{field} must be a local time YYYY-MM-DDTHH:MM")
    try:
        value = datetime(*(int(g) for g in m.groups()))
    except ValueError:
        raise invalid(f"{field} is not a real date and time") from None
    if not MIN_YEAR <= value.year <= MAX_YEAR:
        raise invalid(f"{field} is out of the supported range")
    return value


def parse_date(text: str, field: str = "date") -> date:
    m = _DATE_RE.fullmatch(text)
    if not m:
        raise invalid(f"{field} must be YYYY-MM-DD")
    try:
        value = date(*(int(g) for g in m.groups()))
    except ValueError:
        raise invalid(f"{field} is not a real date") from None
    if not MIN_YEAR <= value.year <= MAX_YEAR:
        raise invalid(f"{field} is out of the supported range")
    return value


def parse_hhmm(text: str) -> int:
    """Minutes after midnight for `HH:MM` in 00:00..23:59; raises ValueError otherwise."""
    m = _HHMM_RE.fullmatch(text) if isinstance(text, str) else None
    if not m:
        raise ValueError(f"{text!r} is not HH:MM")
    hours, minutes = int(m.group(1)), int(m.group(2))
    if hours > 23 or minutes > 59:
        raise ValueError(f"{text!r} is not HH:MM")
    return hours * 60 + minutes


def format_local(local: datetime) -> str:
    return local.strftime("%Y-%m-%dT%H:%M")


def weekday_name(day: date) -> str:
    return WEEKDAYS[day.weekday()]


def to_instant(tz: ZoneInfo, local: datetime) -> datetime:
    """The UTC instant of `local` in `tz` (first occurrence when repeated).

    A time in a spring-forward gap maps forward by the gap's length, which is the right
    answer for an opening-hours boundary; use `exists` to reject gap times as starts.
    """
    try:
        return local.replace(tzinfo=tz, fold=0).astimezone(UTC)
    except (OverflowError, ValueError):
        raise invalid("date is out of the supported range") from None


def exists(tz: ZoneInfo, local: datetime) -> bool:
    """False when `local` falls in a spring-forward gap of `tz`."""
    try:
        back = local.replace(tzinfo=tz, fold=0).astimezone(UTC).astimezone(tz)
    except (OverflowError, ValueError):
        raise invalid("date is out of the supported range") from None
    return back.replace(tzinfo=None) == local


def render(instant: datetime, tz: ZoneInfo | timezone = UTC) -> str:
    """RFC 3339 with an explicit numeric offset, seconds precision.

    RFC 3339 offsets are whole minutes. A zone's historic local mean time can be offset by
    seconds (Berlin before 1893 was +00:53:28); such an instant is rendered in UTC instead.
    """
    local = instant.astimezone(tz)
    if local.utcoffset().total_seconds() % 60:
        local = instant.astimezone(UTC)
    return local.isoformat(timespec="seconds")


def parse_instant(text: str) -> datetime:
    """An RFC 3339 timestamp with an offset (as rendered by `render`); raises ValueError."""
    if not isinstance(text, str):
        raise ValueError("timestamp must be a string")
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def now() -> datetime:
    return datetime.now(UTC)


def minutes(n: int) -> timedelta:
    return timedelta(minutes=n)
