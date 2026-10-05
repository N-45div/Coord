"""In-memory state: restaurants, users, tokens, reservations and idempotency receipts.

`State` is plain data. Reset and import build a complete new `State` and swap it in whole;
every read and write of the live one happens under `Store.lock` (store.py).
"""
from __future__ import annotations

import hashlib
import re
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from . import timeutil
from .validate import MAX_ID, is_int

CONFIRMED = "confirmed"
CANCELLED = "cancelled"
_REFERENCE_ALPHABET = string.ascii_uppercase + string.digits
# Slot and duration bound (~950 years) that keeps start + duration inside datetime's range.
# The cutoff has no bound: it is compared numerically, never added to a date.
MAX_MINUTES = 500_000_000
_REFERENCE = re.compile(r"[A-Z0-9]{6,12}")   # §8: 6 to 12 characters of A-Z0-9


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


@dataclass(frozen=True)
class Restaurant:
    id: str
    name: str
    timezone: str
    slot_minutes: int
    duration_minutes: int
    cutoff_minutes: int
    opening_hours: tuple[Hours, ...]
    tables: tuple[Table, ...]

    @property
    def tz(self) -> ZoneInfo:
        return timeutil.zone(self.timezone)

    def table(self, table_id: str) -> Table | None:
        for table in self.tables:
            if table.id == table_id:
                return table
        return None

    def hours_on(self, weekday: str) -> list[Hours]:
        return [h for h in self.opening_hours if h.weekday == weekday]

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
        }


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
    end: datetime        # UTC instant; start + duration in absolute time
    created_at: str      # rendered once, never regenerated
    seq: int             # creation order, the deterministic tie-break for listings

    @property
    def confirmed(self) -> bool:
        return self.status == CONFIRMED

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end

    def to_response(self, tz: ZoneInfo) -> dict:
        return {
            "reservation_id": self.id,
            "reference": self.reference,
            "restaurant_id": self.restaurant_id,
            "table_id": self.table_ids[0],
            "party_size": self.party_size,
            "status": self.status,
            "starts_at_local": timeutil.format_local(self.local),
            "starts_at": timeutil.render(self.start, tz),
            "ends_at": timeutil.render(self.end, tz),
            "created_at": self.created_at,
        }

    def to_json(self) -> dict:
        return {
            "id": self.id, "reference": self.reference, "user_id": self.user_id,
            "restaurant_id": self.restaurant_id, "table_ids": list(self.table_ids),
            "party_size": self.party_size, "status": self.status,
            "starts_at_local": timeutil.format_local(self.local),
            "starts_at": timeutil.render(self.start), "ends_at": timeutil.render(self.end),
            "created_at": self.created_at, "seq": self.seq,
        }


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
    reservations: dict[str, Reservation] = field(default_factory=dict)
    by_reference: dict[str, str] = field(default_factory=dict)    # reference -> reservation id
    receipts: dict[ReceiptKey, Receipt] = field(default_factory=dict)
    next_seq: int = 1

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

    # -- reservations

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

def _req(obj: dict, key: str, kind, default=None):
    if not isinstance(obj, dict):
        raise ValueError("expected an object")
    if key not in obj:
        if default is not None:
            return default
        raise ValueError(f"missing {key!r}")
    value = obj[key]
    if kind is int:
        ok = is_int(value)
    else:
        ok = isinstance(value, kind)
    if not ok:
        raise ValueError(f"{key!r} has the wrong type")
    return value


def _id(obj: dict, key: str) -> str:
    value = _req(obj, key, str)
    if not value or len(value) > MAX_ID:
        raise ValueError(f"{key!r} must be 1 to {MAX_ID} characters")
    return value


def _list(obj: dict, key: str, required: bool = False) -> list:
    if key not in obj and not required:
        return []
    return _req(obj, key, list)


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
    hours = []
    for entry in _list(obj, "opening_hours"):
        weekday = _req(entry, "weekday", str)
        if weekday not in timeutil.WEEKDAYS:
            raise ValueError(f"unknown weekday {weekday!r}")
        h = Hours(weekday, _req(entry, "opens", str), _req(entry, "closes", str))
        if h.closes_min <= h.opens_min:
            raise ValueError("closes must be later than opens")
        hours.append(h)
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
    return Restaurant(rid, name, tz_name, slot, duration, cutoff, tuple(hours), tuple(tables))


def _reservation_times(restaurant: Restaurant, starts_at_local: str):
    local = datetime.strptime(starts_at_local, "%Y-%m-%dT%H:%M")
    if (timeutil.format_local(local) != starts_at_local
            or not timeutil.MIN_YEAR <= local.year <= timeutil.MAX_YEAR):
        raise ValueError(f"starts_at_local {starts_at_local!r} is not a supported local time")
    start = timeutil.to_instant(restaurant.tz, local)
    return local, start, start + timeutil.minutes(restaurant.duration_minutes)


