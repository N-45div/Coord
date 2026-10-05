"""Recurring reservations (stage-3 "Recurring reservations"; ledger S3-034..S3-046, A-30, A-33)."""
import pytest

import tk
from tk import POL, MGR, DST_BER, expect

D = "2027-06-17"
T19 = f"{D}T19:00"
DATES4 = ["2027-06-17", "2027-06-24", "2027-07-01", "2027-07-08"]


@pytest.fixture
def sw(api):
    seeds = [tk.seed("sp", "PASTSER1", "u_ada", "r_pol", "p_3", "2025-06-19T19:00", 2)]
    w = tk.World(api, tk.fixture(users=(tk.ADA, tk.BOB, MGR), restaurants=(POL, DST_BER), reservations=seeds))
    w.anchor = api.book(w.ada, "r_pol", "p_2", T19, 3)
    return w


def sbody(ref, count=4, weeks=1, **extra):
    return {"anchor_reference": ref, "count": count, "interval_weeks": weeks, **extra}


def mine(api, tok):
    return {r["reference"]: r for r in api.list(tok)}


@pytest.mark.ledger("S3-040", "S3-036", "S3-037", "S3-041")
def test_adopt_weekly_series(sw, api):
    r = api.series(sw.ada, sbody(sw.anchor["reference"]))
    expect(r, 201)
    j = r.json
    assert isinstance(j["series_id"], str) and 1 <= len(j["series_id"]) <= 64
    assert j["revision"] == 1 and j["interval_weeks"] == 1
    occ = j["occurrences"]
    assert [o["index"] for o in occ] == [0, 1, 2, 3]
    assert all(o["exception"] is False for o in occ)
    assert occ[0]["reference"] == sw.anchor["reference"]
    assert occ[0]["reservation"] == sw.anchor, "occurrence 0 must be the unchanged anchor"
    refs = [o["reference"] for o in occ]
    assert len(set(refs)) == 4
    for o, d in zip(occ, DATES4):
        res = o["reservation"]
        assert res["reference"] == o["reference"]
        tk.assert_res(res, POL, "p_2", f"{d}T19:00", 3, "confirmed")
        assert res["revision"] == 1
    listed = mine(api, sw.ada)
    assert set(refs) <= set(listed)
    assert "p_2" not in api.free_tables("r_pol", "2027-07-01T19:00")
    for o in occ[1:]:
        es = api.entries(sw.ada, o["reference"])
        assert [e["event"] for e in es] == ["created"]
    assert len(api.entries(sw.ada, sw.anchor["reference"])) == 1
    assert api.get_ok(sw.ada, sw.anchor["reference"]) == sw.anchor


@pytest.mark.ledger("S3-037")
def test_interval_and_pair_selection(sw, api):
    pair = expect(api.create(sw.ada, {"restaurant_id": "r_pol", "table_ids": ["p_2", "p_1"],
                                      "starts_at_local": f"{D}T21:30", "party_size": 5}), 201)
    r = api.series(sw.ada, sbody(pair["reference"], count=3, weeks=2))
    expect(r, 201)
    dates = [o["reservation"]["starts_at_local"] for o in r.json["occurrences"]]
    assert dates == ["2027-06-17T21:30", "2027-07-01T21:30", "2027-07-15T21:30"]
    for o in r.json["occurrences"]:
        assert o["reservation"]["table_ids"] == ["p_1", "p_2"] and o["reservation"]["party_size"] == 5


@pytest.mark.ledger("S3-038", "S3-022", "S3-023")
def test_each_occurrence_selects_its_own_policy(sw, api):
    pol = tk.policy("2027-07-01")  # 60-minute grid from 12:00, 120-minute duration, 12:00-22:00
    expect(api.publish(sw.tok("u_mgr"), "r_pol", pol), 201)
    r = api.series(sw.ada, sbody(sw.anchor["reference"]))
    expect(r, 201)
    occ = r.json["occurrences"]
    for o in occ[:2]:
        tk.assert_terms(o["reservation"]["accepted_terms"], tk.terms0(POL))
    for o, d in zip(occ[2:], DATES4[2:]):
        tk.assert_terms(o["reservation"]["accepted_terms"], tk.terms_of(pol, 1))
        tk.assert_ts(o["reservation"]["ends_at"], f"{d}T21:00:00+02:00")


@pytest.mark.ledger("S3-038", "S3-039", "S1-043")
def test_occupancy_conflict_rejects_everything(sw, api):
    api.book(sw.bob, "r_pol", "p_2", "2027-07-01T19:30", 2)
    before = mine(api, sw.ada)
    key = tk.new_key()
    expect(api.series(sw.ada, sbody(sw.anchor["reference"]), key=key), 409, "table_unavailable")
    assert mine(api, sw.ada) == before
    assert "p_2" in api.free_tables("r_pol", "2027-06-24T19:00")
    ok = api.series(sw.ada, sbody(sw.anchor["reference"], count=2), key=key)  # failed key reusable
    expect(ok, 201)
    assert len(ok.json["occurrences"]) == 2


