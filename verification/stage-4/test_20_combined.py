"""Combined tables (stage-2 spec "Combined tables", "Model", "API"; ledger S2-030..S2-042, A-20, A-22)."""
import pytest

import tk
from tk import COMBO, THU, FRI, expect

T = f"{THU}T19:00"


def cb(tables, local=T, party=2, rid="r_combo"):
    b = {"restaurant_id": rid, "starts_at_local": local, "party_size": party}
    if isinstance(tables, list):
        b["table_ids"] = tables
    else:
        b["table_id"] = tables
    return b


@pytest.fixture
def cw(api):
    return tk.World(api, tk.fixture(restaurants=(tk.ANKER, COMBO)))


def options(api, local, party, rid="r_combo"):
    for s in api.slots(rid, local[:10], party):
        if s["starts_at_local"] == local:
            return s
    raise AssertionError(f"no slot {local}")


def opt(ids, cap):
    return {"table_ids": ids, "capacity": cap}


# ---- availability ------------------------------------------------------------------------

@pytest.mark.ledger("S2-033", "S2-031", "S2-030")
@pytest.mark.parametrize("party,singles,opts", [
    (1, ["c_1", "c_2", "c_3", "c_4"], [opt(["c_1"], 2), opt(["c_2"], 4), opt(["c_3"], 2), opt(["c_4"], 6),
                                         opt(["c_1", "c_2"], 6), opt(["c_3", "c_2"], 6), opt(["c_4", "c_1"], 8)]),
    (3, ["c_2", "c_4"], [opt(["c_2"], 4), opt(["c_4"], 6), opt(["c_1", "c_2"], 6), opt(["c_3", "c_2"], 6),
                         opt(["c_4", "c_1"], 8)]),
    (5, ["c_4"], [opt(["c_4"], 6), opt(["c_1", "c_2"], 6), opt(["c_3", "c_2"], 6), opt(["c_4", "c_1"], 8)]),
    (7, [], [opt(["c_4", "c_1"], 8)]),
    (8, [], [opt(["c_4", "c_1"], 8)]),
    (9, [], []),
])
def test_available_options_order_and_capacity(cw, api, party, singles, opts):
    s = options(api, T, party)
    assert s["available_table_ids"] == singles
    assert s["available_options"] == opts


@pytest.mark.ledger("S2-033", "S2-037")
def test_pair_booking_blocks_members_and_every_pair_containing_them(cw, api):
    r = api.create(cw.ada, cb(["c_1", "c_2"], party=5))
    expect(r, 201)
    s = options(api, T, 1)
    assert s["available_table_ids"] == ["c_3", "c_4"]
    assert s["available_options"] == [opt(["c_3"], 2), opt(["c_4"], 6)]
    later = options(api, f"{THU}T20:30", 1)  # back-to-back: everything free again
    assert len(later["available_options"]) == 7


@pytest.mark.ledger("S2-033", "S1-052")
def test_single_booking_blocks_pairs_containing_it(cw, api):
    expect(api.create(cw.ada, cb("c_2")), 201)
    s = options(api, f"{THU}T19:30", 1)
    assert s["available_table_ids"] == ["c_1", "c_3", "c_4"]
    assert s["available_options"] == [opt(["c_1"], 2), opt(["c_3"], 2), opt(["c_4"], 6), opt(["c_4", "c_1"], 8)]


# ---- create ------------------------------------------------------------------------------

@pytest.mark.ledger("S2-034", "S2-035", "S2-031")
def test_create_pair_response_shape(cw, api):
    r = api.create(cw.ada, cb(["c_3", "c_2"], party=6))
    expect(r, 201)
    tk.assert_res(r.json, COMBO, ["c_3", "c_2"], T, 6, "confirmed")
    assert "table_id" not in r.json
    for got in (api.get_ok(cw.ada, r.json["reference"]), api.list(cw.ada)[0]):
        assert got["table_ids"] == ["c_3", "c_2"] and "table_id" not in got


@pytest.mark.ledger("S2-034", "S2-035")
def test_single_table_both_forms(cw, api):
    a = api.create(cw.ada, cb("c_2"))
    expect(a, 201)
    assert a.json["table_id"] == "c_2" and a.json["table_ids"] == ["c_2"]
    b = api.create(cw.ada, cb(["c_4"], local=f"{THU}T20:00"))
    expect(b, 201)
    assert b.json["table_id"] == "c_4" and b.json["table_ids"] == ["c_4"]


@pytest.mark.ledger("S2-034", "A-22", "S2-035")
def test_reversed_pair_names_same_set_returned_in_combinable_order(cw, api):
    r = api.create(cw.ada, cb(["c_2", "c_1"], party=5))
    expect(r, 201)
    assert r.json["table_ids"] == ["c_1", "c_2"]


