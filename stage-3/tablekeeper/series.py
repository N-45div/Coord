"""Recurring reservations: adopting a booking as occurrence zero of a weekly series (stage 3).

Runs with the store lock held. Adoption plans every occurrence first, checks occupancy for
all of them at once, and only then creates them, so a failure leaves nothing behind.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .booking import (Placement, check_cutoff, ensure_free, new_reservation, owned, place,
                      select_tables)
from .errors import ApiError, invalid, not_found
from .model import Occurrence, Series, State, User
from .validate import is_int

MIN_COUNT, MAX_COUNT = 2, 12
MIN_INTERVAL, MAX_INTERVAL = 1, 4


def _bounded(body: dict, field: str, low: int, high: int) -> int:
    value = body.get(field)
    if not is_int(value) or not low <= value <= high:
        raise invalid(f"{field} must be an integer from {low} to {high}")
    return value


def adopt(state: State, user: User, body: dict, now: datetime) -> dict:
    """POST /series after authentication and idempotency (decision A-30)."""
    anchor_reference = body.get("anchor_reference")
    if not isinstance(anchor_reference, str):
        raise invalid("anchor_reference must be a reservation reference")
    count = _bounded(body, "count", MIN_COUNT, MAX_COUNT)
    interval = _bounded(body, "interval_weeks", MIN_INTERVAL, MAX_INTERVAL)

    anchor = owned(state, user, anchor_reference)
    if not anchor.confirmed:
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    if anchor.series_id is not None:
        raise ApiError(409, "already_in_series", "the reservation already belongs to a series")
    check_cutoff(anchor, now)

    restaurant = state.restaurants[anchor.restaurant_id]
    tables = select_tables(restaurant, anchor.table_ids)
    planned: dict[str, Placement] = {}
    for index in range(1, count):
        day = anchor.local.date() + timedelta(weeks=index * interval)
        local = datetime.combine(day, anchor.local.time())
        planned[f"occurrence {index}"] = place(state, restaurant, tables, local, anchor.party_size)
    ensure_free(state, restaurant, planned)

    series = Series(state.new_series_id(), user.id, restaurant.id, interval, 1,
                    [Occurrence(0, anchor.id, anchor.local.date())])
    for index, placement in enumerate(planned.values(), start=1):
        res = new_reservation(state, restaurant, user.id, placement, now)
        res.series_id = series.id
        series.occurrences.append(Occurrence(index, res.id, placement.local.date()))
    anchor.series_id = series.id
    state.series[series.id] = series
    state.bump_restaurant(restaurant.id)
    return view(state, series)


def view(state: State, series: Series) -> dict:
    tz = state.restaurants[series.restaurant_id].tz
    occurrences = []
    for occurrence in series.occurrences:
        res = state.reservations[occurrence.reservation_id]
        occurrences.append({"index": occurrence.index, "reference": res.reference,
                            "exception": occurrence.exception, "reservation": res.to_response(tz)})
    return {"series_id": series.id, "revision": series.revision,
            "interval_weeks": series.interval_weeks, "occurrences": occurrences}


def owned_series(state: State, user: User | None, series_id: str) -> Series:
    """The caller's series; anyone else's (or no caller) is a 404, as for reservations."""
    series = state.series.get(series_id)
    if series is None or user is None or series.user_id != user.id:
        raise not_found("no such series")
    return series