@pytest.mark.ledger("S3-039", "A-30")
def test_first_failing_occurrence_in_index_order_decides(sw, api):
    m = sw.tok("u_mgr")
    api.book(sw.bob, "r_pol", "p_2", "2027-06-24T19:00", 2)                     # occurrence 1: occupied
    early = [{"weekday": d, "opens": "12:00", "closes": "18:00"} for d in tk.ALL_DAYS]
    expect(api.publish(m, "r_pol", tk.policy("2027-07-01", hours=early)), 201)  # occurrence 2: closed at 19:00
    expect(api.series(sw.ada, sbody(sw.anchor["reference"])), 409, "table_unavailable")


@pytest.mark.ledger("S3-039", "A-30")
def test_first_failing_occurrence_hours_before_later_conflict(sw, api):
    m = sw.tok("u_mgr")
    early = [{"weekday": d, "opens": "12:00", "closes": "18:00"} for d in tk.ALL_DAYS]
    expect(api.publish(m, "r_pol", tk.policy("2027-06-20", hours=early)), 201)  # occurrence 1: closed
    expect(api.publish(m, "r_pol", tk.policy("2027-06-28")), 201)               # occurrence 2+: open 12-22
    api.book(sw.bob, "r_pol", "p_2", "2027-07-01T19:00", 2)                     # occurrence 2: occupied
    expect(api.series(sw.ada, sbody(sw.anchor["reference"])), 422, "outside_opening_hours")
    assert len(mine(api, sw.ada)) == 2  # anchor + seeded past booking only


@pytest.mark.ledger("S3-038")
def test_dst_gap_rejects_and_fall_back_resolves_first(sw, api):
    a = api.book(sw.ada, "r_dst_ber", "d_1", "2027-03-14T02:30", 2)
    expect(api.series(sw.ada, sbody(a["reference"], count=2, weeks=2)), 422, "invalid_local_time")
    b = api.book(sw.ada, "r_dst_ber", "d_2", "2027-10-17T02:30", 2)
    r = api.series(sw.ada, sbody(b["reference"], count=3, weeks=1))
    expect(r, 201)
    last = r.json["occurrences"][2]["reservation"]
    assert last["starts_at_local"] == "2027-10-31T02:30"
    tk.assert_ts(last["starts_at"], "2027-10-31T02:30:00+02:00")
    tk.assert_ts(last["ends_at"], "2027-10-31T03:00:00+01:00")


@pytest.mark.ledger("S3-034", "A-28", "A-30")
@pytest.mark.parametrize("bad", [
    {"count": 1}, {"count": 13}, {"count": True}, {"count": "3"}, {"count": 2.5}, {"count": None},
    {"interval_weeks": 0}, {"interval_weeks": 5}, {"interval_weeks": True}, {"interval_weeks": "1"},
    {"anchor_reference": 123}, {"anchor_reference": None}, "MISSING_COUNT", "MISSING_WEEKS", "MISSING_ANCHOR",
], ids=lambda b: b if isinstance(b, str) else "-".join(f"{k}={v!r}" for k, v in b.items()))
def test_series_body_validation_422(sw, api, bad):
    b = sbody(sw.anchor["reference"])
    if isinstance(bad, str):
        del b[{"MISSING_COUNT": "count", "MISSING_WEEKS": "interval_weeks", "MISSING_ANCHOR": "anchor_reference"}[bad]]
    else:
        b.update(bad)
    expect(api.series(sw.ada, b), 422, "validation_failed")
    assert len(mine(api, sw.ada)) == 2


@pytest.mark.ledger("S3-034", "A-30", "S1-037", "S1-025")
def test_series_request_level_errors(sw, api):
    b = sbody(sw.anchor["reference"])
    expect(api.series(None, b), 401, "unauthenticated")
    expect(api.series(sw.ada, raw="not json"), 400, "malformed_request")
    expect(api.series(sw.ada, raw="[1]"), 400, "malformed_request")
    expect(api.series(sw.ada, b, key=None), 400, "missing_idempotency_key")
    expect(api.series(sw.ada, b, key="k" * 256), 422, "validation_failed")
    expect(api.series(sw.ada, {**b, "count": 0, "anchor_reference": "ZZZZZZ99"}), 422, "validation_failed")