@pytest.mark.ledger("S2-036", "S2-034", "A-20")
@pytest.mark.parametrize("b,status,code", [
    ({**cb("c_1"), "table_ids": ["c_1"]}, 422, "validation_failed"),
    ({"restaurant_id": "r_combo", "starts_at_local": T, "party_size": 2}, 422, "validation_failed"),
    (cb([]), 422, "validation_failed"),
    (cb(["c_1", "c_1"]), 422, "validation_failed"),
    (cb(["c_1", "c_2", "c_3"]), 422, "combination_not_allowed"),
    (cb(["c_1", "c_3"]), 422, "combination_not_allowed"),
    (cb(["c_3", "c_4"]), 422, "combination_not_allowed"),
    (cb(["c_1", "zz"]), 404, "not_found"),
    (cb(["c_1", "t_1"]), 404, "not_found"),
    (cb(["c_1", "c_2", "zz"]), 404, "not_found"),
    (cb(["c_1", "c_1", "zz"]), 422, "validation_failed"),
    (cb("c_1,c_2"), 404, "not_found"),
    ({**cb([]), "table_ids": "c_1"}, 400, "malformed_request"),
    ({**cb([]), "table_ids": ["c_1", 2]}, 400, "malformed_request"),
    ({**cb([]), "table_ids": {"a": "c_1"}}, 400, "malformed_request"),
    (cb(["c_1", "c_2"], party=7), 422, "party_exceeds_capacity"),
    (cb(["c_1", "c_3"], local=f"{THU}T19:15"), 422, "combination_not_allowed"),
    (cb(["c_1", "c_2"], local=f"{THU}T19:15"), 422, "not_on_slot_grid"),
    (cb(["c_1", "c_2"], local=f"{THU}T22:00", party=7), 422, "outside_opening_hours"),
    (cb(["c_1", "c_2"], local="2026-03-29T02:30"), 422, "invalid_local_time"),
], ids=["both", "neither", "empty", "duplicate", "three", "undeclared", "undeclared2", "unknown-member",
        "foreign-member", "three-with-unknown", "duplicate-with-unknown", "comma-string-as-id", "ids-string",
        "ids-non-string-member", "ids-object", "over-summed-capacity", "undeclared-beats-grid", "grid",
        "hours-beat-capacity", "gap"])
def test_table_set_validation(cw, api, b, status, code):
    expect(api.create(cw.ada, b), status, code)
    assert api.list(cw.ada) == []


@pytest.mark.ledger("S2-031", "S2-038", "S1-061")
def test_party_equal_to_summed_capacity_accepted(cw, api):
    r = api.create(cw.ada, cb(["c_4", "c_1"], party=8))
    expect(r, 201)
    assert r.json["table_ids"] == ["c_4", "c_1"]


@pytest.mark.ledger("S2-037", "S1-058")
def test_member_taken_gives_409(cw, api):
    api.book(cw.bob, "r_combo", "c_2", f"{THU}T18:00")
    expect(api.create(cw.ada, cb(["c_1", "c_2"], party=5)), 409, "table_unavailable")
    expect(api.create(cw.ada, cb(["c_3", "c_2"], party=5)), 409, "table_unavailable")
    expect(api.create(cw.ada, cb(["c_4", "c_1"], party=5)), 201)
    expect(api.create(cw.cy, cb("c_1", local=f"{THU}T20:00")), 409, "table_unavailable")
    expect(api.create(cw.cy, cb("c_4", local=f"{THU}T18:00")), 409, "table_unavailable")
    expect(api.create(cw.cy, cb("c_4", local=f"{THU}T20:30")), 201)  # back-to-back after the pair


# ---- PATCH, cancel, moves ----------------------------------------------------------------

@pytest.mark.ledger("S2-039", "S2-035")
def test_patch_single_to_pair_and_back(cw, api):
    m = expect(api.create(cw.ada, cb("c_2", party=3)), 201)
    p = api.patch(cw.ada, m["reference"], {"table_ids": ["c_1", "c_2"], "party_size": 6})
    expect(p, 200)
    tk.assert_res(p.json, COMBO, ["c_1", "c_2"], T, 6)
    tk.same_identity(p.json, m)
    assert "c_1" not in options(api, T, 1)["available_table_ids"]
    p = api.patch(cw.ada, m["reference"], {"table_id": "c_4"})
    expect(p, 200)
    tk.assert_res(p.json, COMBO, "c_4", T, 6)
    assert options(api, T, 1)["available_table_ids"] == ["c_1", "c_2", "c_3"]


