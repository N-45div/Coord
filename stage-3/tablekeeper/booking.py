"""Booking rules: availability, placement validation, occupancy, create, amend, cancel, moves.

Every function here runs with the store lock held, so each request sees and changes the
state as if it ran alone. Writes validate everything first and mutate only at the end:

- `select_tables` and `place` are the one place a table set, start time and party size
  are checked against the rules of the policy selected for the booking's local date;
- `ensure_free` is the one place occupancy is checked, over the whole resulting set of
  bookings (§1, §11);
- `apply_change` and `cancel_one` are the one place a booking's fields, accepted terms,
  revision and history change, and with them its series' bookkeeping.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime, time

from . import timeutil
from .errors import ApiError, invalid, malformed, not_found
from .model import (CANCELLED, CONFIRMED, Reservation, Restaurant, State, Table, User,
                    created_changes, table_change)
from .policies import Policy
from .validate import (MISSING, check_id, check_party_size, is_int, require_present,
                       string_field)


@dataclass(frozen=True)
class Placement:
    """Where and when a booking sits once a write is applied, and the policy it accepts."""
    table_ids: tuple[str, ...]
    local: datetime
    start: datetime
    end: datetime
    party_size: int
    policy: Policy


# ----------------------------------------------------------------------------- availability

def day_slots(restaurant: Restaurant, policy: Policy, day: date) -> list[tuple[datetime, datetime]]:
    """(local start, UTC start) for every bookable slot on a local date, ascending.

    The grid steps in wall-clock minutes from `opens`; skipped local times never appear and
    a repeated local time appears once, as its first occurrence. A slot is offered when it
    ends, in absolute time, no later than `closes` (§8, §9).
    """
    tz = restaurant.tz
    midnight = datetime.combine(day, time())
    duration = timeutil.minutes(policy.duration_minutes)
    slots = {}
    for hours in policy.hours_on(timeutil.weekday_name(day)):
        closes_at = timeutil.to_instant(tz, midnight + timeutil.minutes(hours.closes_min))
        for minute in range(hours.opens_min, hours.closes_min, policy.slot_minutes):
            local = midnight + timeutil.minutes(minute)
            if not timeutil.exists(tz, local):
                continue
            start = timeutil.to_instant(tz, local)
            if start + duration <= closes_at:
                slots[local] = start
    return sorted(slots.items())


def seating_options(restaurant: Restaurant, policy: Policy) -> list[tuple[tuple[str, ...], int]]:
    """Every seating option with its capacity under `policy`: singles, then declared pairs."""
    singles = [((t.id,), policy.capacity(t.id)) for t in restaurant.tables]
    pairs = [(p, policy.capacity(p[0]) + policy.capacity(p[1])) for p in restaurant.combinable]
    return singles + pairs


def availability(state: State, restaurant: Restaurant, day: date, party_size: int,
                 explain: bool) -> dict:
    """Free seating per slot, under the policy selected for `day` (stage 3)."""
    tz = restaurant.tz
    policy = state.policy_for(restaurant, day)
    duration = timeutil.minutes(policy.duration_minutes)
    booked = [r for r in state.at_restaurant(restaurant.id) if r.confirmed]
    options = [(ids, cap) for ids, cap in seating_options(restaurant, policy) if cap >= party_size]
    slots = []
    for local, start in day_slots(restaurant, policy, day):
        end = start + duration
        taken = {t for r in booked if r.overlaps(start, end) for t in r.table_ids}
        free = [{"table_ids": list(ids), "capacity": cap}
                for ids, cap in options if not taken.intersection(ids)]
        slot = {"starts_at_local": timeutil.format_local(local),
                "starts_at": timeutil.render(start, tz),
                "available_table_ids": [o["table_ids"][0] for o in free if len(o["table_ids"]) == 1],
                "available_options": free}
        if explain:
            slot["explain"] = [_explain(t, policy, party_size, t.id not in taken)
                               for t in restaurant.tables]
        slots.append(slot)
    return {"restaurant_id": restaurant.id, "date": day.isoformat(),
            "timezone": restaurant.timezone, "slots": slots}


def _explain(table: Table, policy: Policy, party_size: int, free: bool) -> dict:
    fits = party_size <= policy.capacity(table.id)
    return {"table_id": table.id, "policy_version": policy.version, "available": fits and free,
            "rules": [{"rule": "capacity", "holds": fits}, {"rule": "no_overlap", "holds": free}]}


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


def place(state: State, restaurant: Restaurant, tables: list[Table], local: datetime,
          party_size: int) -> Placement:
    """Validate a start, table set and party size under the policy for the start's date.

    Order (decision A-02): nonexistent local time, opening hours, slot grid, capacity.
    """
    tz = restaurant.tz
    policy = state.policy_for(restaurant, local.date())
    if not timeutil.exists(tz, local):
        raise ApiError(422, "invalid_local_time", "that local time does not exist (DST gap)")
    start = timeutil.to_instant(tz, local)
    end = start + timeutil.minutes(policy.duration_minutes)
    minute = local.hour * 60 + local.minute
    midnight = datetime.combine(local.date(), time())
    hours = next((h for h in policy.hours_on(timeutil.weekday_name(local.date()))
                  if h.opens_min <= minute < h.closes_min), None)
    if hours is None or end > timeutil.to_instant(tz, midnight + timeutil.minutes(hours.closes_min)):
        raise ApiError(422, "outside_opening_hours", "the booking is outside opening hours")
    if (minute - hours.opens_min) % policy.slot_minutes:
        raise ApiError(422, "not_on_slot_grid", "the start is not on the slot grid")
    if party_size > sum(policy.capacity(t.id) for t in tables):
        raise ApiError(422, "party_exceeds_capacity", "the party is larger than the seating")
    return Placement(tuple(t.id for t in tables), local, start, end, party_size, policy)


def ensure_free(state: State, restaurant: Restaurant, placements: dict[str, Placement]) -> None:
    """409 table_unavailable unless the resulting bookings never share a table in time.

    `placements` maps the ids of bookings being (re)placed to where they will sit, in the
    order they are judged; a new booking uses a key no reservation has. Every other
    confirmed booking at the restaurant keeps its current occupancy.
    """
    fixed = [r for r in state.at_restaurant(restaurant.id)
             if r.confirmed and r.id not in placements]
    moving = list(placements.values())
    for i, p in enumerate(moving):
        for r in fixed:
            if set(p.table_ids) & set(r.table_ids) and r.overlaps(p.start, p.end):
                raise _taken()
        for q in moving[:i]:
            if set(p.table_ids) & set(q.table_ids) and q.start < p.end and p.start < q.end:
                raise _taken()


def _taken() -> ApiError:
    return ApiError(409, "table_unavailable", "the table is taken at that time")


def check_cutoff(res: Reservation, now: datetime) -> None:
    """Refused when now is within the booking's accepted cutoff of its start, or later.

    Compared in seconds so that any cutoff, however large, cannot overflow date arithmetic.
    """
    if (res.start - now).total_seconds() <= res.cutoff_minutes * 60:
        raise ApiError(409, "cutoff_passed", "too close to the start to change or cancel")


def owned(state: State, user: User | None, reference: str) -> Reservation:
    """The caller's reservation; anyone else's is indistinguishable from a missing one."""
    res = state.reservation_by_reference(reference)
    if res is None or user is None or res.user_id != user.id:
        raise not_found("no such reservation")
    return res


def history_time(restaurant: Restaurant, now: datetime) -> str:
    return timeutil.render(now, restaurant.tz)


# ----------------------------------------------------------------------------- create

def new_reservation(state: State, restaurant: Restaurant, user_id: str, placement: Placement,
                    now: datetime, res_id: str | None = None) -> Reservation:
    """A confirmed booking at revision 1 under its placement's policy, with its history."""
    res = Reservation(
        id=res_id or state.new_reservation_id(), reference=state.new_reference(),
        user_id=user_id, restaurant_id=restaurant.id, table_ids=list(placement.table_ids),
        party_size=placement.party_size, status=CONFIRMED, local=placement.local,
        start=placement.start, end=placement.end, created_at=timeutil.render(now),
        seq=state.take_seq(), revision=1, terms=placement.policy.terms())
    res.record("created", created_changes(res), history_time(restaurant, now))
    state.add_reservation(res)
    return res


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
    placement = place(state, restaurant, select_tables(restaurant, table_ids), local, party_size)
    res_id = state.new_reservation_id()
    ensure_free(state, restaurant, {res_id: placement})

    now = timeutil.now()
    res = new_reservation(state, restaurant, user.id, placement, now, res_id)
    state.bump_restaurant(restaurant.id)
    return res.to_response(restaurant.tz)


