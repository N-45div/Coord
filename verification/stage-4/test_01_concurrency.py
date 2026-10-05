"""Concurrency: genuinely parallel requests (barrier-released threads, one connection each).

Spec §1: two confirmed reservations never occupy the same table at overlapping times,
including during concurrent requests. §2: up to 50 in flight, 5 s each. §5: no 5xx.
§7: concurrent identical requests with an unused key -> exactly one 201, rest 200.
"""
import pytest

import tk
from tk import ANKER, BIG, THU, body, expect


def _users_world(api, n):
    fx = tk.fixture(users=(tk.ADA, tk.BOB, tk.CY, *tk.extra_users(n)))
    w = tk.World(api, fx)
    toks = [w.tok(u["id"]) for u in fx["users"]]
    return w, toks


def _all_reservations(api, toks):
    seen = {}
    for t in toks:
        for r in api.list(t):
            seen[r["reference"]] = r
    return list(seen.values())


@pytest.mark.ledger("S1-067", "S1-058", "S1-006", "S1-005", "S1-045")
def test_50_parallel_creates_same_table_same_slot_one_winner(api):
    w, toks = _users_world(api, 7)  # 10 users, 5 distinct keys each
    b = body("r_anker", "t_2", f"{THU}T19:00", 2)
    calls = [(lambda a, t=toks[i % len(toks)]: a.create(t, b)) for i in range(50)]
    res = tk.parallel(calls)
    tk.assert_all_responses(res)
    won = [r for r in res if r.status == 201]
    lost = [r for r in res if r.status != 201]
    assert len(won) == 1, f"expected exactly one 201, got {len(won)}: {[r.status for r in res]}"
    for r in lost:
        expect(r, 409, "table_unavailable")
    allres = _all_reservations(api, toks)
    assert [r["reference"] for r in allres] == [won[0].json["reference"]]
    assert "t_2" not in api.free_tables("r_anker", f"{THU}T19:00", 1)


@pytest.mark.ledger("S1-067", "S1-080", "S1-058", "S1-006")
def test_parallel_overlapping_creates_never_overlap_and_rejections_are_justified(api):
    w, toks = _users_world(api, 7)
    times = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
    reqs = [(toks[i % len(toks)], body("r_anker", "t_1", f"{THU}T{times[i % 8]}", 2)) for i in range(48)]
    res = tk.parallel([(lambda a, t=t, b=b: a.create(t, b)) for t, b in reqs])
    tk.assert_all_responses(res)
    accepted = [r.json for r in res if r.status == 201]
    for r in res:
        if r.status != 201:
            expect(r, 409, "table_unavailable")
    assert accepted, "no booking succeeded"
    tk.assert_no_overlaps(accepted)
    stored = [r for r in _all_reservations(api, toks) if r["table_id"] == "t_1"]
    assert sorted(r["reference"] for r in stored) == sorted(r["reference"] for r in accepted)
    tk.assert_no_overlaps(stored)
    # every rejected request must actually overlap an accepted booking (409 only when taken, §8)
    for (t, b), r in zip(reqs, res):
        if r.status == 409:
            probe = {"starts_at": tk.exp_start(b["starts_at_local"], ANKER["timezone"]),
                     "ends_at": tk.exp_end(b["starts_at_local"], ANKER["timezone"], 90)}
            assert any(tk.intervals_overlap(probe, a) for a in accepted), \
                f"409 for {b['starts_at_local']} although no accepted booking overlaps it"


@pytest.mark.ledger("S1-045", "S1-039", "S1-046")
def test_parallel_identical_requests_unused_key_one_201_rest_200(api):
    w = tk.World(api)
    t1, t2 = w.ada, api.token(tk.ADA["email"], tk.ADA["password"])  # two tokens, same user
    b = body("r_anker", "t_3", f"{THU}T20:00", 5)
    key = tk.new_key()
    res = tk.parallel([(lambda a, t=(t1 if i % 2 else t2): a.create(t, b, key=key)) for i in range(30)])
    tk.assert_all_responses(res)
    statuses = sorted(r.status for r in res)
    assert statuses.count(201) == 1 and statuses.count(200) == 29, f"statuses: {statuses}"
    original = next(r.json for r in res if r.status == 201)
    for r in res:
        assert r.json == original, f"replay body differs from the original: {r.json} vs {original}"
    assert len(api.list(t1)) == 1