@pytest.mark.ledger("S2-039", "A-20")
@pytest.mark.parametrize("b,status,code", [
    ({"table_id": "c_1", "table_ids": ["c_1"]}, 422, "validation_failed"),
    ({"table_ids": []}, 422, "validation_failed"),
    ({"table_ids": ["c_1", "c_3"]}, 422, "combination_not_allowed"),
    ({"table_ids": ["c_1", "c_2"], "party_size": 7}, 422, "party_exceeds_capacity"),
    ({"table_ids": "c_1"}, 400, "malformed_request"),
    ({"table_ids": ["c_4", "c_1"]}, 409, "table_unavailable"),
])
def test_patch_table_set_rules_and_no_change_on_failure(cw, api, b, status, code):
    api.book(cw.bob, "r_combo", "c_4", f"{THU}T19:30")
    m = expect(api.create(cw.ada, cb("c_2", party=3)), 201)
    expect(api.patch(cw.ada, m["reference"], b), status, code)
    assert api.get_ok(cw.ada, m["reference"]) == m


@pytest.mark.ledger("S2-039", "S1-070")
def test_cancel_pair_frees_every_member(cw, api):
    m = expect(api.create(cw.ada, cb(["c_4", "c_1"], party=8)), 201)
    c = api.cancel(cw.ada, m["reference"])
    expect(c, 200)
    assert c.json["status"] == "cancelled" and c.json["table_ids"] == ["c_4", "c_1"] and "table_id" not in c.json
    assert len(options(api, T, 1)["available_options"]) == 7


@pytest.mark.ledger("S2-040", "S1-100")
def test_moves_with_table_ids(cw, api):
    A = expect(api.create(cw.ada, cb(["c_1", "c_2"], party=5)), 201)
    B = expect(api.create(cw.ada, cb("c_4", party=2)), 201)
    r = api.moves(cw.ada, {"moves": [{"reference": A["reference"], "table_ids": ["c_4", "c_1"]},
                                     {"reference": B["reference"], "table_ids": ["c_3"]}]})
    expect(r, 201)
    a, b = r.json["reservations"]
    tk.assert_res(a, COMBO, ["c_4", "c_1"], T, 5)
    tk.assert_res(b, COMBO, "c_3", T, 2)


@pytest.mark.ledger("S2-040", "S1-100", "S1-102")
def test_moves_member_overlap_among_results_409(cw, api):
    A = expect(api.create(cw.ada, cb(["c_1", "c_2"], party=5)), 201)
    B = expect(api.create(cw.ada, cb("c_4", party=2)), 201)
    bad = {"moves": [{"reference": A["reference"], "table_ids": ["c_3", "c_2"]},
                     {"reference": B["reference"], "table_id": "c_3"}]}
    expect(api.moves(cw.ada, bad), 409, "table_unavailable")
    assert api.get_ok(cw.ada, A["reference"]) == A and api.get_ok(cw.ada, B["reference"]) == B


@pytest.mark.ledger("S2-040", "A-20")
def test_moves_item_table_set_validation(cw, api):
    A = expect(api.create(cw.ada, cb(["c_1", "c_2"], party=5)), 201)
    expect(api.moves(cw.ada, {"moves": [{"reference": A["reference"], "table_ids": ["c_1", "c_3"]}]}),
           422, "combination_not_allowed")
    expect(api.moves(cw.ada, {"moves": [{"reference": A["reference"], "table_id": "c_4", "table_ids": ["c_4"]}]}),
           422, "validation_failed")
    expect(api.moves(cw.ada, {"moves": [{"reference": A["reference"], "table_ids": ["c_3"]}]}),
           422, "party_exceeds_capacity")


# ---- seeds, replay, export ----------------------------------------------------------------

@pytest.mark.ledger("S2-032", "S1-015")
def test_seeded_pairs_and_cancelled_seeds(api):
    seeds = [
        {"id": "sp1", "reference": "PAIR01", "user_id": "u_ada", "restaurant_id": "r_combo",
         "table_ids": ["c_1", "c_2"], "starts_at_local": T, "party_size": 5},
        {"id": "sc1", "reference": "CANC01", "user_id": "u_ada", "restaurant_id": "r_combo",
         "table_id": "c_4", "starts_at_local": T, "party_size": 2, "status": "cancelled"},
    ]
    w = tk.World(api, tk.fixture(restaurants=(tk.ANKER, COMBO), reservations=seeds))
    s = options(api, T, 1)
    assert s["available_table_ids"] == ["c_3", "c_4"]
    got = {r["reference"]: r for r in api.list(w.ada)}
    assert got["PAIR01"]["table_ids"] == ["c_1", "c_2"] and got["PAIR01"]["status"] == "confirmed"
    assert got["CANC01"]["status"] == "cancelled" and got["CANC01"]["table_id"] == "c_4"
    expect(api.cancel(w.ada, "CANC01"), 200)


