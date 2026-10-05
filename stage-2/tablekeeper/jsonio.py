"""Strict JSON decoding, response encoding and the request fingerprint used by idempotency.

Request bodies may be nested as deeply as the decoder accepts, which is deeper than Python's
recursion limit, so nothing here walks a parsed body recursively.
"""
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


def depth(value) -> int:
    """How deeply arrays and objects nest in a parsed JSON value (a scalar is 0)."""
    deepest, pending = 0, [(value, 1)]
    while pending:
        node, level = pending.pop()
        if isinstance(node, dict):
            children = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        deepest = max(deepest, level)
        pending.extend((child, level + 1) for child in children)
    return deepest


class _Text(str):
    """Already-encoded output waiting on the fingerprint stack."""


def _scalar(value) -> str:
    # "Same body" is the same JSON value: 4 and 4.0 are one number.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return json.dumps(value, ensure_ascii=False)


def fingerprint(value) -> str:
    """Canonical text of a JSON value: keys sorted, no whitespace, integral floats as ints.

    Equal to json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    after that number normalisation, but built with an explicit stack, so any body the
    decoder accepted can be fingerprinted whatever its depth.
    """
    out: list[str] = []
    pending: list = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, _Text):
            out.append(node)
        elif isinstance(node, dict):
            out.append("{")
            pending.append(_Text("}"))
            entries = sorted(node.items())
            for i in range(len(entries) - 1, -1, -1):
                key, child = entries[i]
                pending.append(child)
                pending.append(_Text(json.dumps(key, ensure_ascii=False) + ":"))
                if i:
                    pending.append(_Text(","))
        elif isinstance(node, list):
            out.append("[")
            pending.append(_Text("]"))
            for i in range(len(node) - 1, -1, -1):
                pending.append(node[i])
                if i:
                    pending.append(_Text(","))
        else:
            out.append(_scalar(node))
    return "".join(out)


def dumps(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
