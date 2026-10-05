"""Strict JSON decoding, response encoding and the request fingerprint used by idempotency."""
from __future__ import annotations

import json

from .errors import malformed


def _reject_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def _parse_int(text: str):
    # An integer too long to convert is still a number; it is out of every range we accept.
    if len(text) > 1000:
        return float("-inf") if text.startswith("-") else float("inf")
    return int(text)


def parse_json(raw: bytes):
    """Decode a request body; anything that is not strict UTF-8 JSON is 400 malformed_request."""
    try:
        text = raw.decode("utf-8-sig")
        return json.loads(text, parse_constant=_reject_constant, parse_int=_parse_int)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise malformed() from None


def parse_object(raw: bytes) -> dict:
    """A body that must be a JSON object (§5: anything else is malformed)."""
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise malformed("request body must be a JSON object")
    return value


def _normalise(value):
    # "Same body" is the same JSON value: 4 and 4.0 are one number, key order is irrelevant.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    return value


def fingerprint(value) -> str:
    return json.dumps(_normalise(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def dumps(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