@pytest.mark.ledger("S2-035", "S1-039")
def test_pair_replay_identical(cw, api):
    key = tk.new_key()
    first = expect(api.create(cw.ada, cb(["c_1", "c_2"], party=5), key=key), 201)
    again = api.create(cw.ada, cb(["c_1", "c_2"], party=5), key=key)
    expect(again, 200)
    assert again.json == first
    expect(api.create(cw.ada, cb(["c_2", "c_1"], party=5), key=key), 409, "idempotency_key_reuse")


@pytest.mark.ledger("S2-042", "S1-086", "S1-088")
def test_export_import_round_trips_pairs(cw, api):
    key = tk.new_key()
    first = expect(api.create(cw.ada, cb(["c_3", "c_2"], party=5), key=key), 201)
    snap = api.list(cw.ada)
    avail = api.avail("r_combo", THU, 1).json
    e = api.export()
    api.reset(tk.fixture())
    expect(api.import_(e), 204)
    assert api.list(cw.ada) == snap
    assert api.avail("r_combo", THU, 1).json == avail
    again = api.create(cw.ada, cb(["c_3", "c_2"], party=5), key=key)
    expect(again, 200)
    assert again.json == first


@pytest.mark.ledger("S2-041", "S1-067", "S1-080")
def test_parallel_pairs_and_singles_never_share_a_table(api):
    fx = tk.fixture(users=(tk.ADA, tk.BOB, tk.CY, *tk.extra_users(7)), restaurants=(COMBO,))
    w = tk.World(api, fx)
    toks = [w.tok(u["id"]) for u in fx["users"]]
    sets = [["c_1", "c_2"], ["c_3", "c_2"], ["c_4", "c_1"], "c_1", "c_2", "c_3", "c_4"]
    times = ["19:00", "19:30", "20:00"]
    reqs = [(toks[i % len(toks)], cb(sets[i % len(sets)], local=f"{THU}T{times[i % 3]}", party=2)) for i in range(42)]
    res = tk.parallel([(lambda a, t=t, b=b: a.create(t, b)) for t, b in reqs])
    tk.assert_all_responses(res)
    for r in res:
        if r.status != 201:
            expect(r, 409, "table_unavailable")
    accepted = [r.json for r in res if r.status == 201]
    assert accepted
    stored = {}
    for t in toks:
        for r in api.list(t):
            stored[r["reference"]] = r
    assert sorted(stored) == sorted(a["reference"] for a in accepted)
    tk.assert_no_overlaps(list(stored.values()))
    for (t, b), r in zip(reqs, res):
        if r.status == 409:
            probe = {"starts_at": tk.exp_start(b["starts_at_local"], "Europe/Berlin"),
                     "ends_at": tk.exp_end(b["starts_at_local"], "Europe/Berlin", 90),
                     "table_ids": b.get("table_ids") or [b["table_id"]], "restaurant_id": "r_combo", "status": "confirmed"}
            assert any(set(tk.tables_of(probe)) & set(tk.tables_of(a)) and tk.intervals_overlap(probe, a)
                       for a in accepted), f"409 without a conflicting accepted booking: {b}"


@pytest.mark.ledger("S2-041", "S1-105")
def test_parallel_pair_moves_and_cancels_consistent(api):
    w = tk.World(api, tk.fixture(restaurants=(COMBO,)))
    A = expect(api.create(w.ada, cb(["c_1", "c_2"], party=5)), 201)
    B = expect(api.create(w.ada, cb("c_4", party=2)), 201)
    C = expect(api.create(w.ada, cb("c_3", party=2)), 201)
    flip = {"moves": [{"reference": A["reference"], "table_ids": ["c_4", "c_1"]},
                      {"reference": B["reference"], "table_id": "c_2"}]}
    flop = {"moves": [{"reference": A["reference"], "table_ids": ["c_1", "c_2"]},
                      {"reference": B["reference"], "table_id": "c_4"}]}
    calls = [(lambda a, bb=(flip if i % 2 else flop): a.moves(w.ada, bb)) for i in range(12)]
    calls += [(lambda a: a.create(w.bob, cb("c_2", party=2))) for _ in range(4)]
    calls += [(lambda a: a.call("GET", "/reservations", token=w.ada)) for _ in range(8)]
    calls += [lambda a: a.cancel(w.ada, C["reference"])]
    res = tk.parallel(calls)
    tk.assert_all_responses(res)
    for r in res[:12]:
        assert r.status in (201, 409), r
    for r in res[24:25]:
        expect(r, 200)
    for r in res[16:24]:
        expect(r, 200)
        tk.assert_no_overlaps(r.json["reservations"])
        st = {x["reference"]: tuple(x["table_ids"]) for x in r.json["reservations"]}
        assert (st[A["reference"]], st[B["reference"]]) in {(("c_1", "c_2"), ("c_4",)), (("c_4", "c_1"), ("c_2",))}, st
    final = api.list(w.ada) + api.list(w.bob)
    tk.assert_no_overlaps(final)
