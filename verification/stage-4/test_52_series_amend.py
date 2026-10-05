"""Amending recurring reservations (stage-4 "Amend recurring reservations"; ledger S4-021..S4-029,
A-40, A-41)."""
from datetime import timedelta

import pytest

import tk
from tk import REP, MGR, DST_BER, expect
from test_50_replan import D, iso, world

DATES = ["2027-06-17", "2027-06-24", "2027-07-01", "2027-07-08"]


@pytest.fixture
def sw(api):
    w = world(api, [], restaurants=(REP, tk.REP2, DST_BER))
    w.anchor = api.book(w.ada, "r_rep", "r_3", f"{D}T19:00", 4)
    w.s = expect(api.series(w.ada, {"anchor_reference": w.anchor["reference"], "count": 4, "interval_weeks": 1}), 201)
    w.sid = w.s["series_id"]
    w.refs = [o["reference"] for o in w.s["occurrences"]]
    return w


def amend_body(rev, idx, hm, **extra):
    return {"expected_revision": rev, "from_index": idx, "local_time": hm, **extra}


def state(api, w):
    return {ref: api.get_ok(w.ada, ref) for ref in w.refs}, {ref: api.entries(w.ada, ref) for ref in w.refs}


@pytest.mark.ledger("S4-024", "S4-027", "S4-010", "A-41")
def test_amend_moves_eligible_occurrences(sw, api):
    rr0 = api.rrev(sw.mgr, "r_rep", "r_6")
    r = api.amend(sw.ada, sw.sid, amend_body(1, 1, "20:00"))
    expect(r, 201)
    j = r.json
    assert j["series_id"] == sw.sid and j["revision"] == 2
    assert [o["reference"] for o in j["occurrences"]] == sw.refs
    assert all(o["exception"] is False for o in j["occurrences"]), "series amendments do not mark exceptions"
    locs = [o["reservation"]["starts_at_local"] for o in j["occurrences"]]
    assert locs == [f"{DATES[0]}T19:00"] + [f"{d}T20:00" for d in DATES[1:]]
    for i, o in enumerate(j["occurrences"]):
        res = o["reservation"]
        assert res["table_ids"] == ["r_3"] and res["party_size"] == 4
        es = api.entries(sw.ada, o["reference"])
        if i == 0:
            assert res["revision"] == 1 and len(es) == 1
        else:
            assert res["revision"] == 2
            assert [e["event"] for e in es] == ["created", "changed"]
            assert es[1]["changes"] == [{"field": "starts_at_local", "from": f"{DATES[i]}T19:00",
                                         "to": f"{DATES[i]}T20:00"}]
            tk.assert_ts(res["ends_at"], f"{DATES[i]}T22:00:00+02:00")
    assert api.rrev(sw.mgr, "r_rep", "r_6") == rr0 + 1


@pytest.mark.ledger("S4-024", "S4-027")
def test_exceptions_and_cancelled_are_not_eligible(sw, api):
    expect(api.patch(sw.ada, sw.refs[2], {"party_size": 3}), 200)  # exception
    expect(api.cancel(sw.ada, sw.refs[3]), 200)
    g = expect(api.get_series(sw.ada, sw.sid), 200)
    assert g["revision"] == 3
    r = api.amend(sw.ada, sw.sid, amend_body(3, 1, "20:00"))
    expect(r, 201)
    occ = r.json["occurrences"]
    assert [o["reservation"]["starts_at_local"][11:] for o in occ] == ["19:00", "20:00", "19:00", "19:00"]
    assert occ[3]["reservation"]["status"] == "cancelled" and occ[2]["exception"] is True
    assert r.json["revision"] == 4


@pytest.mark.ledger("S4-025", "S4-027", "S4-010")
def test_all_noop_and_empty_eligible_sets_change_nothing(sw, api):
    rr0 = api.rrev(sw.mgr, "r_rep", "r_6")
    before = state(api, sw)
    r = api.amend(sw.ada, sw.sid, amend_body(1, 0, "19:00"))
    expect(r, 201)
    assert r.json["revision"] == 1
    assert state(api, sw) == before
    expect(api.cancel(sw.ada, sw.refs[3]), 200)
    r = api.amend(sw.ada, sw.sid, amend_body(2, 3, "21:00"))  # only occurrence 3, which is cancelled
    expect(r, 201)
    assert r.json["revision"] == 2
    assert api.rrev(sw.mgr, "r_rep", "r_6") == rr0 + 1  # only the cancel counted