@pytest.mark.ledger("S1-040", "S1-045", "S1-006")
def test_parallel_same_key_different_bodies_take_effect_once(api):
    w = tk.World(api)
    key = tk.new_key()
    bodies = [body("r_big", f"b_{1 + i % 10}", f"{THU}T{10 + i // 10:02d}:00", 2) for i in range(20)]
    res = tk.parallel([(lambda a, b=b: a.create(w.ada, b, key=key)) for b in bodies])
    tk.assert_all_responses(res)
    won = [r for r in res if r.status == 201]
    assert len(won) == 1, [r.status for r in res]
    for r in res:
        if r.status != 201:
            expect(r, 409, "idempotency_key_reuse")
    assert len(api.list(w.ada)) == 1


@pytest.mark.ledger("S1-080", "S1-079", "S1-006")
def test_parallel_patches_competing_for_one_table(api):
    w = tk.World(api)
    mine = [api.book(w.ada, "r_big", f"b_{i}", f"{THU}T12:00") for i in range(1, 10)]
    res = tk.parallel([(lambda a, m=m: a.patch(w.ada, m["reference"], {"table_id": "b_10"})) for m in mine])
    tk.assert_all_responses(res)
    ok = [i for i, r in enumerate(res) if r.status == 200]
    assert len(ok) == 1, [r.status for r in res]
    for i, r in enumerate(res):
        if i not in ok:
            expect(r, 409, "table_unavailable")
            cur = api.get_ok(w.ada, mine[i]["reference"])
            assert cur["table_id"] == mine[i]["table_id"] and cur["starts_at"] == mine[i]["starts_at"]
    after = api.list(w.ada)
    tk.assert_no_overlaps(after)
    assert sum(1 for r in after if r["table_id"] == "b_10") == 1


@pytest.mark.ledger("S1-080", "S1-105", "S1-102", "S1-006")
def test_parallel_creates_patches_and_moves_on_one_interval(api):
    w, toks = _users_world(api, 5)
    ada, bob = w.ada, w.bob
    # bookings that will try to move onto b_10 around 12:00
    a_src = [api.book(ada, "r_big", f"b_{i}", f"{THU}T12:00") for i in range(1, 6)]
    b_src = [api.book(bob, "r_big", f"b_{i}", f"{THU}T14:00") for i in range(1, 6)]
    calls = []
    for i, t in enumerate(toks):  # creates
        calls.append(lambda a, t=t, i=i: a.create(t, body("r_big", "b_10", f"{THU}T{12 + (i % 2)}:{'30' if i % 3 else '00'}")))
    for m in a_src:  # single PATCHes
        calls.append(lambda a, m=m: a.patch(ada, m["reference"], {"table_id": "b_10", "starts_at_local": f"{THU}T12:30"}))
    pairs = [(b_src[0], b_src[1]), (b_src[2], b_src[3])]
    for x, y in pairs:  # two-item batches: one item onto b_10, one elsewhere
        calls.append(lambda a, x=x, y=y: a.moves(bob, {"moves": [
            {"reference": x["reference"], "table_id": "b_10", "starts_at_local": f"{THU}T12:00"},
            {"reference": y["reference"], "starts_at_local": f"{THU}T16:00"}]}))
    res = tk.parallel(calls)
    tk.assert_all_responses(res)
    for r in res:
        assert r.status in (200, 201, 409), r
        if r.status == 409:
            expect(r, 409, "table_unavailable")
    everything = _all_reservations(api, toks)
    tk.assert_no_overlaps(everything)
    by_ref = {r["reference"]: r for r in everything}
    for (x, y), r in zip(pairs, res[-2:]):
        moved_x = by_ref[x["reference"]]["table_id"] == "b_10"
        moved_y = by_ref[y["reference"]]["starts_at_local"] == f"{THU}T16:00"
        assert moved_x == moved_y == (r.status == 201), \
            f"partial batch visible: x moved={moved_x}, y moved={moved_y}, response {r.status}"


