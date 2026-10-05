"""Upgrade from stage 1: a stage-1 export imported into the stage-2 service (S2-026, A-23).

Needs TK_STAGE1_BASE_URL: the team's accepted stage-1 service (candidate.py --with-stage1 <commit>).
"""
import os

import pytest

import tk
from tk import THU, FRI, body, expect

S1_URL = os.environ.get("TK_STAGE1_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not S1_URL, reason="TK_STAGE1_BASE_URL not set (stage-1 reference service)")

SEED = tk.seed("res_seed_bob", "SEEDB0B1", "u_bob", "r_anker", "t_2", f"{FRI}T19:00", 3)


@pytest.fixture
def s1():
    a = tk.Api(S1_URL)
    yield a
    a.close()


@pytest.mark.ledger("S2-026", "A-23", "S1-088", "S1-039", "S1-104")
def test_stage1_export_imports_into_stage2(api, s1):
    s1.reset(tk.fixture(reservations=[SEED]))
    ada = s1.token(tk.ADA["email"], tk.ADA["password"])
    bob = s1.token(tk.BOB["email"], tk.BOB["password"])
    su = s1.signup("dee@example.com", "dee secret pw", "Dee")
    expect(su, 201)
    dee = su.json["token"]
    k1, b1 = tk.new_key(), body("r_anker", "t_1", f"{THU}T19:00", 2)
    o1 = expect(s1.create(ada, b1, key=k1), 201)
    k2, b2 = tk.new_key(), body("r_anker", "t_2", f"{THU}T19:00", 2)
    o2 = expect(s1.create(ada, b2, key=k2), 201)
    expect(s1.patch(ada, o2["reference"], {"party_size": 4}), 200)
    k3, b3 = tk.new_key(), body("r_big", "b_1", f"{THU}T12:00", 2)
    o3 = expect(s1.create(dee, b3, key=k3), 201)
    expect(s1.cancel(dee, o3["reference"]), 200)
    km, bm = tk.new_key(), {"moves": [{"reference": o1["reference"], "table_id": "t_3"}, {"reference": o2["reference"]}]}
    om = expect(s1.moves(ada, bm, key=km), 201)
    kf = tk.new_key()
    expect(s1.create(ada, body("r_anker", "t_1", f"{THU}T19:15"), key=kf), 422, "not_on_slot_grid")
    lists = {n: sorted(s1.list(t), key=lambda r: r["reference"]) for n, t in (("ada", ada), ("bob", bob), ("dee", dee))}
    exported = s1.export()

    api.reset(tk.fixture(users=(tk.CY,), restaurants=(tk.HARBOR,)))
    cy = api.token(tk.CY["email"], tk.CY["password"])
    expect(api.import_(exported), 204)

    # every account, token and reservation survives; stage-2 shapes add table_ids
    for name, tok in (("ada", ada), ("bob", bob), ("dee", dee)):
        got = sorted(api.list(tok), key=lambda r: r["reference"])
        assert [r["reference"] for r in got] == [r["reference"] for r in lists[name]]
        for g, o in zip(got, lists[name]):
            tk.assert_res(g)
            for k in ("reservation_id", "status", "starts_at", "ends_at", "created_at", "party_size",
                      "table_id", "restaurant_id", "starts_at_local"):
                assert g[k] == o[k], f"{name} {o['reference']} {k}: {o[k]!r} -> {g[k]!r}"
            assert g["table_ids"] == [o["table_id"]]
    expect(api.login("dee@example.com", "dee secret pw"), 200)
    expect(api.login(tk.BOB["email"], tk.BOB["password"]), 200)
    expect(api.call("GET", "/reservations", token=cy), 401, "unauthenticated")
    # receipts replay with the original stage-1 bodies
    for key, b, o, tok in ((k1, b1, o1, ada), (k2, b2, o2, ada), (k3, b3, o3, dee)):
        r = api.create(tok, b, key=key)
        expect(r, 200)
        assert r.json == o, f"replay after upgrade differs from the original response: {r.json} vs {o}"
    rm = api.moves(ada, bm, key=km)
    expect(rm, 200)
    assert rm.json == om
    expect(api.create(ada, b2, key=k1), 409, "idempotency_key_reuse")
    expect(api.create(ada, body("r_anker", "t_1", f"{FRI}T18:00"), key=kf), 201)
    # occupancy carried over
    assert api.free_tables("r_anker", f"{THU}T19:00", 1) == ["t_1"]
    s = [x for x in api.slots("r_anker", THU, 1) if x["starts_at_local"] == f"{THU}T19:00"][0]
    assert s["available_options"] == [{"table_ids": ["t_1"], "capacity": 2}]
    # new references never collide with imported ones
    old = {r["reference"] for rs in lists.values() for r in rs}
    for hhmm in ("18:00", "21:00"):
        n = api.book(bob, "r_anker", "t_3", f"{tk.THU2}T{hhmm}")
        assert n["reference"] not in old


@pytest.mark.ledger("S2-026", "S2-042")
def test_stage1_export_then_stage2_round_trip(api, s1):
    s1.reset(tk.fixture())
    ada = s1.token(tk.ADA["email"], tk.ADA["password"])
    o1 = s1.book(ada, "r_anker", "t_1", f"{THU}T19:00")
    expect(api.import_(s1.export()), 204)
    pair_rest = api.call("GET", "/restaurants/r_anker").json
    assert pair_rest.get("combinable", []) == []
    e2 = api.export()
    api.reset(tk.fixture())
    expect(api.import_(e2), 204)
    assert api.get_ok(ada, o1["reference"])["table_ids"] == ["t_1"]
