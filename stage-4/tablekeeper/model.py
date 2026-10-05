"""In-memory state: restaurants and their policies, users, tokens, reservations with their
revisions and histories, recurring series, seating plans and table closures, and
idempotency receipts.

`State` is plain data. Reset and import build a complete new `State` and swap it in whole;
every read and write of the live one happens under `Store.lock` (store.py).
"""
from __future__ import annotations

import copy
import hashlib
import re
import secrets
import string
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import timeutil
from .policies import Hours, Policy, parse_hours, policy_from_state, select
from .validate import MAX_ID, is_int

CONFIRMED = "confirmed"
CANCELLED = "cancelled"
_REFERENCE_ALPHABET = string.ascii_uppercase + string.digits
_REFERENCE = re.compile(r"[A-Z0-9]{6,12}")   # §8: 6 to 12 characters of A-Z0-9
# Slot and duration bound (~950 years) that keeps start + duration inside datetime's range.
# The cutoff has no bound: it is compared numerically, never added to a date.
MAX_MINUTES = 500_000_000


def is_reference(value) -> bool:
    return isinstance(value, str) and _REFERENCE.fullmatch(value) is not None


# ----------------------------------------------------------------------------- restaurants

@dataclass(frozen=True)
class Table:
    id: str
    label: str
    capacity: int

    def to_json(self) -> dict:
        return {"id": self.id, "label": self.label, "capacity": self.capacity}


@dataclass(frozen=True)
class Restaurant:
    """A restaurant's fixture configuration. It never changes; policies are kept in State."""
    id: str
    name: str
    timezone: str
    slot_minutes: int
    duration_minutes: int
    cutoff_minutes: int
    opening_hours: tuple[Hours, ...]
    tables: tuple[Table, ...]
    combinable: tuple[tuple[str, str], ...] = ()   # declared pairs, in declaration order
    manager_user_ids: tuple[str, ...] = ()

    @property
    def tz(self) -> ZoneInfo:
        return timeutil.zone(self.timezone)

    @property
    def table_ids(self) -> list[str]:
        return [t.id for t in self.tables]

    def table(self, table_id: str) -> Table | None:
        for table in self.tables:
            if table.id == table_id:
                return table
        return None

    def pair(self, table_ids) -> tuple[str, str] | None:
        """The declared pair naming exactly these two tables, in its declared order."""
        wanted = set(table_ids)
        return next((p for p in self.combinable if set(p) == wanted), None)

    def policy_zero(self) -> Policy:
        """The fixture's own rules: policy 0, in force before any published policy."""
        return Policy(0, None, self.slot_minutes, self.duration_minutes, self.cutoff_minutes,
                      self.opening_hours, tuple((t.id, t.capacity) for t in self.tables))

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "timezone": self.timezone}

    def to_json(self) -> dict:
        """The fixture's shape; also the restaurant detail response."""
        return {
            "id": self.id,
            "name": self.name,
            "timezone": self.timezone,
            "slot_minutes": self.slot_minutes,
            "reservation_duration_minutes": self.duration_minutes,
            "cancellation_cutoff_minutes": self.cutoff_minutes,
            "opening_hours": [h.to_json() for h in self.opening_hours],
            "tables": [t.to_json() for t in self.tables],
            "combinable": [list(p) for p in self.combinable],
        }

    def to_state(self) -> dict:
        return {**self.to_json(), "manager_user_ids": list(self.manager_user_ids)}


# ----------------------------------------------------------------------------- people

@dataclass
class User:
    id: str
    email: str
    display_name: str
    password_hash: str

    def to_json(self) -> dict:
        return {"id": self.id, "email": self.email, "display_name": self.display_name,
                "password_hash": self.password_hash}


def email_key(email: str) -> str:
    return email.casefold()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- reservations

