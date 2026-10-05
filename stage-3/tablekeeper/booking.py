"""Booking rules: availability, placement validation, occupancy, create, amend, cancel, moves.

Every function here runs with the store lock held, so each request sees and changes the
state as if it ran alone. Writes validate everything first and mutate only at the end:

- `select_tables` and `place` are the one place a table set, start time and party size
  are checked against the restaurant's rules (§8, §9, stage-2 combinations);
- `ensure_free` is the one place occupancy is checked, over the whole resulting set of
  bookings (§1, §11). Create, PATCH and moves all go through all three.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from . import timeutil
from .errors import ApiError, invalid, malformed, not_found
from .model import CANCELLED, CONFIRMED, Reservation, Restaurant, State, Table, User
from .validate import MISSING, check_id, check_party_size, require_present, string_field


@dataclass(frozen=True)
class Placement:
    """Where and when a booking sits once a write is applied."""
    table_ids: tuple[str, ...]
    local: datetime
    start: datetime
    end: datetime
    party_size: int


# ----------------------------------------------------------------------------- availability

def day_slots(restaurant: Restaurant, day: date) -> list[tuple[datetime, datetime]]:
    """(local start, UTC start) for every bookable slot on a local date, ascending.

    The grid steps in wall-clock minutes from `opens`; skipped local times never appear and
    a repeated local time appears once, as its first occurrence. A slot is offered when it
    ends, in absolute time, no later than `closes` (§8, §9).
    """
    tz = restaurant.tz
    midnight = datetime.combine(day, time())
    duration = timeutil.minutes(restaurant.duration_minutes)
    slots = {}
    for hours in restaurant.hours_on(timeutil.weekday_name(day)):
        closes_at = timeutil.to_instant(tz, midnight + timeutil.minutes(hours.closes_min))
        for minute in range(hours.opens_min, hours.closes_min, restaurant.slot_minutes):
            local = midnight + timeutil.minutes(minute)
            if not timeutil.exists(tz, local):
                continue
            start = timeutil.to_instant(tz, local)
            if start + duration <= closes_at:
                slots[local] = start
    return sorted(slots.items())


def availability(state: State, restaurant: Restaurant, day: date, party_size: int) -> dict:
    """Free seating per slot: single tables (`available_table_ids`) and every option."""
    tz = restaurant.tz
    duration = timeutil.minutes(restaurant.duration_minutes)
    booked = [r for r in state.at_restaurant(restaurant.id) if r.confirmed]
    options = [(ids, capacity) for ids, capacity in restaurant.options() if capacity >= party_size]
    slots = []
    for local, start in day_slots(restaurant, day):
        end = start + duration
        taken = {t for r in booked if r.overlaps(start, end) for t in r.table_ids}
        free = [{"table_ids": list(ids), "capacity": capacity}
                for ids, capacity in options if not taken.intersection(ids)]
        slots.append({"starts_at_local": timeutil.format_local(local),
                      "starts_at": timeutil.render(start, tz),
                      "available_table_ids": [o["table_ids"][0] for o in free
                                              if len(o["table_ids"]) == 1],
                      "available_options": free})
    return {"restaurant_id": restaurant.id, "date": day.isoformat(),
            "timezone": restaurant.timezone, "slots": slots}


# ----------------------------------------------------------------------------- rules

def check_table_types(body: dict) -> None:
    """400 when `table_id` is not a string or `table_ids` is not an array of strings."""
    string_field(body, "table_id")
    if "table_ids" in body:
        table_ids = body["table_ids"]
        if not isinstance(table_ids, list) or not all(isinstance(t, str) for t in table_ids):
            raise malformed("table_ids must be an array of table id strings")


def requested_tables(body: dict, *, required: bool):
    """The requested table ids, or MISSING when an amendment leaves the tables alone.

    Shape rules (decision A-20): exactly one of `table_id` / `table_ids`, a non-empty set,
    no duplicate ids. Types were already checked by `check_table_types`.
    """
    has_one, has_set = "table_id" in body, "table_ids" in body
    if has_one and has_set:
        raise invalid("send either table_id or table_ids, not both")
    if not has_one and not has_set:
        if required:
            raise invalid("missing required field: table_id or table_ids")
        return MISSING
    table_ids = [body["table_id"]] if has_one else list(body["table_ids"])
    if not table_ids:
        raise invalid("table_ids must name at least one table")
    for table_id in table_ids:
        check_id(table_id, "table_ids")
    if len(set(table_ids)) != len(table_ids):
        raise invalid("table_ids must not repeat a table")
    return table_ids


def select_tables(restaurant: Restaurant, table_ids: list[str]) -> list[Table]:
    """The tables of a requested set, in stored order (a pair in its declared order).

    404 for an unknown table or one of another restaurant; 422 combination_not_allowed
    for more than two tables or a pair the restaurant has not declared.
    """
    tables = []
    for table_id in table_ids:
        table = restaurant.table(table_id)
        if table is None:
            raise not_found("no such table at this restaurant")
        tables.append(table)
    if len(tables) == 1:
        return tables
    pair = restaurant.pair(table_ids) if len(tables) == 2 else None
    if pair is None:
        raise ApiError(422, "combination_not_allowed",
                       "only a declared pair of tables can be combined")
    return [restaurant.table(table_id) for table_id in pair]


def place(restaurant: Restaurant, tables: list[Table], local: datetime,
          party_size: int) -> Placement:
    """Validate a start, table set and party size against the restaurant's rules (§8, §9).

    Order (decision A-02): nonexistent local time, opening hours, slot grid, capacity.
    """
    tz = restaurant.tz
    if not timeutil.exists(tz, local):
        raise ApiError(422, "invalid_local_time", "that local time does not exist (DST gap)")
    start = timeutil.to_instant(tz, local)
    end = start + timeutil.minutes(restaurant.duration_minutes)
    minute = local.hour * 60 + local.minute
    midnight = datetime.combine(local.date(), time())
    hours = next((h for h in restaurant.hours_on(timeutil.weekday_name(local.date()))
                  if h.opens_min <= minute < h.closes_min), None)
    if hours is None or end > timeutil.to_instant(tz, midnight + timeutil.minutes(hours.closes_min)):
        raise ApiError(422, "outside_opening_hours", "the booking is outside opening hours")
    if (minute - hours.opens_min) % restaurant.slot_minutes:
        raise ApiError(422, "not_on_slot_grid", "the start is not on the slot grid")
    if party_size > sum(t.capacity for t in tables):
        raise ApiError(422, "party_exceeds_capacity", "the party is larger than the seating")
    return Placement(tuple(t.id for t in tables), local, start, end, party_size)


def ensure_free(state: State, restaurant: Restaurant, placements: dict[str, Placement]) -> None:
    """409 table_unavailable unless the resulting bookings never share a table in time.

    `placements` maps the ids of bookings being (re)placed to where they will sit; a new
    booking uses a key no reservation has. Every other confirmed booking at the restaurant
    keeps its current occupancy.
    """
    fixed = [r for r in state.at_restaurant(restaurant.id)
             if r.confirmed and r.id not in placements]
    moving = list(placements.values())
    for i, p in enumerate(moving):
        for r in fixed:
            if set(p.table_ids) & set(r.table_ids) and r.overlaps(p.start, p.end):
                raise _taken()
        for q in moving[i + 1:]:
            if set(p.table_ids) & set(q.table_ids) and q.start < p.end and p.start < q.end:
                raise _taken()


def _taken() -> ApiError:
    return ApiError(409, "table_unavailable", "the table is taken at that time")


def check_cutoff(restaurant: Restaurant, res: Reservation, now: datetime) -> None:
    """Refused when now is within the cutoff of the current start, or later (A-03).

    Compared in seconds so that any cutoff, however large, cannot overflow date arithmetic.
    """
    if (res.start - now).total_seconds() <= restaurant.cutoff_minutes * 60:
        raise ApiError(409, "cutoff_passed", "too close to the start to change or cancel")


def owned(state: State, user: User, reference: str) -> Reservation:
    """The caller's reservation; anyone else's is indistinguishable from a missing one."""
    res = state.reservation_by_reference(reference)
    if res is None or res.user_id != user.id:
        raise not_found("no such reservation")
    return res


# ----------------------------------------------------------------------------- create

def create(state: State, user: User, body: dict) -> dict:
    """POST /reservations after authentication and idempotency (decisions A-02, A-20)."""
    restaurant_id = string_field(body, "restaurant_id")
    check_table_types(body)
    local_text = string_field(body, "starts_at_local")
    require_present(body, ("restaurant_id", "starts_at_local", "party_size"))
    table_ids = requested_tables(body, required=True)
    check_id(restaurant_id, "restaurant_id")
    party_size = check_party_size(body["party_size"])
    local = timeutil.parse_local_datetime(local_text)

    restaurant = state.restaurants.get(restaurant_id)
    if restaurant is None:
        raise not_found("no such restaurant")
    placement = place(restaurant, select_tables(restaurant, table_ids), local, party_size)
    res_id = state.new_reservation_id()
    ensure_free(state, restaurant, {res_id: placement})

    res = Reservation(
        id=res_id, reference=state.new_reference(), user_id=user.id,
        restaurant_id=restaurant.id, table_ids=list(placement.table_ids),
        party_size=party_size, status=CONFIRMED, local=placement.local,
        start=placement.start, end=placement.end,
        created_at=timeutil.render(timeutil.now()), seq=state.take_seq())
    state.add_reservation(res)
    return res.to_response(restaurant.tz)


# ----------------------------------------------------------------------------- amend

def check_amendment_types(body: dict) -> None:
    """400 for a PATCH field of the wrong JSON type (`party_size` is always 422 instead)."""
    check_table_types(body)
    string_field(body, "starts_at_local")


def plan_amendment(state: State, restaurant: Restaurant, res: Reservation, body: dict,
                   now: datetime) -> Placement | None:
    """Validate one amendment; return its placement, or None when it changes nothing.

    Order (decisions A-04, A-20): cancelled, cutoff against the current start, field
    formats, then the create rules on the merged booking. Nothing is mutated here. A table
    set equal to the current one in any order is not a change.
    """
    if not res.confirmed:
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    check_cutoff(restaurant, res, now)

    table_ids = requested_tables(body, required=False)
    local_text = body.get("starts_at_local", MISSING)
    party_size = body.get("party_size", MISSING)
    if party_size is not MISSING:
        check_party_size(party_size)
    local = timeutil.parse_local_datetime(local_text) if local_text is not MISSING else res.local

    table_ids = res.table_ids if table_ids is MISSING else table_ids
    party_size = res.party_size if party_size is MISSING else party_size
    if (set(table_ids), local, party_size) == (set(res.table_ids), res.local, res.party_size):
        return None
    return place(restaurant, select_tables(restaurant, table_ids), local, party_size)


def apply_placement(res: Reservation, placement: Placement) -> None:
    res.table_ids = list(placement.table_ids)
    res.local = placement.local
    res.start = placement.start
    res.end = placement.end
    res.party_size = placement.party_size


def amend(state: State, user: User, reference: str, body: dict, now: datetime) -> dict:
    """PATCH /reservations/{reference} (§8, decision A-04)."""
    res = owned(state, user, reference)
    restaurant = state.restaurants[res.restaurant_id]
    check_amendment_types(body)
    placement = plan_amendment(state, restaurant, res, body, now)
    if placement is not None:
        ensure_free(state, restaurant, {res.id: placement})
        apply_placement(res, placement)
    return res.to_response(restaurant.tz)


# ----------------------------------------------------------------------------- cancel

def cancel(state: State, user: User, reference: str, now: datetime) -> dict:
    """POST /reservations/{reference}/cancel (§8, decision A-05); frees every table."""
    res = owned(state, user, reference)
    restaurant = state.restaurants[res.restaurant_id]
    if res.status != CANCELLED:
        check_cutoff(restaurant, res, now)
        res.status = CANCELLED
    return res.to_response(restaurant.tz)


# ----------------------------------------------------------------------------- list

def list_for(state: State, user: User) -> dict:
    mine = [r for r in state.reservations.values() if r.user_id == user.id]
    mine.sort(key=lambda r: (r.start, r.seq), reverse=True)
    return {"reservations": [r.to_response(state.restaurants[r.restaurant_id].tz) for r in mine]}


# ----------------------------------------------------------------------------- moves

MAX_MOVES = 8


def _move_items(body: dict) -> list[dict]:
    moves = body.get("moves", MISSING)
    if not isinstance(moves, list) or not 1 <= len(moves) <= MAX_MOVES:
        raise invalid(f"moves must be an array of 1 to {MAX_MOVES} objects")
    references = set()
    for item in moves:
        if not isinstance(item, dict) or not isinstance(item.get("reference"), str):
            raise invalid("each move must be an object with a string reference")
        if item["reference"] in references:
            raise invalid("each reference may appear only once")
        references.add(item["reference"])
    return moves


def move(state: State, user: User, body: dict, now: datetime) -> dict:
    """POST /reservation-moves: every move commits or none does (§11, decision A-12)."""
    items = _move_items(body)
    listed: list[Reservation] = []
    placements: dict[str, Placement] = {}
    restaurant = None
    for item in items:
        res = owned(state, user, item["reference"])
        if restaurant is None:
            restaurant = state.restaurants[res.restaurant_id]
        elif res.restaurant_id != restaurant.id:
            raise invalid("all moved bookings must be at the same restaurant")
        check_amendment_types(item)
        placement = plan_amendment(state, restaurant, res, item, now)
        if placement is not None:
            placements[res.id] = placement
        listed.append(res)

    ensure_free(state, restaurant, placements)
    for res in listed:
        if res.id in placements:
            apply_placement(res, placements[res.id])
    return {"reservations": [res.to_response(restaurant.tz) for res in listed]}
