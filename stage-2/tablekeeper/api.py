"""Endpoint handlers: authentication, idempotency and the glue between HTTP and the rules.

Each handler takes a `Request` and returns `(status, body)`; errors are raised as ApiError.
Everything that reads or writes state runs inside `store.lock` (see store.py).
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Callable

from . import booking, timeutil
from .errors import ApiError, invalid, not_found, unauthenticated
from .jsonio import depth, fingerprint, parse_object
from .model import Receipt, State, User, state_from_fixture, state_from_json, state_to_json
from .passwords import DUMMY_HASH, hash_password, is_valid_hash, verify_password
from .store import Store
from .validate import check_id, query_positive_int, require_present, string_field

MAX_IDEMPOTENCY_KEY = 255
# Exported state nests a handful of levels. Imported state is deep-copied by export and
# re-serialised by replays, so anything far deeper is refused rather than recursed into.
MAX_STATE_DEPTH = 64
_BEARER = re.compile(r"Bearer +(\S+) *", re.IGNORECASE)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")


@dataclass
class Request:
    method: str
    path: str                                   # route path, without the query string
    params: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)   # lower-case names
    body: bytes = b""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


Response = tuple[int, "dict | None"]


class Api:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ------------------------------------------------------------------ helpers

    def _caller(self, state: State, req: Request) -> User:
        match = _BEARER.fullmatch(req.header("authorization") or "")
        user = state.user_for_token(match.group(1)) if match else None
        if user is None:
            raise unauthenticated()
        return user

    def _idempotent(self, state: State, user: User, req: Request, body: dict,
                    action: Callable[[], dict]) -> Response:
        """Run `action` at most once per (user, method, path, key) and replay its response (§7).

        Called with the lock held, after authentication and JSON parsing and before any
        field validation (decision A-01). Only a successful outcome is stored, so a key
        whose first use failed stays unused.
        """
        key = req.header("idempotency-key")
        if not key:
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
        if len(key) > MAX_IDEMPOTENCY_KEY:
            raise invalid(f"Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY} characters")
        receipt_key = (user.id, req.method, req.path, key)
        request_print = fingerprint(body)
        receipt = state.receipts.get(receipt_key)
        if receipt is not None:
            if receipt.fingerprint != request_print:
                raise ApiError(409, "idempotency_key_reuse",
                               "this Idempotency-Key was used with a different request")
            return 200, receipt.response
        response = action()
        state.receipts[receipt_key] = Receipt(request_print, 201, response)
        return 201, response

    # ------------------------------------------------------------------ runtime and test control

    def health(self, req: Request) -> Response:
        return 200, {"status": "ok"}

    def reset(self, req: Request) -> Response:
        fixture = parse_object(req.body)
        try:
            state = state_from_fixture(fixture, hash_password)
        except (ValueError, TypeError, KeyError, ApiError) as exc:
            raise invalid(f"invalid fixture: {exc}") from None
        with self.store.lock:
            self.store.state = state
        return 204, None

    def export(self, req: Request) -> Response:
        with self.store.lock:
            snapshot = copy.deepcopy(state_to_json(self.store.state))
        return 200, {"track": "tablekeeper", "format_version": 1, "state": snapshot}

    def import_(self, req: Request) -> Response:
        envelope = parse_object(req.body)
        version = envelope.get("format_version")
        if (envelope.get("track") != "tablekeeper" or type(version) is not int or version != 1
                or not isinstance(envelope.get("state"), dict)):
            raise invalid("expected {track: tablekeeper, format_version: 1, state: {...}}")
        if depth(envelope["state"]) > MAX_STATE_DEPTH:
            raise invalid("state is nested too deeply to have been exported by this service")
        try:
            state = state_from_json(envelope["state"], is_valid_hash)
        except Exception as exc:  # any defect in an untrusted state is a validation failure
            raise invalid(f"invalid state: {exc}") from None
        with self.store.lock:
            self.store.state = state
        return 204, None

    # ------------------------------------------------------------------ authentication (§6)

    def signup(self, req: Request) -> Response:
        body = parse_object(req.body)
        email = string_field(body, "email")
        password = string_field(body, "password")
        display_name = string_field(body, "display_name")
        require_present(body, ("email", "password", "display_name"))
        if not _EMAIL.fullmatch(email):
            raise invalid("email must look like local@domain")
        if len(password) < 8:
            raise invalid("password must be at least 8 characters")
        if not display_name.strip():
            raise invalid("display_name must not be empty")
        with self.store.lock:
            if self.store.state.user_for_email(email) is not None:
                raise _email_taken()
        password_hash = hash_password(password)          # slow: outside the lock
        with self.store.lock:
            state = self.store.state
            if state.user_for_email(email) is not None:
                raise _email_taken()
            user = User(state.new_user_id(), email, display_name, password_hash)
            state.add_user(user)
            token = state.issue_token(user.id)
        return 201, {"user_id": user.id, "display_name": user.display_name, "token": token}

    def login(self, req: Request) -> Response:
        body = parse_object(req.body)
        email = string_field(body, "email")
        password = string_field(body, "password")
        require_present(body, ("email", "password"))
        with self.store.lock:
            state = self.store.state
            user = state.user_for_email(email)
        ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
        with self.store.lock:
            # A reset or import between the two steps invalidates the account looked up.
            if not ok or user is None or self.store.state is not state:
                raise unauthenticated("wrong email or password")
            token = state.issue_token(user.id)
        return 200, {"user_id": user.id, "display_name": user.display_name, "token": token}

    # ------------------------------------------------------------------ public browsing (§8)

    def restaurant_summaries(self) -> list[dict]:
        """The restaurant list the page shell embeds (same content as GET /restaurants)."""
        with self.store.lock:
            return [r.summary() for r in self.store.state.restaurants.values()]

    def restaurants(self, req: Request) -> Response:
        with self.store.lock:
            items = [r.summary() for r in self.store.state.restaurants.values()]
        return 200, {"restaurants": items}

    def restaurant(self, req: Request) -> Response:
        with self.store.lock:
            restaurant = self.store.state.restaurants.get(req.params["id"])
            if restaurant is None:
                raise not_found("no such restaurant")
            return 200, restaurant.to_json()

    def availability(self, req: Request) -> Response:
        params = {name: req.query.get(name) for name in ("restaurant_id", "date", "party_size")}
        missing = [name for name, value in params.items() if not value]
        if missing:
            raise invalid(f"missing query parameter(s): {', '.join(missing)}")
        restaurant_id = check_id(params["restaurant_id"], "restaurant_id")
        day = timeutil.parse_date(params["date"])
        party_size = query_positive_int(params["party_size"], "party_size")
        with self.store.lock:
            state = self.store.state
            restaurant = state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            return 200, booking.availability(state, restaurant, day, party_size)

    # ------------------------------------------------------------------ reservations (§8, §11)

    def create_reservation(self, req: Request) -> Response:
        with self.store.lock:
            state = self.store.state
            user = self._caller(state, req)
            body = parse_object(req.body)
            return self._idempotent(state, user, req, body,
                                    lambda: booking.create(state, user, body))

    def move_reservations(self, req: Request) -> Response:
        with self.store.lock:
            state = self.store.state
            user = self._caller(state, req)
            body = parse_object(req.body)
            return self._idempotent(state, user, req, body,
                                    lambda: booking.move(state, user, body, timeutil.now()))

    def list_reservations(self, req: Request) -> Response:
        with self.store.lock:
            state = self.store.state
            return 200, booking.list_for(state, self._caller(state, req))

    def get_reservation(self, req: Request) -> Response:
        with self.store.lock:
            state = self.store.state
            res = booking.owned(state, self._caller(state, req), req.params["reference"])
            return 200, res.to_response(state.restaurants[res.restaurant_id].tz)

    def cancel_reservation(self, req: Request) -> Response:
        with self.store.lock:
            state = self.store.state
            user = self._caller(state, req)
            return 200, booking.cancel(state, user, req.params["reference"], timeutil.now())

    def amend_reservation(self, req: Request) -> Response:
        with self.store.lock:
            state = self.store.state
            user = self._caller(state, req)
            body = parse_object(req.body)
            return 200, booking.amend(state, user, req.params["reference"], body,
                                      timeutil.now())


def _email_taken() -> ApiError:
    return ApiError(409, "email_taken", "an account with this email already exists")

