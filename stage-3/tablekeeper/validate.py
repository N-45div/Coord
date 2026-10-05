"""Field-level checks shared by the endpoints (§5).

Wrong JSON type is 400 malformed_request; a missing field or a value of the right type
that is out of range or badly formatted is 422 validation_failed. `party_size` is the
exception the spec names: every invalid value of it is 422.
"""
from __future__ import annotations

import re

from .errors import invalid, malformed

MAX_ID = 64
_DIGITS = re.compile(r"[0-9]+")

MISSING = object()


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def string_field(body: dict, field: str):
    """The value of a string field, MISSING when absent; 400 when present but not a string."""
    if field not in body:
        return MISSING
    value = body[field]
    if not isinstance(value, str):
        raise malformed(f"{field} must be a string")
    return value


def check_id(value: str, field: str) -> str:
    if not value or len(value) > MAX_ID:
        raise invalid(f"{field} must be 1 to {MAX_ID} characters")
    return value


def check_party_size(value) -> int:
    if not is_int(value) or value < 1:
        raise invalid("party_size must be an integer of at least 1")
    return value


def query_positive_int(text: str, field: str) -> int:
    if not _DIGITS.fullmatch(text):
        raise invalid(f"{field} must be written as plain decimal digits")
    digits = text.lstrip("0") or "0"
    # A longer number exceeds any capacity anyway; capping it keeps int parsing cheap.
    value = int(digits) if len(digits) <= 15 else 10**15
    if value < 1:
        raise invalid(f"{field} must be at least 1")
    return value


def require_present(body: dict, fields) -> None:
    missing = [f for f in fields if f not in body]
    if missing:
        raise invalid(f"missing required field(s): {', '.join(missing)}")
