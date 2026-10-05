"""Deeply nested values in ignored or invalid fields (spec §3.4 unknown fields ignored, §5 never 5xx).

Tuned after Gate D1 (audit-105337a, not first-time detection): the garbage tests only nested at depth
5000 at the top level. Depths around 1000 are needed as well.
"""
import pytest

import tk
from tk import THU, body, expect_no_5xx

DEPTHS = [500, 990, 999, 1000, 1001, 1100, 1200, 1300, 1600, 2500]


def nested(depth, kind):
    return ("[" * depth + "]" * depth) if kind == "list" else ('{"a":' * depth + "1" + "}" * depth)


@pytest.mark.ledger("S1-006", "S1-011")
@pytest.mark.parametrize("kind", ["list", "object"])
@pytest.mark.parametrize("depth", DEPTHS)
def test_deeply_nested_ignored_field_never_5xx(w, api, depth, kind):
    deep = nested(depth, kind)
    ref = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00")["reference"]
    b = body("r_anker", "t_2", f"{THU}T19:00")
    create = '{"restaurant_id":"r_anker","table_id":"t_2","starts_at_local":"%sT19:00","party_size":2,"x":%s}' % (THU, deep)
    moves = '{"moves":[{"reference":"%s","party_size":1}],"x":%s}' % (ref, deep)
    patch = '{"party_size":1,"x":%s}' % deep
    signup = '{"email":"deep%d@example.com","password":"long enough","display_name":"D","x":%s}' % (depth, deep)
    login = '{"email":"ada@example.com","password":"correct horse","x":%s}' % deep
    calls = [
        ("POST", "/reservations", w.ada, tk.new_key(), create, (201, 409)),
        ("POST", "/reservation-moves", w.ada, tk.new_key(), moves, (201,)),
        ("PATCH", f"/reservations/{ref}", w.ada, None, patch, (200,)),
        ("POST", "/auth/signup", None, None, signup, (201,)),
        ("POST", "/auth/login", None, None, login, (200,)),
    ]
    for method, path, tok, key, raw, ok in calls:
        r = api.call(method, path, token=tok, key=key, raw=raw)
        expect_no_5xx(r)
        assert r.status in ok or (r.status == 400 and r.json["error"]["code"] == "malformed_request"), \
            f"ignored deep field must be ignored (§3.4) or the body rejected as malformed (400): {r!r}"
    # an ordinary request still works afterwards
    assert api.create(w.ada, b).status in (201, 409)