# ----------------------------------------------------------------------------- amend

def check_amendment_types(body: dict) -> None:
    """400 for a PATCH field of the wrong JSON type (`party_size` is always 422 instead)."""
    check_table_types(body)
    string_field(body, "starts_at_local")


def check_expected_revision(body: dict, res: Reservation) -> None:
    """Optional `expected_revision`: 422 unless a positive integer, 409 when stale (A-29)."""
    if "expected_revision" not in body:
        return
    expected = body["expected_revision"]
    if not is_int(expected) or expected < 1:
        raise invalid("expected_revision must be a positive integer")
    if expected != res.revision:
        raise ApiError(409, "stale_revision", "the reservation has changed since that revision")


def plan_amendment(state: State, restaurant: Restaurant, res: Reservation, body: dict,
                   now: datetime) -> Placement | None:
    """Validate one amendment; return its placement, or None when it changes nothing.

    Order (decision A-29): expected revision, cancelled, the old accepted cutoff, field
    formats, then the create rules on the merged booking under the policy for its
    resulting date. Nothing is mutated here. A table set equal to the current one in any
    order is not a change.
    """
    check_expected_revision(body, res)
    if not res.confirmed:
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    check_cutoff(res, now)

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
    return place(state, restaurant, select_tables(restaurant, table_ids), local, party_size)