@dataclass
class Reservation:
    id: str
    reference: str
    user_id: str
    restaurant_id: str
    table_ids: list[str]
    party_size: int
    status: str
    local: datetime      # naive wall-clock start at the restaurant
    start: datetime      # UTC instant
    end: datetime        # UTC instant; start + the accepted duration, in absolute time
    created_at: str      # rendered once, never regenerated
    seq: int             # creation order, the deterministic tie-break for listings
    revision: int = 1
    terms: dict = field(default_factory=dict)       # accepted terms (a policy snapshot)
    history: list[dict] = field(default_factory=list)
    series_id: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.status == CONFIRMED

    @property
    def cutoff_minutes(self) -> int:
        return self.terms["cancellation_cutoff_minutes"]

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end

    def record(self, event: str, changes: list[dict], at: str, **extra) -> None:
        """Append a history entry carrying the resulting revision and terms (stage 3)."""
        self.history.append({
            "seq": len(self.history) + 1, "at": at, "event": event, "changes": changes,
            **extra, "revision": self.revision, "accepted_terms": copy.deepcopy(self.terms),
        })

    def to_response(self, tz: ZoneInfo) -> dict:
        tables = {"table_id": self.table_ids[0]} if len(self.table_ids) == 1 else {}
        return {
            "reservation_id": self.id,
            "reference": self.reference,
            "restaurant_id": self.restaurant_id,
            **tables,
            "table_ids": list(self.table_ids),
            "party_size": self.party_size,
            "status": self.status,
            "starts_at_local": timeutil.format_local(self.local),
            "starts_at": timeutil.render(self.start, tz),
            "ends_at": timeutil.render(self.end, tz),
            "created_at": self.created_at,
            "revision": self.revision,
            "accepted_terms": copy.deepcopy(self.terms),
        }

    def to_json(self) -> dict:
        return {
            "id": self.id, "reference": self.reference, "user_id": self.user_id,
            "restaurant_id": self.restaurant_id, "table_ids": list(self.table_ids),
            "party_size": self.party_size, "status": self.status,
            "starts_at_local": timeutil.format_local(self.local),
            "starts_at": timeutil.render(self.start), "ends_at": timeutil.render(self.end),
            "created_at": self.created_at, "seq": self.seq, "revision": self.revision,
            "terms": copy.deepcopy(self.terms), "history": copy.deepcopy(self.history),
            "series_id": self.series_id,
        }


def table_change(before: list[str] | None, after: list[str]) -> dict | None:
    """The history change for a table set: `table_id` between singles, else `table_ids`."""
    if before is not None and set(before) == set(after):
        return None
    if len(after) == 1 and (before is None or len(before) == 1):
        return {"field": "table_id", "from": before[0] if before else None, "to": after[0]}
    return {"field": "table_ids", "from": list(before) if before else None, "to": list(after)}


def created_changes(res: Reservation) -> list[dict]:
    return [table_change(None, res.table_ids),
            {"field": "starts_at_local", "from": None, "to": timeutil.format_local(res.local)},
            {"field": "party_size", "from": None, "to": res.party_size}]


# ----------------------------------------------------------------------------- series

@dataclass
class Occurrence:
    index: int
    reservation_id: str
    scheduled: date          # the occurrence's scheduled local date, fixed at adoption
    exception: bool = False

    def to_json(self) -> dict:
        return {"index": self.index, "reservation_id": self.reservation_id,
                "scheduled": self.scheduled.isoformat(), "exception": self.exception}


@dataclass
class Series:
    id: str
    user_id: str
    restaurant_id: str
    interval_weeks: int
    revision: int
    occurrences: list[Occurrence]

    def occurrence_of(self, reservation_id: str) -> Occurrence | None:
        return next((o for o in self.occurrences if o.reservation_id == reservation_id), None)

    def to_json(self) -> dict:
        return {"id": self.id, "user_id": self.user_id, "restaurant_id": self.restaurant_id,
                "interval_weeks": self.interval_weeks, "revision": self.revision,
                "occurrences": [o.to_json() for o in self.occurrences]}


# ----------------------------------------------------------------------------- seating plans