@pytest.mark.ledger("S3-035", "A-30")
def test_anchor_rules(sw, api):
    expect(api.series(sw.ada, sbody("ZZZZZZ99")), 404, "not_found")
    bobs = api.book(sw.bob, "r_pol", "p_3", T19, 2)
    expect(api.series(sw.ada, sbody(bobs["reference"])), 404, "not_found")
    expect(api.series(sw.ada, sbody("PASTSER1")), 409, "cutoff_passed")
    c = api.book(sw.ada, "r_pol", "p_1", T19, 2)
    expect(api.cancel(sw.ada, c["reference"]), 200)
    expect(api.series(sw.ada, sbody(c["reference"])), 409, "reservation_cancelled")
    s = expect(api.series(sw.ada, sbody(sw.anchor["reference"], count=3)), 201)
    expect(api.series(sw.ada, sbody(sw.anchor["reference"], count=2)), 409, "already_in_series")
    occ1 = s["occurrences"][1]["reference"]
    expect(api.series(sw.ada, sbody(occ1, count=2)), 409, "already_in_series")
    expect(api.cancel(sw.ada, occ1), 200)
    expect(api.series(sw.ada, sbody(occ1, count=2)), 409, "reservation_cancelled")  # A-30: cancelled first


@pytest.mark.ledger("S3-042")
def test_get_series_owner_only(sw, api):
    s = expect(api.series(sw.ada, sbody(sw.anchor["reference"], count=2)), 201)
    g = api.get_series(sw.ada, s["series_id"])
    expect(g, 200)
    assert g.json == s
    expect(api.get_series(sw.bob, s["series_id"]), 404, "not_found")
    expect(api.get_series(None, s["series_id"]), 404, "not_found")
    expect(api.get_series(sw.ada, "no-such-series"), 404, "not_found")


@pytest.mark.ledger("S3-043", "S3-044", "S3-045", "A-33")
def test_exceptions_revisions_cancel_and_replay(sw, api):
    key = tk.new_key()
    b = sbody(sw.anchor["reference"])
    s = expect(api.series(sw.ada, b, key=key), 201)
    sid = s["series_id"]
    o1, o2, o3 = (s["occurrences"][i]["reference"] for i in (1, 2, 3))

    def cur():
        return expect(api.get_series(sw.ada, sid), 200)
    expect(api.patch(sw.ada, o1, {"party_size": 3}), 200)          # no-op
    expect(api.patch(sw.ada, o1, {"party_size": 9}), 422, "party_exceeds_capacity")  # failure
    g = cur()
    assert g["revision"] == 1 and all(o["exception"] is False for o in g["occurrences"])
    expect(api.patch(sw.ada, o1, {"table_id": "p_3"}), 200)        # real change
    g = cur()
    assert g["revision"] == 2
    assert [o["exception"] for o in g["occurrences"]] == [False, True, False, False]
    assert g["occurrences"][1]["reservation"]["table_id"] == "p_3"
    assert [o["reference"] for o in g["occurrences"]] == [o["reference"] for o in s["occurrences"]]
    expect(api.cancel(sw.ada, o2), 200)
    g = cur()
    assert g["revision"] == 3 and g["occurrences"][2]["exception"] is False
    assert g["occurrences"][2]["reservation"]["status"] == "cancelled"
    expect(api.cancel(sw.ada, o2), 200)                            # repeated cancel: nothing
    assert cur()["revision"] == 3
    expect(api.cancel(sw.ada, sw.anchor["reference"]), 200)       # anchor cancel keeps siblings
    g = cur()
    assert g["revision"] == 4
    assert g["occurrences"][3]["reservation"]["status"] == "confirmed"
    assert api.get_ok(sw.ada, o3)["status"] == "confirmed"
    expect(api.patch(sw.ada, o1, {"party_size": 2}), 200)         # stays an exception
    g = cur()
    assert g["revision"] == 5 and g["occurrences"][1]["exception"] is True
    rp = api.series(sw.ada, b, key=key)
    expect(rp, 200)
    assert rp.json == s, "series replay must return the original response"
    assert cur()["revision"] == 5


@pytest.mark.ledger("S3-051", "S3-045", "S1-088")
def test_series_survives_export_import(sw, api):
    key = tk.new_key()
    b = sbody(sw.anchor["reference"], count=3)
    s = expect(api.series(sw.ada, b, key=key), 201)
    expect(api.patch(sw.ada, s["occurrences"][1]["reference"], {"party_size": 2}), 200)
    snap = expect(api.get_series(sw.ada, s["series_id"]), 200)
    hist = api.entries(sw.ada, s["occurrences"][1]["reference"])
    e = api.export()
    api.reset(tk.fixture())
    expect(api.import_(e), 204)
    assert expect(api.get_series(sw.ada, s["series_id"]), 200) == snap
    assert api.entries(sw.ada, s["occurrences"][1]["reference"]) == hist
    rp = api.series(sw.ada, b, key=key)
    expect(rp, 200)
    assert rp.json == s
    expect(api.patch(sw.ada, s["occurrences"][2]["reference"], {"party_size": 2}), 200)
    assert expect(api.get_series(sw.ada, s["series_id"]), 200)["revision"] == snap["revision"] + 1