def apply_change(state: State, restaurant: Restaurant, res: Reservation, placement: Placement,
                 now: datetime, *, event: str = "changed", exception: bool = True,
                 **extra) -> None:
    """Commit a validated real change: fields, accepted terms, end, one revision, one entry.

    A diner's change of a series occurrence marks it a permanent exception (stage 3); the
    series revision itself is bumped once per operation by the caller (`touch_series`).
    """
    changes = [c for c in (
        table_change(res.table_ids, list(placement.table_ids)),
        _field_change("starts_at_local", timeutil.format_local(res.local), timeutil.format_local(placement.local)),
        _field_change("party_size", res.party_size, placement.party_size),
    ) if c is not None]
    res.table_ids = list(placement.table_ids)
    res.local = placement.local
    res.start = placement.start
    res.end = placement.end
    res.party_size = placement.party_size
    res.terms = placement.policy.terms()
    res.revision += 1
    res.record(event, changes, history_time(restaurant, now), **extra)
    if exception and res.series_id is not None:
        occurrence = state.series[res.series_id].occurrence_of(res.id)
        if occurrence is not None:
            occurrence.exception = True


def _field_change(name: str, before, after) -> dict | None:
    return None if before == after else {"field": name, "from": before, "to": after}


def touch_series(state: State, reservations: list[Reservation]) -> None:
    """Bump the revision of every series these changed bookings belong to, once each."""
    for series_id in {r.series_id for r in reservations if r.series_id is not None}:
        state.series[series_id].revision += 1


def amend(state: State, user: User, reference: str, body: dict, now: datetime) -> dict:
    """PATCH /reservations/{reference} (§8, decision A-29)."""
    res = owned(state, user, reference)
    restaurant = state.restaurants[res.restaurant_id]
    check_amendment_types(body)
    placement = plan_amendment(state, restaurant, res, body, now)
    if placement is not None:
        ensure_free(state, restaurant, {res.id: placement})
        apply_change(state, restaurant, res, placement, now)
        touch_series(state, [res])
        state.bump_restaurant(restaurant.id)
    return res.to_response(restaurant.tz)


# ----------------------------------------------------------------------------- cancel

def cancel(state: State, user: User, reference: str, now: datetime) -> dict:
    """POST /reservations/{reference}/cancel (§8, decision A-05); frees every table."""
    res = owned(state, user, reference)
    restaurant = state.restaurants[res.restaurant_id]
    if res.status != CANCELLED:
        check_cutoff(res, now)
        res.status = CANCELLED
        res.revision += 1
        res.record("cancelled", [], history_time(restaurant, now))
        touch_series(state, [res])
        state.bump_restaurant(restaurant.id)
    return res.to_response(restaurant.tz)


# ----------------------------------------------------------------------------- reads

def list_for(state: State, user: User) -> dict:
    mine = [r for r in state.reservations.values() if r.user_id == user.id]
    mine.sort(key=lambda r: (r.start, r.seq), reverse=True)
    return {"reservations": [r.to_response(state.restaurants[r.restaurant_id].tz) for r in mine]}


def history(state: State, user: User | None, reference: str) -> dict:
    res = owned(state, user, reference)
    return {"reference": res.reference, "entries": [dict(e) for e in res.history]}


def decision(state: State, user: User | None, reference: str) -> dict:
    res = owned(state, user, reference)
    return {"reference": res.reference, "revision": res.revision,
            "accepted_terms": copy.deepcopy(res.terms)}


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
    """POST /reservation-moves: every move commits or none does (§11, decisions A-12, A-29)."""
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
    changed = [res for res in listed if res.id in placements]
    for res in changed:
        apply_change(state, restaurant, res, placements[res.id], now)
    if changed:
        touch_series(state, changed)
        state.bump_restaurant(restaurant.id)
    return {"reservations": [res.to_response(restaurant.tz) for res in listed]}