@dataclass(frozen=True)
class Closure:
    """An applied table closure: the table is unusable during [start, end)."""
    restaurant_id: str
    table_id: str
    start: datetime
    end: datetime
    plan_id: str

    def blocks(self, table_ids, start: datetime, end: datetime) -> bool:
        return self.table_id in table_ids and self.start < end and start < self.end

    def to_json(self) -> dict:
        return {"restaurant_id": self.restaurant_id, "table_id": self.table_id,
                "start": timeutil.render(self.start), "end": timeutil.render(self.end),
                "plan_id": self.plan_id}


@dataclass
class Plan:
    """A previewed seating plan for a proposed closure (stage 4)."""
    id: str
    restaurant_id: str
    closure: dict                 # {table_id, from, to} as supplied
    start: datetime
    end: datetime
    restaurant_revision: int      # the restaurant revision it was planned against
    assignments: list[dict]       # [{reference, table_ids, changed}] in reference order
    moved_count: int
    unused_seats: int
    applied: bool = False

    def preview(self) -> dict:
        return {"plan_id": self.id, "restaurant_revision": self.restaurant_revision,
                "closure": dict(self.closure),
                "assignments": [dict(a, table_ids=list(a["table_ids"])) for a in self.assignments],
                "moved_count": self.moved_count, "unused_seats": self.unused_seats}

    def to_json(self) -> dict:
        return {**self.preview(), "restaurant_id": self.restaurant_id,
                "start": timeutil.render(self.start), "end": timeutil.render(self.end),
                "applied": self.applied}


@dataclass(frozen=True)
class Receipt:
    """A completed idempotent request: the body it was made with and the response it got."""
    fingerprint: str
    status: int
    response: dict


ReceiptKey = tuple[str, str, str, str]   # (user id, method, path, Idempotency-Key)


# ----------------------------------------------------------------------------- state

@dataclass
class State:
    users: dict[str, User] = field(default_factory=dict)
    user_by_email: dict[str, str] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)          # token digest -> user id
    restaurants: dict[str, Restaurant] = field(default_factory=dict)
    policies: dict[str, list[Policy]] = field(default_factory=dict)   # published, in order
    restaurant_revision: dict[str, int] = field(default_factory=dict)
    reservations: dict[str, Reservation] = field(default_factory=dict)
    by_reference: dict[str, str] = field(default_factory=dict)    # reference -> reservation id
    series: dict[str, Series] = field(default_factory=dict)
    plans: dict[str, Plan] = field(default_factory=dict)
    closures: list[Closure] = field(default_factory=list)
    receipts: dict[ReceiptKey, Receipt] = field(default_factory=dict)
    next_seq: int = 1

    # -- restaurants and policies

    def add_restaurant(self, restaurant: Restaurant) -> None:
        if restaurant.id in self.restaurants:
            raise ValueError(f"duplicate restaurant {restaurant.id!r}")
        self.restaurants[restaurant.id] = restaurant
        self.policies[restaurant.id] = []
        self.restaurant_revision[restaurant.id] = 0

    def policy_for(self, restaurant: Restaurant, day: date) -> Policy:
        return select(restaurant.policy_zero(), self.policies[restaurant.id], day)

    def bump_restaurant(self, restaurant_id: str) -> None:
        self.restaurant_revision[restaurant_id] += 1

    def closures_at(self, restaurant_id: str) -> list[Closure]:
        return [c for c in self.closures if c.restaurant_id == restaurant_id]

    # -- users and tokens

    def add_user(self, user: User) -> None:
        key = email_key(user.email)
        if user.id in self.users or key in self.user_by_email:
            raise ValueError(f"duplicate user {user.id!r} / {user.email!r}")
        self.users[user.id] = user
        self.user_by_email[key] = user.id

    def user_for_email(self, email: str) -> User | None:
        user_id = self.user_by_email.get(email_key(email))
        return self.users.get(user_id) if user_id else None

    def issue_token(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.tokens[token_digest(token)] = user_id
        return token

    def user_for_token(self, token: str) -> User | None:
        user_id = self.tokens.get(token_digest(token))
        return self.users.get(user_id) if user_id else None

    def new_user_id(self) -> str:
        return self._fresh_id("u_", self.users)

    # -- reservations and series

    def add_reservation(self, res: Reservation) -> None:
        if res.id in self.reservations or res.reference in self.by_reference:
            raise ValueError(f"duplicate reservation {res.id!r} / {res.reference!r}")
        self.reservations[res.id] = res
        self.by_reference[res.reference] = res.id
        self.next_seq = max(self.next_seq, res.seq + 1)

    def reservation_by_reference(self, reference: str) -> Reservation | None:
        res_id = self.by_reference.get(reference)
        return self.reservations.get(res_id) if res_id else None

    def at_restaurant(self, restaurant_id: str) -> list[Reservation]:
        return [r for r in self.reservations.values() if r.restaurant_id == restaurant_id]

    def new_reservation_id(self) -> str:
        return self._fresh_id("res_", self.reservations)

    def new_series_id(self) -> str:
        return self._fresh_id("ser_", self.series)

    def new_plan_id(self) -> str:
        return self._fresh_id("plan_", self.plans)

    def new_reference(self) -> str:
        while True:
            reference = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(8))
            if reference not in self.by_reference:
                return reference

    def take_seq(self) -> int:
        seq = self.next_seq
        self.next_seq += 1
        return seq

    def _fresh_id(self, prefix: str, taken: dict) -> str:
        n = len(taken) + 1
        while f"{prefix}{n}" in taken:
            n += 1
        return f"{prefix}{n}"