@pytest.mark.ledger("S4-022", "A-40")
@pytest.mark.parametrize("bad", [
    {"expected_revision": 0}, {"expected_revision": -1}, {"expected_revision": True}, {"expected_revision": "1"},
    {"expected_revision": 1.5}, {"from_index": -1}, {"from_index": 4}, {"from_index": True}, {"from_index": "1"},
    {"local_time": "8:00"}, {"local_time": "24:00"}, {"local_time": "20:00:00"}, {"local_time": "2000"},
    {"local_time": 2000}, {"local_time": ""}, {"local_time": "20:60"},
    "NO_REV", "NO_INDEX", "NO_TIME",
], ids=lambda b: b if isinstance(b, str) else "-".join(f"{k}={v!r}" for k, v in b.items()))
def test_amend_body_validation(sw, api, bad):
    b = amend_body(1, 1, "20:00")
    if isinstance(bad, str):
        del b[{"NO_REV": "expected_revision", "NO_INDEX": "from_index", "NO_TIME": "local_time"}[bad]]
    else:
        b.update(bad)
    before = state(api, sw)
    expect(api.amend(sw.ada, sw.sid, b), 422, "validation_failed")
    assert state(api, sw) == before


@pytest.mark.ledger("S4-021", "S4-023", "S4-028", "A-40", "S1-040")
def test_amend_request_rules_stale_and_replay(sw, api):
    b = amend_body(1, 1, "20:00")
    expect(api.amend(None, sw.sid, b), 401, "unauthenticated")
    expect(api.amend(sw.bob, sw.sid, b), 404, "not_found")
    expect(api.amend(sw.ada, "no-such-series", b), 404, "not_found")
    expect(api.amend(sw.ada, sw.sid, b, key=None), 400, "missing_idempotency_key")
    expect(api.amend(sw.ada, sw.sid, raw="nope"), 400, "malformed_request")
    expect(api.amend(sw.ada, sw.sid, amend_body(2, 1, "20:00")), 409, "stale_revision")
    expect(api.amend(sw.ada, sw.sid, amend_body(2, 1, "22:30")), 409, "stale_revision")  # before validation
    key = tk.new_key()
    first = expect(api.amend(sw.ada, sw.sid, b, key=key), 201)
    expect(api.cancel(sw.ada, sw.refs[1]), 200)
    expect(api.patch(sw.ada, sw.refs[2], {"party_size": 2}), 200)
    again = api.amend(sw.ada, sw.sid, b, key=key)
    expect(again, 200)
    assert again.json == first, "replay returns the original response"
    expect(api.amend(sw.ada, sw.sid, amend_body(1, 2, "20:00"), key=key), 409, "idempotency_key_reuse")
    assert expect(api.get_series(sw.ada, sw.sid), 200)["revision"] == 4


@pytest.mark.ledger("S4-026", "S1-043")
def test_occupancy_conflict_changes_nothing(sw, api):
    api.book(sw.bob, "r_rep", "r_3", "2027-07-01T21:00", 2)  # occurrence 2 at 20:00 would overlap
    before = state(api, sw)
    rr0 = api.rrev(sw.mgr, "r_rep", "r_6")
    key = tk.new_key()
    expect(api.amend(sw.ada, sw.sid, amend_body(1, 1, "20:00"), key=key), 409, "table_unavailable")
    assert state(api, sw) == before
    assert api.rrev(sw.mgr, "r_rep", "r_6") == rr0
    assert expect(api.get_series(sw.ada, sw.sid), 200)["revision"] == 1
    expect(api.amend(sw.ada, sw.sid, amend_body(1, 1, "18:30"), key=key), 201)  # key reusable after 4xx


@pytest.mark.ledger("S4-026", "A-40")
def test_non_occupancy_errors_take_precedence_in_index_order(sw, api):
    expect(api.publish(sw.mgr, "r_rep", tk.policy("2027-07-01", slot=60, dur=120,
                                                  hours=REP["opening_hours"],
                                                  caps={t["id"]: t["capacity"] for t in REP["tables"]})), 201)
    api.book(sw.bob, "r_rep", "r_3", "2027-06-24T21:00", 2)  # occurrence 1 at 20:30 would overlap
    # occurrence 2 (2027-07-01) uses a 60-minute grid from 12:00: 20:30 is off-grid
    expect(api.amend(sw.ada, sw.sid, amend_body(1, 1, "20:30")), 422, "not_on_slot_grid")


@pytest.mark.ledger("S4-025", "S3-027", "S3-022")
def test_amended_occurrences_adopt_resulting_date_policy(sw, api):
    pol = tk.policy("2027-07-01", slot=30, dur=90, hours=REP["opening_hours"],
                    caps={t["id"]: t["capacity"] for t in REP["tables"]})
    expect(api.publish(sw.mgr, "r_rep", pol), 201)
    r = expect(api.amend(sw.ada, sw.sid, amend_body(1, 1, "20:00")), 201)
    occ = r["occurrences"]
    tk.assert_terms(occ[1]["reservation"]["accepted_terms"], tk.terms0(REP))
    for o, d in zip(occ[2:], DATES[2:]):
        tk.assert_terms(o["reservation"]["accepted_terms"], tk.terms_of(pol, 1))
        tk.assert_ts(o["reservation"]["ends_at"], f"{d}T21:30:00+02:00")


