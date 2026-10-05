"""Export / import (spec §10) and upgrade-safety of receipts, tokens and references."""
import json

import pytest

import tk
from tk import THU, FRI, body, expect, expect_no_5xx

OTHER_REST = {
    "id": "r_other", "name": "Elsewhere", "timezone": "Europe/Berlin", "slot_minutes": 30,
    "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 30,
    "opening_hours": [{"weekday": "thu", "opens": "12:00", "closes": "14:00"}],
    "tables": [{"id": "o_1", "label": "1", "capacity": 2}],
}
ZED = {"id": "u_zed", "email": "zed@example.com", "password": "zed password", "display_name": "Zed"}
SEEDED = tk.seed("res_seed_bob", "SEEDB0B1", "u_bob", "r_anker", "t_2", f"{FRI}T19:00", 3)


def _snapshot(api, toks):
    return {name: sorted(api.list(t), key=lambda r: r["reference"]) for name, t in toks.items()}


@pytest.fixture
def populated(api):
    """A source state with every kind of record §10 says must survive."""
    w = tk.World(api, tk.fixture(reservations=[SEEDED]))
    s = type("S", (), {})()
    s.w = w
    su = api.signup("dee@example.com", "dee secret pw", "Dee")
    expect(su, 201)
    s.dee_id, s.dee = su.json["user_id"], su.json["token"]
    s.ada, s.bob = w.ada, w.bob
    s.k1, s.b1 = tk.new_key(), body("r_anker", "t_1", f"{THU}T19:00", 2)
    s.o1 = expect(api.create(s.ada, s.b1, key=s.k1), 201)
    s.k2, s.b2 = tk.new_key(), body("r_anker", "t_2", f"{THU}T19:00", 2)
    s.o2 = expect(api.create(s.ada, s.b2, key=s.k2), 201)
    expect(api.patch(s.ada, s.o2["reference"], {"party_size": 4}), 200)
    s.k3, s.b3 = tk.new_key(), body("r_big", "b_1", f"{THU}T12:00", 2)
    s.o3 = expect(api.create(s.dee, s.b3, key=s.k3), 201)
    expect(api.cancel(s.dee, s.o3["reference"]), 200)
    s.km, s.bm = tk.new_key(), {"moves": [{"reference": s.o1["reference"], "table_id": "t_3"},
                                           {"reference": s.o2["reference"]}]}
    s.om = expect(api.moves(s.ada, s.bm, key=s.km), 201)
    s.kf = tk.new_key()
    expect(api.create(s.ada, body("r_anker", "t_1", f"{THU}T19:15", 2), key=s.kf), 422, "not_on_slot_grid")
    s.toks = {"ada": s.ada, "bob": s.bob, "dee": s.dee}
    s.snap = _snapshot(api, s.toks)
    s.restaurants = api.call("GET", "/restaurants").json
    s.anker = api.call("GET", "/restaurants/r_anker").json
    s.avail = api.avail("r_anker", THU, 2).json
    return s


@pytest.mark.ledger("S1-085")
def test_export_shape(w, api):
    e = api.export()
    assert e["track"] == "tablekeeper"
    assert e["format_version"] == 1 and type(e["format_version"]) is int
    assert isinstance(e["state"], dict)


@pytest.mark.ledger("S1-086", "S1-088", "S1-089", "S1-104", "S1-043", "S1-015")
def test_round_trip_into_replaced_destination_preserves_everything(api, populated):
    s = populated
    exported = api.export()
    # destination: a different world with its own user, token and booking
    dest = tk.World(api, tk.fixture(users=(ZED,), restaurants=(OTHER_REST,)))
    zed_tok = dest.tok("u_zed")
    api.book(zed_tok, "r_other", "o_1", f"{THU}T12:00")
    r = api.import_(exported)
    expect(r, 204)
    assert r.content == b""
    # accounts, hashed-password login, existing tokens
    assert _snapshot(api, s.toks) == s.snap
    assert api.token("dee@example.com", "dee secret pw")
    lg = api.login(tk.ADA["email"], tk.ADA["password"])
    expect(lg, 200)
    assert lg.json["user_id"] == "u_ada"
    # fixture configuration
    assert api.call("GET", "/restaurants").json == s.restaurants
    assert api.call("GET", "/restaurants/r_anker").json == s.anker
    assert api.avail("r_anker", THU, 2).json == s.avail
    # receipts: replays return the original bodies, reuse still conflicts
    for key, b, o, tok in ((s.k1, s.b1, s.o1, s.ada), (s.k2, s.b2, s.o2, s.ada), (s.k3, s.b3, s.o3, s.dee)):
        rr = api.create(tok, b, key=key)
        expect(rr, 200)
        assert rr.json == o
    rm = api.moves(s.ada, s.bm, key=s.km)
    expect(rm, 200)
    assert rm.json == s.om
    expect(api.create(s.ada, s.b2, key=s.k1), 409, "idempotency_key_reuse")
    # the failed key stays reusable
    expect(api.create(s.ada, body("r_anker", "t_1", f"{FRI}T18:00", 2), key=s.kf), 201)
    # previous destination data and credentials are gone
    expect(api.call("GET", "/reservations", token=zed_tok), 401, "unauthenticated")
    expect(api.login(ZED["email"], ZED["password"]), 401, "unauthenticated")
    expect(api.call("GET", "/restaurants/r_other"), 404, "not_found")