# ----------------------------------------------------------------------------- loading
#
# Fixtures (reset) and exported state (import) are both untrusted JSON. The loaders below
# raise ValueError on anything malformed; the API turns that into 422 validation_failed.

def _req(obj: dict, key: str, kind):
    if not isinstance(obj, dict):
        raise ValueError("expected an object")
    if key not in obj:
        raise ValueError(f"missing {key!r}")
    value = obj[key]
    ok = is_int(value) if kind is int else isinstance(value, kind)
    if not ok:
        raise ValueError(f"{key!r} has the wrong type")
    return value


def _id(obj: dict, key: str) -> str:
    value = _req(obj, key, str)
    if not value or len(value) > MAX_ID:
        raise ValueError(f"{key!r} must be 1 to {MAX_ID} characters")
    return value


def _list(obj: dict, key: str) -> list:
    return _req(obj, key, list) if key in obj else []


def restaurant_from_json(obj: dict) -> Restaurant:
    rid = _id(obj, "id")
    tz_name = _req(obj, "timezone", str)
    timeutil.zone(tz_name)
    slot = _req(obj, "slot_minutes", int)
    duration = _req(obj, "reservation_duration_minutes", int)
    cutoff = obj.get("cancellation_cutoff_minutes", 0)
    if not is_int(cutoff) or cutoff < 0:
        raise ValueError("cancellation_cutoff_minutes must be a non-negative integer")
    if not (1 <= slot <= MAX_MINUTES and 1 <= duration <= MAX_MINUTES):
        raise ValueError("slot_minutes and reservation_duration_minutes are out of range")
    hours = parse_hours(obj.get("opening_hours", []), unique_weekdays=False)
    tables, seen = [], set()
    for entry in _list(obj, "tables"):
        tid = _id(entry, "id")
        capacity = _req(entry, "capacity", int)
        label = entry.get("label", tid)
        if tid in seen or capacity < 0 or not isinstance(label, str):
            raise ValueError(f"invalid table {tid!r}")
        seen.add(tid)
        tables.append(Table(tid, label, capacity))
    name = obj.get("name", rid)
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    pairs = []
    for entry in _list(obj, "combinable"):
        if (not isinstance(entry, list) or len(entry) != 2 or entry[0] == entry[1]
                or any(t not in seen for t in entry)):
            raise ValueError("combinable entries are pairs of two of the restaurant's tables")
        if set(entry) not in [set(p) for p in pairs]:
            pairs.append((entry[0], entry[1]))
    managers = _list(obj, "manager_user_ids")
    if not all(isinstance(m, str) for m in managers):
        raise ValueError("manager_user_ids must be strings")
    return Restaurant(rid, name, tz_name, slot, duration, cutoff, hours, tuple(tables),
                      tuple(pairs), tuple(managers))


