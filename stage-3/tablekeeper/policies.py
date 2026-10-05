"""Booking policies: the rules a restaurant books by on a given local date (stage 3).

Policy 0 is the reset fixture's rules and applies before any published policy. Published
policies are immutable and numbered 1, 2, ... per restaurant. A booking's local start date
selects the policy with the greatest `effective_from` not later than that date; ties go to
the greatest version.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import timeutil
from .errors import invalid
from .validate import is_int

MAX_GRID_MINUTES = 1440
MAX_CUTOFF_MINUTES = 10080
MAX_TABLE_CAPACITY = 100


@dataclass(frozen=True)
class Hours:
    weekday: str
    opens: str
    closes: str

    @property
    def opens_min(self) -> int:
        return timeutil.parse_hhmm(self.opens)

    @property
    def closes_min(self) -> int:
        return timeutil.parse_hhmm(self.closes)

    def to_json(self) -> dict:
        return {"weekday": self.weekday, "opens": self.opens, "closes": self.closes}


def parse_hours(entries, *, unique_weekdays: bool) -> tuple[Hours, ...]:
    """Opening hours per stage 1 (§4); raises ValueError when malformed."""
    if not isinstance(entries, list):
        raise ValueError("opening_hours must be an array")
    hours, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("opening_hours entries must be objects")
        weekday, opens, closes = entry.get("weekday"), entry.get("opens"), entry.get("closes")
        if weekday not in timeutil.WEEKDAYS or not isinstance(opens, str) or not isinstance(closes, str):
            raise ValueError("opening_hours entries need a weekday, opens and closes")
        h = Hours(weekday, opens, closes)
        if h.closes_min <= h.opens_min:
            raise ValueError("closes must be later than opens")
        if unique_weekdays and weekday in seen:
            raise ValueError(f"duplicate weekday {weekday}")
        seen.add(weekday)
        hours.append(h)
    return tuple(hours)


@dataclass(frozen=True)
class Policy:
    version: int
    effective_from: date | None          # None for policy 0, which precedes every date
    slot_minutes: int
    duration_minutes: int
    cutoff_minutes: int
    opening_hours: tuple[Hours, ...]
    capacities: tuple[tuple[str, int], ...]   # every table, in fixture order

    def capacity(self, table_id: str) -> int:
        return dict(self.capacities)[table_id]

    def hours_on(self, weekday: str) -> list[Hours]:
        return [h for h in self.opening_hours if h.weekday == weekday]

    def terms(self) -> dict:
        """The accepted-terms snapshot a booking keeps: the whole policy but its start date."""
        return {
            "policy_version": self.version,
            "slot_minutes": self.slot_minutes,
            "reservation_duration_minutes": self.duration_minutes,
            "cancellation_cutoff_minutes": self.cutoff_minutes,
            "opening_hours": [h.to_json() for h in self.opening_hours],
            "capacities": dict(self.capacities),
        }

    def to_json(self) -> dict:
        """A published policy as returned by the policy endpoints (decision A-34)."""
        return {
            "effective_from": self.effective_from.isoformat(),
            "slot_minutes": self.slot_minutes,
            "reservation_duration_minutes": self.duration_minutes,
            "cancellation_cutoff_minutes": self.cutoff_minutes,
            "opening_hours": [h.to_json() for h in self.opening_hours],
            "capacities": dict(self.capacities),
            "policy_version": self.version,
        }


def select(policy_zero: Policy, published: list[Policy], day: date) -> Policy:
    eligible = [p for p in published if p.effective_from <= day]
    if not eligible:
        return policy_zero
    return max(eligible, key=lambda p: (p.effective_from, p.version))


def _int_in(body: dict, field: str, low: int, high: int) -> int:
    value = body.get(field)
    if not is_int(value) or not low <= value <= high:
        raise invalid(f"{field} must be an integer from {low} to {high}")
    return value


def parse_publication(body: dict, table_ids: list[str], version: int) -> Policy:
    """A complete policy from a publication body; every defect is 422 (decision A-28)."""
    raw_date = body.get("effective_from")
    if not isinstance(raw_date, str):
        raise invalid("effective_from must be a YYYY-MM-DD date")
    effective_from = timeutil.parse_date(raw_date, "effective_from")
    slot = _int_in(body, "slot_minutes", 1, MAX_GRID_MINUTES)
    duration = _int_in(body, "reservation_duration_minutes", 1, MAX_GRID_MINUTES)
    cutoff = _int_in(body, "cancellation_cutoff_minutes", 0, MAX_CUTOFF_MINUTES)
    try:
        hours = parse_hours(body.get("opening_hours"), unique_weekdays=True)
    except ValueError as exc:
        raise invalid(f"invalid opening_hours: {exc}") from None
    capacities = body.get("capacities")
    if not isinstance(capacities, dict) or set(capacities) != set(table_ids):
        raise invalid("capacities must name exactly the restaurant's tables")
    for table_id in table_ids:
        value = capacities[table_id]
        if not is_int(value) or not 1 <= value <= MAX_TABLE_CAPACITY:
            raise invalid(f"capacity of {table_id} must be an integer from 1 to {MAX_TABLE_CAPACITY}")
    return Policy(version, effective_from, slot, duration, cutoff, hours,
                  tuple((t, capacities[t]) for t in table_ids))


def policy_from_state(obj: dict, table_ids: list[str]) -> Policy:
    """A published policy from exported state; raises on anything invalid."""
    version = obj["policy_version"]
    if not is_int(version) or version < 1:
        raise ValueError("invalid policy_version")
    return parse_publication(obj, table_ids, version)