@pytest.mark.ledger("S1-092", "S1-057")
def test_new_references_after_import_do_not_collide(api, populated):
    s = populated
    exported = api.export()
    api.reset(tk.fixture())
    expect(api.import_(exported), 204)
    old = {r["reference"] for rs in s.snap.values() for r in rs}
    old_ids = {r["reservation_id"] for rs in s.snap.values() for r in rs}
    new = []
    for tid in ("t_1", "t_2", "t_3"):
        for hhmm in ("18:00", "19:30", "21:00"):
            new.append(api.book(s.bob, "r_anker", tid, f"{tk.THU2}T{hhmm}"))
    refs = [n["reference"] for n in new]
    assert len(set(refs)) == len(refs)
    assert not (set(refs) & old), "a new reference collides with an imported one"
    assert not ({n["reservation_id"] for n in new} & old_ids), "a new reservation_id collides with an imported one"


@pytest.mark.ledger("S1-086")
def test_import_twice_does_not_duplicate(api, populated):
    s = populated
    exported = api.export()
    expect(api.import_(exported), 204)
    expect(api.import_(exported), 204)
    assert _snapshot(api, s.toks) == s.snap
    assert api.export()["state"] is not None


@pytest.mark.ledger("S1-090")
def test_export_is_a_snapshot_later_writes_not_included(api, populated):
    s = populated
    exported = api.export()
    frozen = json.dumps(exported, sort_keys=True)
    k4, b4 = tk.new_key(), body("r_anker", "t_1", f"{FRI}T20:00", 2)
    later = expect(api.create(s.ada, b4, key=k4), 201)
    expect(api.cancel(s.ada, s.o1["reference"]), 200)
    expect(api.import_(json.loads(frozen)), 204)
    assert _snapshot(api, s.toks) == s.snap
    expect(api.get(s.ada, later["reference"]), 404, "not_found")
    # the later write's key is not in the snapshot: it is a first use again
    again = api.create(s.ada, b4, key=k4)
    expect(again, 201)
    assert again.json["reference"] != s.o1["reference"]


@pytest.mark.ledger("S1-090", "S1-088")
def test_export_during_concurrent_writes_is_consistent(api):
    w = tk.World(api)
    toks = [w.ada, w.bob, w.cy]
    jobs = []
    for i in range(24):
        jobs.append((toks[i % 3], tk.new_key(), body("r_big", f"b_{1 + i % 10}", f"{THU}T{10 + 2 * (i // 10):02d}:00", 2)))
    calls = [(lambda a, j=j: a.create(j[0], j[2], key=j[1])) for j in jobs]
    calls.insert(12, lambda a: a.call("GET", "/_test/export", timeout=tk.CTL_TIMEOUT))
    res = tk.parallel(calls)
    tk.assert_all_responses(res)
    exp_resp = res.pop(12)
    expect(exp_resp, 200)
    for r in res:
        expect(r, 201)
    expect(api.import_(exp_resp.json), 204)
    present = {r["reference"] for t in toks for r in api.list(t)}
    for (tok, key, b), r in zip(jobs, res):
        rr = api.create(tok, b, key=key)
        if r.json["reference"] in present:
            expect(rr, 200)
            assert rr.json == r.json, "booking present in export but its receipt is not"
        else:
            expect(rr, 201)  # neither the booking nor its receipt was exported


@pytest.mark.ledger("S1-087", "S1-020")
@pytest.mark.parametrize("bad", [
    "RAW:not json",
    {},
    {"track": "tablekeeper", "format_version": 1},
    {"track": "tablekeeper", "state": {}},
    {"format_version": 1, "state": {}},
    "WRONG_TRACK",
    "WRONG_VERSION",
    "STATE_STRING",
    "STATE_LIST",
    "STATE_NUMBER",
], ids=["not-json", "empty", "no-state", "no-version", "no-track", "wrong-track", "wrong-version",
        "state-string", "state-list", "state-number"])
def test_invalid_import_rejected_and_destination_unchanged(api, populated, bad):
    s = populated
    exported = api.export()
    if bad == "RAW:not json":
        expect(api.import_(raw="{not json"), 400, "malformed_request")
    else:
        if bad == "WRONG_TRACK":
            bad = {**exported, "track": "toy"}
        elif bad == "WRONG_VERSION":
            bad = {**exported, "format_version": 2}
        elif bad == "STATE_STRING":
            bad = {**exported, "state": "x"}
        elif bad == "STATE_LIST":
            bad = {**exported, "state": []}
        elif bad == "STATE_NUMBER":
            bad = {**exported, "state": 5}
        expect(api.import_(bad), 422, "validation_failed")
    _assert_destination_unchanged(api, s)