def _local_time(starts_at_local: str) -> datetime:
    local = datetime.strptime(starts_at_local, "%Y-%m-%dT%H:%M")
    if (timeutil.format_local(local) != starts_at_local
            or not timeutil.MIN_YEAR <= local.year <= timeutil.MAX_YEAR):
        raise ValueError(f"starts_at_local {starts_at_local!r} is not a supported local time")
    return local


def _table_set(restaurant: Restaurant, table_ids: list) -> list[str]:
    """A stored table set: one table, or two in their declared combination order."""
    if (not 1 <= len(table_ids) <= 2 or len(set(table_ids)) != len(table_ids)
            or any(not isinstance(t, str) or restaurant.table(t) is None for t in table_ids)):
        raise ValueError("a reservation holds one table or two distinct tables")
    if len(table_ids) == 2:
        return list(restaurant.pair(table_ids) or table_ids)
    return list(table_ids)


def _reference(item: dict) -> str:
    reference = _req(item, "reference", str)
    if not is_reference(reference):
        raise ValueError("reference must be 6 to 12 characters of A-Z0-9")
    return reference


def _with_original_history(res: Reservation, restaurant: Restaurant, *, seeded: bool) -> Reservation:
    """Stage-3 fields for a booking that predates them: seeded, or imported from stage 1-2.

    Revision 1 under policy 0 with a `created` entry at its creation time. A cancelled one
    also carries its `cancelled` entry: still at revision 1 when seeded (decision A-43), at
    revision 2 when it was cancelled through the API before an upgrade (decision A-31).
    """
    res.terms = restaurant.policy_zero().terms()
    res.revision = 1
    res.history = []
    at = timeutil.render(timeutil.parse_instant(res.created_at), restaurant.tz)
    res.record("created", created_changes(res), at)
    if res.status == CANCELLED:
        if not seeded:
            res.revision = 2
        res.record("cancelled", [], at)
    return res


def seeded_reservation(obj: dict, state: State, reset_at: datetime) -> Reservation:
    """A fixture reservation: a POST /reservations body plus id, reference and user_id."""
    restaurant = state.restaurants.get(_req(obj, "restaurant_id", str))
    if restaurant is None:
        raise ValueError("seeded reservation names an unknown restaurant")
    table_ids = (_req(obj, "table_ids", list) if "table_ids" in obj
                 else [_req(obj, "table_id", str)])
    table_ids = _table_set(restaurant, table_ids)
    status = obj.get("status", CONFIRMED)
    if status not in (CONFIRMED, CANCELLED):
        raise ValueError("seeded status must be confirmed or cancelled")
    party_size = _req(obj, "party_size", int)
    if party_size < 1:
        raise ValueError("party_size must be at least 1")
    local = _local_time(_req(obj, "starts_at_local", str))
    start = timeutil.to_instant(restaurant.tz, local)
    if obj.get("created_at") is None:
        created_at = timeutil.render(reset_at)
    else:
        instant = timeutil.parse_instant(obj["created_at"])
        created_at = timeutil.render(instant, instant.tzinfo)
    res = Reservation(
        id=_id(obj, "id"), reference=_reference(obj), user_id=_id(obj, "user_id"),
        restaurant_id=restaurant.id, table_ids=table_ids, party_size=party_size,
        status=status, local=local, start=start,
        end=start + timeutil.minutes(restaurant.duration_minutes), created_at=created_at,
        seq=state.take_seq())
    return _with_original_history(res, restaurant, seeded=True)


