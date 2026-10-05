"""Seating changes after a table closure: plan preview and application (stage 4).

Runs with the store lock held. A preview stores only the plan. Application re-checks that
nothing at the restaurant changed since the preview (its revision), then records the
closure and every reassignment in one step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from . import timeutil
from .booking import history_time, touch_series
from .errors import ApiError, invalid, not_found
from .model import Closure, Plan, Reservation, Restaurant, State, User

# Inputs up to the spec's guaranteed size are always planned exactly. Larger ones are tried
# under a search budget and refused with 422 planning_limit if they exceed it.
GUARANTEED_TABLES, GUARANTEED_PAIRS, GUARANTEED_BOOKINGS = 6, 4, 6
MAX_BOOKINGS = 12
SEARCH_BUDGET = 20_000      # search nodes (well under a second) for inputs beyond the guaranteed size


class _OverBudget(Exception):
    pass
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})", re.ASCII)


def managed_restaurant(state: State, user: User, restaurant_id: str) -> Restaurant:
    restaurant = state.restaurants.get(restaurant_id)
    if restaurant is None:
        raise not_found("no such restaurant")
    if user.id not in restaurant.manager_user_ids:
        raise ApiError(403, "forbidden", "only this restaurant's managers may change seating")
    return restaurant


def _instant(body: dict, field: str) -> datetime:
    value = body.get(field)
    if not isinstance(value, str) or not _INSTANT.fullmatch(value):
        raise invalid(f"{field} must be an RFC 3339 timestamp with an offset")
    try:
        return datetime.fromisoformat(value).astimezone(timeutil.UTC)
    except ValueError:
        raise invalid(f"{field} is not a real timestamp") from None


@dataclass(frozen=True)
class Option:
    rank: int
    table_ids: tuple[str, ...]
    unused: int
    changed: bool


def preview(state: State, user: User, restaurant_id: str, body: dict) -> dict:
    """POST /restaurants/{id}/replans after authentication and idempotency (decision A-36)."""
    restaurant = managed_restaurant(state, user, restaurant_id)
    table_id = body.get("table_id")
    if not isinstance(table_id, str) or not table_id:
        raise invalid("table_id must be a table id")
    start, end = _instant(body, "from"), _instant(body, "to")
    if not start < end:
        raise invalid("from must be earlier than to")
    if restaurant.table(table_id) is None:
        raise not_found("no such table at this restaurant")

    considered = sorted((r for r in state.at_restaurant(restaurant.id)
                         if r.confirmed and r.overlaps(start, end)), key=lambda r: r.reference)
    guaranteed = (len(restaurant.tables) <= GUARANTEED_TABLES
                  and len(restaurant.combinable) <= GUARANTEED_PAIRS
                  and len(considered) <= GUARANTEED_BOOKINGS)
    proposed = Closure(restaurant.id, table_id, start, end, "proposed")
    try:
        if len(considered) > MAX_BOOKINGS:
            raise _OverBudget()
        choice = _solve(state, restaurant, considered, proposed,
                        budget=None if guaranteed else SEARCH_BUDGET)
    except _OverBudget:
        raise ApiError(422, "planning_limit", "this closure is too large to plan") from None
    if choice is None:
        raise ApiError(409, "no_feasible_plan", "no seating keeps every booking")

    plan = Plan(
        id=state.new_plan_id(), restaurant_id=restaurant.id,
        closure={"table_id": table_id, "from": body["from"], "to": body["to"]},
        start=start, end=end, restaurant_revision=state.restaurant_revision[restaurant.id],
        assignments=[{"reference": r.reference, "table_ids": list(o.table_ids), "changed": o.changed}
                     for r, o in zip(considered, choice)],
        moved_count=sum(o.changed for o in choice), unused_seats=sum(o.unused for o in choice))
    state.plans[plan.id] = plan
    return plan.preview()


def _solve(state: State, restaurant: Restaurant, considered: list[Reservation],
           proposed: Closure, budget: int | None) -> list[Option] | None:
    """The best feasible assignment, or None.

    Lexicographic objective: bookings moved, then unused seats, then the vector of option
    ranks in reference order. A depth-first search over bookings in reference order, trying
    options in rank order, meets assignments in increasing rank-vector order, so pruning any
    branch that cannot beat the best (moved, unused) found so far leaves the optimum.
    """
    options = [(t.id,) for t in restaurant.tables] + list(restaurant.combinable)
    considered_ids = {r.id for r in considered}
    fixed = [r for r in state.at_restaurant(restaurant.id)
             if r.confirmed and r.id not in considered_ids]
    closures = state.closures_at(restaurant.id) + [proposed]

    candidates: list[list[Option]] = []
    for res in considered:
        capacity = res.terms["capacities"]
        current = set(res.table_ids)
        mine = []
        for rank, table_ids in enumerate(options):
            seats = sum(capacity.get(t, 0) for t in table_ids)
            if seats < res.party_size:
                continue
            if any(c.blocks(table_ids, res.start, res.end) for c in closures):
                continue
            if any(set(table_ids) & set(r.table_ids) and r.overlaps(res.start, res.end) for r in fixed):
                continue
            mine.append(Option(rank, tuple(table_ids), seats - res.party_size, set(table_ids) != current))
        if not mine:
            return None
        candidates.append(mine)

    n = len(considered)
    clashes = [[j for j in range(i) if considered[j].overlaps(considered[i].start, considered[i].end)]
               for i in range(n)]
    # Lower bounds for what the bookings from i onwards must still add.
    must_move = [0] * (n + 1)
    least_unused = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        must_move[i] = must_move[i + 1] + all(o.changed for o in candidates[i])
        least_unused[i] = least_unused[i + 1] + min(o.unused for o in candidates[i])

    best: list = [None, None]   # [(moved, unused), choice]
    chosen: list[Option] = []
    nodes = [0]

    def search(i: int, moved: int, unused: int) -> None:
        nodes[0] += 1
        if budget is not None and nodes[0] > budget:
            raise _OverBudget()
        if best[0] is not None and (moved + must_move[i], unused + least_unused[i]) >= best[0]:
            return
        if i == n:
            best[0], best[1] = (moved, unused), list(chosen)
            return
        for option in candidates[i]:
            if any(set(option.table_ids) & set(chosen[j].table_ids) for j in clashes[i]):
                continue
            chosen.append(option)
            search(i + 1, moved + option.changed, unused + option.unused)
            chosen.pop()

    search(0, 0, 0)
    return best[1]


def apply(state: State, user: User, restaurant_id: str, plan_id: str, now: datetime) -> dict:
    """POST /restaurants/{id}/replans/{plan_id}/apply (decision A-37); all or nothing."""
    restaurant = managed_restaurant(state, user, restaurant_id)
    plan = state.plans.get(plan_id)
    if plan is None or plan.restaurant_id != restaurant.id:
        raise not_found("no such plan")
    if plan.applied:
        raise ApiError(409, "plan_already_applied", "this plan has already been applied")
    if state.restaurant_revision[restaurant.id] != plan.restaurant_revision:
        raise ApiError(409, "stale_plan", "the restaurant has changed since this plan was made")

    state.closures.append(Closure(restaurant.id, plan.closure["table_id"], plan.start, plan.end, plan.id))
    considered = [state.reservation_by_reference(a["reference"]) for a in plan.assignments]
    moved = []
    for res, assignment in zip(considered, plan.assignments):
        if assignment["changed"]:
            _reassign(restaurant, res, assignment["table_ids"], plan.id, now)
            moved.append(res)
    touch_series(state, moved)
    state.bump_restaurant(restaurant.id)
    plan.applied = True
    return {"plan_id": plan.id, "restaurant_revision": state.restaurant_revision[restaurant.id],
            "reservations": [r.to_response(restaurant.tz) for r in considered]}


def _reassign(restaurant: Restaurant, res: Reservation, table_ids: list[str], plan_id: str,
              now: datetime) -> None:
    """An operator repair: new tables only; times, terms and exception flags are kept."""
    change = {"field": "table_ids", "from": list(res.table_ids), "to": list(table_ids)}
    res.table_ids = list(table_ids)
    res.revision += 1
    res.record("reassigned", [change], history_time(restaurant, now), plan_id=plan_id)