def _assert_destination_unchanged(api, s):
    """After a rejected import (§10: 'without changing the destination'): bookings, tokens AND every
    idempotency receipt are intact; replays create nothing. Tuned after Gate fault probe M8."""
    assert _snapshot(api, s.toks) == s.snap
    for key, b, o, tok in ((s.k1, s.b1, s.o1, s.ada), (s.k2, s.b2, s.o2, s.ada), (s.k3, s.b3, s.o3, s.dee)):
        rr = api.create(tok, b, key=key)
        expect(rr, 200)
        assert rr.json == o, "receipt changed or lost after a rejected import"
    rm = api.moves(s.ada, s.bm, key=s.km)
    expect(rm, 200)
    assert rm.json == s.om, "batch receipt changed or lost after a rejected import"
    expect(api.create(s.ada, s.b2, key=s.k1), 409, "idempotency_key_reuse")
    expect(api.moves(s.ada, {"moves": [{"reference": s.o2["reference"], "party_size": 1}]}, key=s.km),
           409, "idempotency_key_reuse")
    assert _snapshot(api, s.toks) == s.snap, "a replay after a rejected import changed state"


def _corruptions(state):
    """Type-corrupted copies of an opaque state: each top-level value, and the first element of each
    top-level container, replaced by a value of another JSON type."""
    def other(v):
        return 12345 if isinstance(v, (str, list, dict)) else "corrupt"
    out = []
    for k, v in state.items():
        out.append((f"{k}", {**state, k: other(v)}))
        if isinstance(v, list) and v:
            out.append((f"{k}[0]", {**state, k: [other(v[0])] + v[1:]}))
        elif isinstance(v, dict) and v:
            k2 = next(iter(v))
            out.append((f"{k}.{k2}", {**state, k: {**v, k2: other(v[k2])}}))
    return out


@pytest.mark.ledger("S1-087", "S1-088")
def test_import_of_internally_invalid_state_is_all_or_nothing(api, populated):
    """§10: an invalid state gives 422 without changing the destination. The state format is the
    service's own, so a corrupted copy may also be accepted (204); a 422 must leave everything intact.
    Tuned after Gate fault probe M8 (receipts dropped on a rejected import)."""
    s = populated
    exported = api.export()
    rejected = 0
    for name, state in _corruptions(exported["state"]):
        r = api.import_({**exported, "state": state})
        expect_no_5xx(r)
        if r.status == 204:
            expect(api.import_(exported), 204)  # accepted as valid: restore and continue
            continue
        expect(r, 422, "validation_failed")
        rejected += 1
        _assert_destination_unchanged(api, s)
    assert rejected, "no corrupted state was rejected; the invalid-state path is untested"


@pytest.mark.ledger("S1-091", "S1-008")
def test_reset_after_import_clears_imported_state(api, populated):
    s = populated
    exported = api.export()
    api.reset(tk.fixture(users=(ZED,), restaurants=(OTHER_REST,)))
    expect(api.import_(exported), 204)
    api.reset(tk.fixture(users=(ZED,), restaurants=(OTHER_REST,)))
    expect(api.call("GET", "/reservations", token=s.ada), 401, "unauthenticated")
    expect(api.call("GET", "/reservations", token=s.dee), 401, "unauthenticated")
    expect(api.login("dee@example.com", "dee secret pw"), 401, "unauthenticated")
    expect(api.call("GET", "/restaurants/r_anker"), 404, "not_found")


@pytest.mark.ledger("S1-036")
def test_export_contains_no_plaintext_password(api, populated):
    text = json.dumps(api.export())
    for pw in (tk.ADA["password"], tk.BOB["password"], tk.CY["password"], "dee secret pw"):
        assert pw not in text, f"plaintext password {pw!r} found in the export"
        assert json.dumps(pw)[1:-1] not in text


@pytest.mark.ledger("S1-088", "S1-035")
def test_new_logins_after_import_and_old_tokens_coexist(api, populated):
    s = populated
    exported = api.export()
    api.reset(tk.fixture())
    expect(api.import_(exported), 204)
    fresh = api.token("dee@example.com", "dee secret pw")
    assert _snapshot(api, {"dee": fresh})["dee"] == s.snap["dee"]
    assert _snapshot(api, {"dee": s.dee})["dee"] == s.snap["dee"]
    expect(api.signup("dee@example.com", "another pw!", "Dee2"), 409, "email_taken")


@pytest.mark.ledger("S1-090", "S1-088", "S1-002")
@pytest.mark.skipif(not tk.SECOND_BASE_URL, reason="TK_SECOND_BASE_URL not set (needs a second, fresh container)")
def test_import_into_a_fresh_second_container(api, populated):
    s = populated
    exported = api.export()
    other = tk.Api(tk.SECOND_BASE_URL)
    try:
        other.reset(tk.fixture(users=(ZED,), restaurants=(OTHER_REST,)))
        expect(other.import_(exported), 204)
        assert _snapshot(other, s.toks) == s.snap
        rr = other.create(s.ada, s.b1, key=s.k1)
        expect(rr, 200)
        assert rr.json == s.o1
        rm = other.moves(s.ada, s.bm, key=s.km)
        expect(rm, 200)
        assert rm.json == s.om
        assert other.token(tk.BOB["email"], tk.BOB["password"])
    finally:
        other.close()