def state_from_fixture(fixture: dict, hasher) -> State:
    """The state a reset installs. `hasher` turns a plaintext password into its stored hash."""
    state = State()
    for obj in _list(fixture, "restaurants"):
        state.add_restaurant(restaurant_from_json(obj))
    for obj in _list(fixture, "users"):
        password = _req(obj, "password", str)
        state.add_user(User(_id(obj, "id"), _req(obj, "email", str),
                            _req(obj, "display_name", str), hasher(password)))
    reset_at = timeutil.now()
    for obj in _list(fixture, "reservations"):
        state.add_reservation(seeded_reservation(obj, state, reset_at))
    return state


# ----------------------------------------------------------------------------- export/import

STATE_SCHEMA = "tablekeeper-state"
STATE_STAGE = 4
READABLE_STAGES = (1, 2, 3, 4)   # earlier stages' exports are upgraded on import (A-31)


def state_to_json(state: State) -> dict:
    return {
        "schema": STATE_SCHEMA,
        "stage": STATE_STAGE,
        "restaurants": [
            {**r.to_state(), "revision": state.restaurant_revision[r.id],
             "policies": [p.to_json() for p in state.policies[r.id]]}
            for r in state.restaurants.values()
        ],
        "users": [u.to_json() for u in state.users.values()],
        "tokens": [{"token_sha256": digest, "user_id": uid} for digest, uid in state.tokens.items()],
        "reservations": [r.to_json() for r in state.reservations.values()],
        "series": [s.to_json() for s in state.series.values()],
        "plans": [p.to_json() for p in state.plans.values()],
        "closures": [c.to_json() for c in state.closures],
        "receipts": [
            {"user_id": k[0], "method": k[1], "path": k[2], "key": k[3],
             "fingerprint": rec.fingerprint, "status": rec.status, "response": rec.response}
            for k, rec in state.receipts.items()
        ],
        "next_seq": state.next_seq,
    }


def state_from_json(obj: dict, valid_hash) -> State:
    """Rebuild exported state exactly; raises ValueError (or KeyError/TypeError) if invalid."""
    stage = _req(obj, "stage", int)
    if _req(obj, "schema", str) != STATE_SCHEMA or stage not in READABLE_STAGES:
        raise ValueError("state was not exported by this service")
    state = State()
    for item in _req(obj, "restaurants", list):
        restaurant = restaurant_from_json(item)
        state.add_restaurant(restaurant)
        if stage >= 3:
            state.restaurant_revision[restaurant.id] = _req(item, "revision", int)
            for policy in _req(item, "policies", list):
                state.policies[restaurant.id].append(policy_from_state(policy, restaurant.table_ids))
    for item in _req(obj, "users", list):
        password_hash = _req(item, "password_hash", str)
        if not valid_hash(password_hash):
            raise ValueError("invalid password hash")
        state.add_user(User(_id(item, "id"), _req(item, "email", str),
                            _req(item, "display_name", str), password_hash))
    for item in _req(obj, "tokens", list):
        user_id = _req(item, "user_id", str)
        if user_id not in state.users:
            raise ValueError("token for an unknown user")
        state.tokens[_req(item, "token_sha256", str)] = user_id
    for item in _req(obj, "reservations", list):
        state.add_reservation(_reservation_from_json(item, state, stage))
    for item in (_req(obj, "series", list) if stage >= 3 else []):
        series = _series_from_json(item, state)
        state.series[series.id] = series
    for item in (_req(obj, "plans", list) if stage >= 4 else []):
        plan = _plan_from_json(item, state)
        state.plans[plan.id] = plan
    for item in (_req(obj, "closures", list) if stage >= 4 else []):
        closure = Closure(_id(item, "restaurant_id"), _id(item, "table_id"),
                          timeutil.parse_instant(_req(item, "start", str)).astimezone(timeutil.UTC),
                          timeutil.parse_instant(_req(item, "end", str)).astimezone(timeutil.UTC),
                          _id(item, "plan_id"))
        if closure.restaurant_id not in state.restaurants or closure.end <= closure.start:
            raise ValueError("invalid closure")
        state.closures.append(closure)
    for item in _req(obj, "receipts", list):
        key = (_req(item, "user_id", str), _req(item, "method", str), _req(item, "path", str),
               _req(item, "key", str))
        state.receipts[key] = Receipt(_req(item, "fingerprint", str), _req(item, "status", int),
                                      _req(item, "response", dict))
    state.next_seq = max(state.next_seq, _req(obj, "next_seq", int))
    return state