def seeded_reservation(obj: dict, state: State, reset_at: datetime) -> Reservation:
    """A fixture reservation: a POST /reservations body plus id, reference and user_id."""
    restaurant = state.restaurants.get(_req(obj, "restaurant_id", str))
    if restaurant is None:
        raise ValueError("seeded reservation names an unknown restaurant")
    table_id = _req(obj, "table_id", str)
    if restaurant.table(table_id) is None:
        raise ValueError("seeded reservation names an unknown table")
    party_size = _req(obj, "party_size", int)
    if party_size < 1:
        raise ValueError("party_size must be at least 1")
    local, start, end = _reservation_times(restaurant, _req(obj, "starts_at_local", str))
    if obj.get("created_at") is None:
        created_at = timeutil.render(reset_at)
    else:
        instant = timeutil.parse_instant(obj["created_at"])
        created_at = timeutil.render(instant, instant.tzinfo)
    return Reservation(
        id=_id(obj, "id"), reference=_reference(obj), user_id=_id(obj, "user_id"),
        restaurant_id=restaurant.id, table_ids=[table_id], party_size=party_size,
        status=CONFIRMED, local=local, start=start, end=end, created_at=created_at,
        seq=state.take_seq())


def state_from_fixture(fixture: dict, hasher) -> State:
    """The state a reset installs. `hasher` turns a plaintext password into its stored hash."""
    state = State()
    for obj in _list(fixture, "restaurants"):
        restaurant = restaurant_from_json(obj)
        if restaurant.id in state.restaurants:
            raise ValueError(f"duplicate restaurant {restaurant.id!r}")
        state.restaurants[restaurant.id] = restaurant
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
STATE_STAGE = 1


def state_to_json(state: State) -> dict:
    return {
        "schema": STATE_SCHEMA,
        "stage": STATE_STAGE,
        "restaurants": [r.to_json() for r in state.restaurants.values()],
        "users": [u.to_json() for u in state.users.values()],
        "tokens": [{"token_sha256": digest, "user_id": uid} for digest, uid in state.tokens.items()],
        "reservations": [r.to_json() for r in state.reservations.values()],
        "receipts": [
            {"user_id": k[0], "method": k[1], "path": k[2], "key": k[3],
             "fingerprint": rec.fingerprint, "status": rec.status, "response": rec.response}
            for k, rec in state.receipts.items()
        ],
        "next_seq": state.next_seq,
    }


def state_from_json(obj: dict, valid_hash) -> State:
    """Rebuild exported state exactly; raises ValueError (or KeyError/TypeError) if invalid."""
    if _req(obj, "schema", str) != STATE_SCHEMA or _req(obj, "stage", int) != STATE_STAGE:
        raise ValueError("state was not exported by this service")
    state = State()
    for item in _req(obj, "restaurants", list):
        restaurant = restaurant_from_json(item)
        if restaurant.id in state.restaurants:
            raise ValueError("duplicate restaurant")
        state.restaurants[restaurant.id] = restaurant
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
        state.add_reservation(_reservation_from_json(item, state))
    for item in _req(obj, "receipts", list):
        key = (_req(item, "user_id", str), _req(item, "method", str), _req(item, "path", str),
               _req(item, "key", str))
        state.receipts[key] = Receipt(_req(item, "fingerprint", str), _req(item, "status", int),
                                      _req(item, "response", dict))
    state.next_seq = max(state.next_seq, _req(obj, "next_seq", int))
    return state


def _reference(item: dict) -> str:
    reference = _req(item, "reference", str)
    if not is_reference(reference):
        raise ValueError("reference must be 6 to 12 characters of A-Z0-9")
    return reference


def _reservation_from_json(item: dict, state: State) -> Reservation:
    restaurant = state.restaurants.get(_req(item, "restaurant_id", str))
    if restaurant is None:
        raise ValueError("reservation at an unknown restaurant")
    table_ids = _req(item, "table_ids", list)
    if len(table_ids) != 1 or any(restaurant.table(t) is None for t in table_ids):
        raise ValueError("reservation names an unknown table")
    status = _req(item, "status", str)
    if status not in (CONFIRMED, CANCELLED):
        raise ValueError("unknown reservation status")
    party_size = _req(item, "party_size", int)
    local_text = _req(item, "starts_at_local", str)
    local = datetime.strptime(local_text, "%Y-%m-%dT%H:%M")
    start = timeutil.parse_instant(_req(item, "starts_at", str))
    end = timeutil.parse_instant(_req(item, "ends_at", str))
    created_at = _req(item, "created_at", str)
    timeutil.parse_instant(created_at)
    if party_size < 1 or end <= start:
        raise ValueError("invalid reservation")
    return Reservation(
        id=_id(item, "id"), reference=_reference(item), user_id=_id(item, "user_id"),
        restaurant_id=restaurant.id, table_ids=list(table_ids), party_size=party_size,
        status=status, local=local, start=start.astimezone(timeutil.UTC),
        end=end.astimezone(timeutil.UTC), created_at=created_at, seq=_req(item, "seq", int))