@pytest.mark.ledger("S1-105", "S1-102", "S1-100")
def test_parallel_batches_never_observed_half_applied(api):
    w = tk.World(api)
    A = api.book(w.ada, "r_big", "b_1", f"{THU}T12:00")
    B = api.book(w.ada, "r_big", "b_2", f"{THU}T12:00")
    swap = {"moves": [{"reference": A["reference"], "table_id": "b_2"}, {"reference": B["reference"], "table_id": "b_1"}]}
    away = {"moves": [{"reference": A["reference"], "table_id": "b_3"}, {"reference": B["reference"], "table_id": "b_4"}]}
    back = {"moves": [{"reference": A["reference"], "table_id": "b_1"}, {"reference": B["reference"], "table_id": "b_2"}]}
    calls = []
    for i in range(18):
        bb = (swap, away, back)[i % 3]
        calls.append(lambda a, bb=bb: a.moves(w.ada, bb))
    for _ in range(12):
        calls.append(lambda a: a.call("GET", "/reservations", token=w.ada))
    res = tk.parallel(calls)
    tk.assert_all_responses(res)
    legal = {("b_1", "b_2"), ("b_2", "b_1"), ("b_3", "b_4")}
    for r in res[:18]:
        expect(r, 201)
    for r in res[18:]:
        expect(r, 200)
        tables = {x["reference"]: x["table_id"] for x in r.json["reservations"]}
        state = (tables[A["reference"]], tables[B["reference"]])
        assert state in legal, f"half-applied batch observed: A,B on {state}"
    final = {x["reference"]: x["table_id"] for x in api.list(w.ada)}
    assert (final[A["reference"]], final[B["reference"]]) in legal


@pytest.mark.ledger("S1-005", "S1-006")
def test_50_mixed_reads_in_flight_within_5s(api):
    w = tk.World(api)
    tok = w.ada
    api.book(tok, "r_anker", "t_1", f"{THU}T19:00")
    kinds = [
        lambda a: a.call("GET", "/restaurants"),
        lambda a: a.call("GET", "/restaurants/r_big"),
        lambda a: a.avail("r_big", THU, 2),
        lambda a: a.avail("r_anker", THU, 2),
        lambda a: a.call("GET", "/reservations", token=tok),
    ]
    res = tk.parallel([kinds[i % len(kinds)] for i in range(50)])
    tk.assert_all_responses(res)
    for r in res:
        expect(r, 200)


@pytest.mark.ledger("S1-029", "S1-006", "S1-027")
def test_parallel_signups_same_email_exactly_one_account(api):
    tk.World(api)
    res = tk.parallel([(lambda a, i=i: a.signup("race@example.com", f"password-{i:02d}", f"Racer{i}")) for i in range(20)])
    tk.assert_all_responses(res)
    won = [i for i, r in enumerate(res) if r.status == 201]
    assert len(won) == 1, [r.status for r in res]
    for i, r in enumerate(res):
        if i not in won:
            expect(r, 409, "email_taken")
    expect(api.login("race@example.com", f"password-{won[0]:02d}"), 200)


@pytest.mark.ledger("S1-070", "S1-054", "S1-067")
def test_parallel_cancel_and_rebook_same_slot(api):
    w, toks = _users_world(api, 7)
    X = api.book(w.ada, "r_big", "b_1", f"{THU}T12:00")
    calls = [lambda a: a.cancel(w.ada, X["reference"])]
    calls += [(lambda a, t=t: a.create(t, body("r_big", "b_1", f"{THU}T12:00"))) for t in toks[1:]]
    res = tk.parallel(calls)
    tk.assert_all_responses(res)
    expect(res[0], 200)
    assert res[0].json["status"] == "cancelled"
    won = [r for r in res[1:] if r.status == 201]
    assert len(won) <= 1, [r.status for r in res]
    for r in res[1:]:
        if r.status != 201:
            expect(r, 409, "table_unavailable")
    everything = _all_reservations(api, toks)
    tk.assert_no_overlaps(everything)
    # after the cancel completed the slot is free unless one rebooking won
    free = api.free_tables("r_big", f"{THU}T12:00", 1)
    assert ("b_1" in free) == (len(won) == 0)