def _reservation_from_json(item: dict, state: State, stage: int) -> Reservation:
    restaurant = state.restaurants.get(_req(item, "restaurant_id", str))
    if restaurant is None:
        raise ValueError("reservation at an unknown restaurant")
    status = _req(item, "status", str)
    if status not in (CONFIRMED, CANCELLED):
        raise ValueError("unknown reservation status")
    party_size = _req(item, "party_size", int)
    start = timeutil.parse_instant(_req(item, "starts_at", str))
    end = timeutil.parse_instant(_req(item, "ends_at", str))
    created_at = _req(item, "created_at", str)
    timeutil.parse_instant(created_at)
    if party_size < 1 or end <= start:
        raise ValueError("invalid reservation")
    res = Reservation(
        id=_id(item, "id"), reference=_reference(item), user_id=_id(item, "user_id"),
        restaurant_id=restaurant.id, table_ids=_table_set(restaurant, _req(item, "table_ids", list)),
        party_size=party_size, status=status, local=_local_time(_req(item, "starts_at_local", str)),
        start=start.astimezone(timeutil.UTC), end=end.astimezone(timeutil.UTC),
        created_at=created_at, seq=_req(item, "seq", int))
    if stage < 3:
        return _with_original_history(res, restaurant, seeded=False)
    res.revision = _req(item, "revision", int)
    res.terms = _req(item, "terms", dict)
    res.history = _req(item, "history", list)
    if not isinstance(res.terms.get("cancellation_cutoff_minutes"), int) or not res.history:
        raise ValueError("invalid accepted terms or history")
    series_id = item.get("series_id")
    if series_id is not None and not isinstance(series_id, str):
        raise ValueError("invalid series id")
    res.series_id = series_id
    return res


def _series_from_json(item: dict, state: State) -> Series:
    occurrences = []
    for occ in _req(item, "occurrences", list):
        res_id = _req(occ, "reservation_id", str)
        if res_id not in state.reservations:
            raise ValueError("series occurrence names an unknown reservation")
        occurrences.append(Occurrence(_req(occ, "index", int), res_id,
                                      date.fromisoformat(_req(occ, "scheduled", str)),
                                      _req(occ, "exception", bool)))
    series = Series(_id(item, "id"), _id(item, "user_id"), _id(item, "restaurant_id"),
                    _req(item, "interval_weeks", int), _req(item, "revision", int), occurrences)
    if series.restaurant_id not in state.restaurants or not occurrences:
        raise ValueError("invalid series")
    return series


def _plan_from_json(item: dict, state: State) -> Plan:
    restaurant_id = _id(item, "restaurant_id")
    if restaurant_id not in state.restaurants:
        raise ValueError("plan at an unknown restaurant")
    assignments = []
    for a in _req(item, "assignments", list):
        table_ids = _req(a, "table_ids", list)
        if not all(isinstance(t, str) for t in table_ids):
            raise ValueError("invalid assignment")
        assignments.append({"reference": _reference(a), "table_ids": table_ids,
                            "changed": _req(a, "changed", bool)})
    closure = _req(item, "closure", dict)
    return Plan(_id(item, "plan_id"), restaurant_id,
                {"table_id": _req(closure, "table_id", str), "from": _req(closure, "from", str),
                 "to": _req(closure, "to", str)},
                timeutil.parse_instant(_req(item, "start", str)).astimezone(timeutil.UTC),
                timeutil.parse_instant(_req(item, "end", str)).astimezone(timeutil.UTC),
                _req(item, "restaurant_revision", int), assignments,
                _req(item, "moved_count", int), _req(item, "unused_seats", int),
                _req(item, "applied", bool))
