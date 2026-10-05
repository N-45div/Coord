"""Deeply nested values in ignored or invalid fields (spec §3.4 unknown fields ignored, §5 never 5xx).

Tuned after Gate D1 (audit-105337a, not first-time detection): the garbage tests only nested at depth
5000 at the top level. Depths around 1000 are needed as well.
"""
import pytest

import tk
from tk import THU, body, expect, expect_no_5xx

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


def _deep_ok(api, tok, make_raw, call):
    """First depth (deep to shallow) at which the service accepts a body with a deep ignored field."""
    for depth in (1400, 1200, 1000, 900, 500):
        r = call(make_raw(depth))
        expect_no_5xx(r)
        if r.status in (200, 201):
            return depth, r
        assert r.status == 400 and r.json["error"]["code"] == "malformed_request", r
    raise AssertionError("no depth accepted")


@pytest.mark.ledger("S1-086", "S1-088", "S1-090", "S1-039", "S1-104")
def test_export_import_round_trip_with_deep_ignored_fields(w, api):
    """§10: import must accept an unchanged export of this service, and retries stay valid. Receipts
    for bodies with deeply nested ignored fields must survive the round trip (Coordinator audit
    pointer on e48a498's import depth bound)."""
    key_c, key_m = tk.new_key(), tk.new_key()
    other = f"{THU}T21:00"
    a = api.book(w.ada, "r_anker", "t_1", other)

    def create_raw(depth):
        return ('{"restaurant_id":"r_anker","table_id":"t_2","starts_at_local":"%sT19:00","party_size":2,"x":%s}'
                % (THU, nested(depth, "list")))

    def moves_raw(depth):
        return '{"moves":[{"reference":"%s","party_size":1}],"x":%s}' % (a["reference"], nested(depth, "object"))

    dc, rc = _deep_ok(api, w.ada, create_raw, lambda raw: api.call("POST", "/reservations", token=w.ada,
                                                                    key=key_c, raw=raw))
    dm, rm = _deep_ok(api, w.ada, moves_raw, lambda raw: api.call("POST", "/reservation-moves", token=w.ada,
                                                                   key=key_m, raw=raw))
    assert rc.status == 201 and rm.status == 201, (rc, rm)
    exported = api.export()
    targets = [tk.Api(tk.SECOND_BASE_URL)] if tk.SECOND_BASE_URL else []
    targets.append(api)
    try:
        for dest in targets:
            dest.reset(tk.fixture(users=(tk.BOB,), restaurants=(tk.HARBOR,)))
            r = dest.import_(exported)
            expect(r, 204)
            rr = dest.call("POST", "/reservations", token=w.ada, key=key_c, raw=create_raw(dc))
            expect(rr, 200)
            assert rr.json == rc.json, "create receipt with a deep ignored field lost or changed by export/import"
            mm = dest.call("POST", "/reservation-moves", token=w.ada, key=key_m, raw=moves_raw(dm))
            expect(mm, 200)
            assert mm.json == rm.json, "batch receipt with a deep ignored field lost or changed by export/import"
            expect(dest.call("POST", "/reservations", token=w.ada, key=key_c,
                             raw=create_raw(dc).replace('"party_size":2', '"party_size":1')), 409, "idempotency_key_reuse")
    finally:
        for dest in targets:
            if dest is not api:
                dest.close()