@pytest.mark.ledger("S4-025", "S1-063")
def test_dst_gap_rejects_whole_amendment(api):
    w = world(api, [], restaurants=(REP, DST_BER))
    a = api.book(w.ada, "r_dst_ber", "d_1", "2027-03-14T01:30", 2)
    s = expect(api.series(w.ada, {"anchor_reference": a["reference"], "count": 3, "interval_weeks": 1}), 201)
    refs = [o["reference"] for o in s["occurrences"]]
    before = [api.get_ok(w.ada, x) for x in refs]
    expect(api.amend(w.ada, s["series_id"], amend_body(1, 0, "02:30")), 422, "invalid_local_time")
    assert [api.get_ok(w.ada, x) for x in refs] == before


@pytest.mark.ledger("S4-029", "S3-031")
def test_concurrent_amendments_same_revision(sw, api):
    res = tk.parallel([(lambda a, hm=hm: a.amend(sw.ada, sw.sid, amend_body(1, 1, hm)))
                       for hm in ("19:30", "20:00", "20:30", "21:00") * 2])
    tk.assert_all_responses(res)
    ok = [r for r in res if r.status == 201]
    assert len(ok) == 1, [r.status for r in res]
    for r in res:
        if r.status != 201:
            expect(r, 409, "stale_revision")
    g = expect(api.get_series(sw.ada, sw.sid), 200)
    assert g["revision"] == 2
    times = {o["reservation"]["starts_at_local"][11:] for o in g["occurrences"][1:]}
    assert len(times) == 1, f"partially applied amendments: {times}"


@pytest.mark.ledger("S4-026", "S4-018")
def test_applied_closure_blocks_amendment(sw, api):
    p = expect(api.replan(sw.mgr, "r_rep", {"table_id": "r_3", "from": iso("2027-06-24T21:00"),
                                            "to": iso("2027-06-24T23:00")}), 201)
    assert p["assignments"] == []
    expect(api.apply(sw.mgr, "r_rep", p["plan_id"]), 201)
    expect(api.amend(sw.ada, sw.sid, amend_body(1, 1, "20:00")), 409, "table_unavailable")


@pytest.mark.ledger("S4-024", "S4-019")
def test_replan_moved_occurrence_keeps_its_new_table(sw, api):
    p = expect(api.replan(sw.mgr, "r_rep", {"table_id": "r_3", "from": iso("2027-06-24T18:00"),
                                            "to": iso("2027-06-24T21:00")}), 201)
    expect(api.apply(sw.mgr, "r_rep", p["plan_id"]), 201)
    moved = api.get_ok(sw.ada, sw.refs[1])["table_ids"]
    assert moved != ["r_3"]
    rev = expect(api.get_series(sw.ada, sw.sid), 200)["revision"]
    r = expect(api.amend(sw.ada, sw.sid, amend_body(rev, 1, "20:30")), 201)
    o1 = r["occurrences"][1]["reservation"]
    assert o1["table_ids"] == moved and o1["starts_at_local"] == "2027-06-24T20:30"
    assert r["occurrences"][1]["exception"] is False


@pytest.mark.slow
@pytest.mark.ledger("S4-025", "A-40", "A-03")
def test_amend_checks_old_accepted_cutoff(api):
    rest = {**tk.now_restaurant(rid="r_nowamend", cutoff=30), "manager_user_ids": ["u_mgr"]}
    w = tk.World(api, tk.fixture(users=(tk.ADA, MGR), restaurants=(rest,)))
    tok = w.ada
    start_local = tk.local_at(rest, tk.now_utc() + timedelta(minutes=30, seconds=25))
    boundary = tk.instant(start_local, rest["timezone"]) - timedelta(minutes=30)
    a = api.book(tok, rest["id"], rest["tables"][0]["id"], start_local, 2)
    s = expect(api.series(tok, {"anchor_reference": a["reference"], "count": 2, "interval_weeks": 1}), 201)
    assert tk.now_utc() < boundary, "setup too slow"
    tk.wait_until(boundary + timedelta(seconds=15))
    new_hm = (tk.local_dt(start_local, rest["timezone"]) + timedelta(minutes=5)).strftime("%H:%M")
    expect(api.amend(tok, s["series_id"], amend_body(1, 0, new_hm)), 409, "cutoff_passed")
    assert api.get_ok(tok, a["reference"])["starts_at_local"] == start_local
    r = expect(api.amend(tok, s["series_id"], amend_body(1, 1, new_hm)), 201)
    assert r["occurrences"][1]["reservation"]["starts_at_local"][11:] == new_hm
