"""Policies, accepted terms, revisions (stage-3 "Policies and accepted terms"; ledger S3-014..S3-033,
A-27..A-29, A-34)."""
from datetime import timedelta

import pytest

import tk
from tk import POL, POL2, MGR, expect

D0 = "2027-06-17"   # policy 0 date
D1 = "2027-07-15"   # covered by a policy effective 2027-07-01


@pytest.fixture
def pw(api):
    return tk.World(api, tk.fixture(users=(tk.ADA, tk.BOB, MGR), restaurants=(POL, POL2)))


def pols(api, rid):
    r = api.policies(rid)
    expect(r, 200)
    return r.json["policies"]


# ---- publishing permissions and idempotency ----------------------------------------------

@pytest.mark.ledger("S3-014", "S3-015", "A-27")
def test_publish_permissions(pw, api):
    p = tk.policy("2027-07-01")
    expect(api.publish(None, "r_pol", p), 401, "unauthenticated")
    expect(api.publish(pw.ada, "r_pol", p), 403, "forbidden")
    expect(api.publish(pw.tok("u_mgr"), "r_nowhere", p), 404, "not_found")
    expect(api.publish(pw.ada, "r_nowhere", p), 404, "not_found")  # A-27: 404 before 403
    assert pols(api, "r_pol") == []


@pytest.mark.ledger("S3-017", "S3-019", "A-34")
def test_publish_versions_per_restaurant_and_list(pw, api):
    m = pw.tok("u_mgr")
    a, b = tk.policy("2027-07-01"), tk.policy("2027-06-01", slot=30, dur=90, cut=0)
    ra = api.publish(m, "r_pol", a)
    expect(ra, 201)
    assert ra.json["policy_version"] == 1
    for k, v in a.items():
        assert ra.json[k] == v, k
    rb = api.publish(m, "r_pol", b)
    expect(rb, 201)
    assert rb.json["policy_version"] == 2
    rc = api.publish(m, "r_pol2", a)
    expect(rc, 201)
    assert rc.json["policy_version"] == 1, "versions are per restaurant"
    listed = pols(api, "r_pol")
    assert [x["policy_version"] for x in listed] == [1, 2]
    assert listed[0] == ra.json and listed[1] == rb.json
    assert [x["policy_version"] for x in pols(api, "r_pol2")] == [1]
    expect(api.policies("r_nowhere"), 404, "not_found")


@pytest.mark.ledger("S3-015", "S3-017", "S1-037", "S1-025", "S1-039", "S1-040", "S1-043")
def test_publish_idempotency(pw, api):
    m = pw.tok("u_mgr")
    p = tk.policy("2027-07-01")
    expect(api.publish(m, "r_pol", p, key=None), 400, "missing_idempotency_key")
    expect(api.publish(m, "r_pol", p, key="k" * 256), 422, "validation_failed")
    key = tk.new_key()
    first = expect(api.publish(m, "r_pol", p, key=key), 201)
    again = api.publish(m, "r_pol", p, key=key)
    expect(again, 200)
    assert again.json == first
    expect(api.publish(m, "r_pol", {**p, "slot_minutes": 15}, key=key), 409, "idempotency_key_reuse")
    expect(api.publish(m, "r_pol", {**p, "slot_minutes": 0}, key=key), 409, "idempotency_key_reuse")
    k2 = tk.new_key()
    expect(api.publish(m, "r_pol", {**p, "slot_minutes": 0}, key=k2), 422, "validation_failed")
    nxt = api.publish(m, "r_pol", tk.policy("2027-08-01"), key=k2)  # failed key reusable
    expect(nxt, 201)
    assert nxt.json["policy_version"] == 2, "replays and failures must not allocate versions"


def _bad_policies():
    p = tk.policy("2027-07-01")
    cases = {}
    for k in p:
        cases[f"missing-{k}"] = {kk: vv for kk, vv in p.items() if kk != k}
    cases.update({
        "date-impossible": {**p, "effective_from": "2027-02-30"},
        "date-format": {**p, "effective_from": "2027-7-1"},
        "date-int": {**p, "effective_from": 20270701},
        "slot-0": {**p, "slot_minutes": 0}, "slot-1441": {**p, "slot_minutes": 1441},
        "slot-bool": {**p, "slot_minutes": True}, "slot-str": {**p, "slot_minutes": "30"},
        "slot-frac": {**p, "slot_minutes": 30.5},
        "dur-0": {**p, "reservation_duration_minutes": 0}, "dur-1441": {**p, "reservation_duration_minutes": 1441},
        "cut-neg": {**p, "cancellation_cutoff_minutes": -1}, "cut-10081": {**p, "cancellation_cutoff_minutes": 10081},
        "cut-bool": {**p, "cancellation_cutoff_minutes": False},
        "hours-dup-weekday": {**p, "opening_hours": [{"weekday": "mon", "opens": "12:00", "closes": "14:00"},
                                                     {"weekday": "mon", "opens": "18:00", "closes": "22:00"}]},
        "hours-closes-before-opens": {**p, "opening_hours": [{"weekday": "mon", "opens": "22:00", "closes": "12:00"}]},
        "hours-equal": {**p, "opening_hours": [{"weekday": "mon", "opens": "12:00", "closes": "12:00"}]},
        "hours-bad-time": {**p, "opening_hours": [{"weekday": "mon", "opens": "25:00", "closes": "26:00"}]},
        "hours-bad-weekday": {**p, "opening_hours": [{"weekday": "monday", "opens": "12:00", "closes": "14:00"}]},
        "hours-not-list": {**p, "opening_hours": {"mon": ["12:00", "14:00"]}},
        "caps-missing-table": {**p, "capacities": {"p_1": 2, "p_2": 4}},
        "caps-extra-table": {**p, "capacities": {"p_1": 2, "p_2": 4, "p_3": 6, "zz": 2}},
        "caps-0": {**p, "capacities": {"p_1": 0, "p_2": 4, "p_3": 6}},
        "caps-101": {**p, "capacities": {"p_1": 101, "p_2": 4, "p_3": 6}},
        "caps-bool": {**p, "capacities": {"p_1": True, "p_2": 4, "p_3": 6}},
        "caps-str": {**p, "capacities": {"p_1": "2", "p_2": 4, "p_3": 6}},
        "caps-list": {**p, "capacities": [2, 4, 6]},
    })
    return cases


BAD = _bad_policies()


@pytest.mark.ledger("S3-016", "A-28")
@pytest.mark.parametrize("case", sorted(BAD))
def test_invalid_policy_422_no_version(pw, api, case):
    m = pw.tok("u_mgr")
    expect(api.publish(m, "r_pol", BAD[case]), 422, "validation_failed")
    assert pols(api, "r_pol") == []
    ok = api.publish(m, "r_pol", tk.policy("2027-07-01"))
    expect(ok, 201)
    assert ok.json["policy_version"] == 1


@pytest.mark.ledger("S3-016", "S1-011")
def test_policy_boundaries_and_unknown_fields(pw, api):
    m = pw.tok("u_mgr")
    p = tk.policy("2027-07-01", slot=1, dur=1440, cut=0, caps={"p_1": 1, "p_2": 100, "p_3": 50})
    r = api.publish(m, "r_pol", {**p, "note": "summer", "timezone": "Asia/Tokyo"})
    expect(r, 201)
    expect(api.publish(m, "r_pol", tk.policy("2027-07-02", slot=1440, dur=1, cut=10080)), 201)
    d = api.call("GET", "/restaurants/r_pol").json
    assert d["timezone"] == "Europe/Berlin"


@pytest.mark.ledger("S3-020", "S3-018")
def test_restaurant_detail_keeps_fixture_configuration(pw, api):
    before = api.call("GET", "/restaurants/r_pol").json
    expect(api.publish(pw.tok("u_mgr"), "r_pol", tk.policy("2020-01-01")), 201)
    assert api.call("GET", "/restaurants/r_pol").json == before


# ---- selection ---------------------------------------------------------------------------

@pytest.mark.ledger("S3-021", "S3-022", "S3-023")
def test_policy_selection_by_local_date(pw, api):
    m = pw.tok("u_mgr")
    a = tk.policy("2027-07-01", slot=60, dur=120)                         # v1
    b = tk.policy("2027-06-01", slot=30, dur=60, hours=[{"weekday": d, "opens": "17:00", "closes": "21:00"}
                                                        for d in tk.ALL_DAYS])  # v2, earlier date
    c = tk.policy("2027-07-01", slot=45, dur=45, hours=[{"weekday": d, "opens": "11:00", "closes": "14:00"}
                                                        for d in tk.ALL_DAYS])  # v3, same date as v1
    for p in (a, b, c):
        expect(api.publish(m, "r_pol", p), 201)

    def starts(date):
        return [s["starts_at_local"][11:] for s in api.slots("r_pol", date, 2)]
    assert starts("2027-05-20") == ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]  # v0
    assert starts("2027-06-17") == ["17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00"]  # v2
    assert starts("2027-07-15") == ["11:00", "11:45", "12:30", "13:15"]  # v3 supersedes v1 (tie -> higher)
    r = api.book(pw.ada, "r_pol", "p_2", "2027-07-15T11:45", 2)
    tk.assert_terms(r["accepted_terms"], tk.terms_of(c, 3))
    tk.assert_ts(r["ends_at"], "2027-07-15T12:30:00+02:00")
    expect(api.create(pw.ada, tk.body("r_pol", "p_2", "2027-07-15T12:00", 2)), 422, "not_on_slot_grid")
    expect(api.create(pw.ada, tk.body("r_pol", "p_2", "2027-06-17T21:00", 2)), 422, "outside_opening_hours")
    q = api.book(pw.ada, "r_pol", "p_2", "2027-06-17T20:00", 2)
    tk.assert_terms(q["accepted_terms"], tk.terms_of(b, 2))


@pytest.mark.ledger("S3-022", "S3-047", "S2-031")
def test_policy_capacity_applies_to_bookings_and_pairs(pw, api):
    expect(api.publish(pw.tok("u_mgr"), "r_pol", tk.policy("2027-07-01", caps={"p_1": 5, "p_2": 1, "p_3": 8})), 201)
    expect(api.create(pw.ada, tk.body("r_pol", "p_1", f"{D0}T19:00", 3)), 422, "party_exceeds_capacity")
    api.book(pw.ada, "r_pol", "p_1", f"{D1}T13:00", 5)
    expect(api.create(pw.ada, tk.body("r_pol", "p_2", f"{D1}T13:00", 2)), 422, "party_exceeds_capacity")
    s = [x for x in api.slots("r_pol", D1, 6) if x["starts_at_local"] == f"{D1}T15:00"][0]
    assert {"table_ids": ["p_1", "p_2"], "capacity": 6} in s["available_options"]
    pair = api.create(pw.ada, {"restaurant_id": "r_pol", "table_ids": ["p_1", "p_2"],
                               "starts_at_local": f"{D1}T15:00", "party_size": 6})
    expect(pair, 201)
    assert pair.json["accepted_terms"]["capacities"] == {"p_1": 5, "p_2": 1, "p_3": 8}


@pytest.mark.ledger("S3-025", "S3-021")
def test_publication_never_changes_existing_bookings(pw, api):
    r = api.book(pw.ada, "r_pol", "p_3", f"{D1}T19:00", 6)
    ends = r["ends_at"]
    expect(api.publish(pw.tok("u_mgr"), "r_pol", tk.policy("2027-01-01", dur=30, caps={"p_1": 1, "p_2": 1, "p_3": 1})), 201)
    now = api.get_ok(pw.ada, r["reference"])
    assert now == r and now["ends_at"] == ends
    assert len(api.entries(pw.ada, r["reference"])) == 1
    noop = api.patch(pw.ada, r["reference"], {"party_size": 6})  # no-op keeps old terms even though they no longer validate
    expect(noop, 200)
    assert noop.json == r


# ---- amendments, revisions, expected_revision ---------------------------------------------

@pytest.mark.ledger("S3-027", "S3-029", "S3-022")
def test_amendment_validates_against_resulting_date_policy(pw, api):
    pol = tk.policy("2027-07-01")
    expect(api.publish(pw.tok("u_mgr"), "r_pol", pol), 201)
    r = api.book(pw.ada, "r_pol", "p_2", f"{D0}T19:00", 3)
    expect(api.patch(pw.ada, r["reference"], {"starts_at_local": f"{D1}T19:30"}), 422, "not_on_slot_grid")
    expect(api.patch(pw.ada, r["reference"], {"starts_at_local": f"{D1}T21:00"}), 422, "outside_opening_hours")
    assert api.get_ok(pw.ada, r["reference"]) == r
    assert len(api.entries(pw.ada, r["reference"])) == 1
    ok = api.patch(pw.ada, r["reference"], {"starts_at_local": f"{D1}T20:00", "table_id": "p_1"})
    expect(ok, 200)
    assert ok.json["revision"] == 2
    tk.assert_terms(ok.json["accepted_terms"], tk.terms_of(pol, 1))
    tk.assert_ts(ok.json["ends_at"], f"{D1}T22:00:00+02:00")
    back = api.patch(pw.ada, r["reference"], {"starts_at_local": f"{D0}T21:30", "table_id": "p_2"})
    expect(back, 200)
    assert back.json["revision"] == 3
    tk.assert_terms(back.json["accepted_terms"], tk.terms0(POL))


@pytest.mark.ledger("S3-030", "A-29")
@pytest.mark.parametrize("value", [0, -1, True, "1", 1.5, None, [1]], ids=["zero", "neg", "bool", "str", "frac", "null", "list"])
def test_expected_revision_invalid_422(pw, api, value):
    r = api.book(pw.ada, "r_pol", "p_2", f"{D0}T19:00", 3)
    expect(api.patch(pw.ada, r["reference"], {"party_size": 2, "expected_revision": value}), 422, "validation_failed")
    assert api.get_ok(pw.ada, r["reference"]) == r


@pytest.mark.ledger("S3-030", "A-29")
def test_expected_revision_stale_and_current(pw, api):
    r = api.book(pw.ada, "r_pol", "p_2", f"{D0}T19:00", 3)
    ref = r["reference"]
    expect(api.patch(pw.ada, ref, {"party_size": 2, "expected_revision": 2}), 409, "stale_revision")
    ok = api.patch(pw.ada, ref, {"party_size": 2, "expected_revision": 1})
    expect(ok, 200)
    assert ok.json["revision"] == 2
    expect(api.patch(pw.ada, ref, {"party_size": 1, "expected_revision": 1}), 409, "stale_revision")
    # stale_revision is checked before cutoff, cancellation and field validation (A-29)
    expect(api.patch(pw.ada, ref, {"party_size": 0, "expected_revision": 1}), 409, "stale_revision")
    expect(api.cancel(pw.ada, ref), 200)
    expect(api.patch(pw.ada, ref, {"party_size": 1, "expected_revision": 1}), 409, "stale_revision")
    expect(api.patch(pw.ada, ref, {"party_size": 1, "expected_revision": 3}), 409, "reservation_cancelled")
    seeds = [tk.seed("sp", "PASTPOL1", "u_ada", "r_pol", "p_3", "2025-06-19T19:00", 2)]
    w = tk.World(api, tk.fixture(users=(tk.ADA, MGR), restaurants=(POL,), reservations=seeds))
    expect(api.patch(w.ada, "PASTPOL1", {"party_size": 1, "expected_revision": 2}), 409, "stale_revision")
    expect(api.patch(w.ada, "PASTPOL1", {"party_size": 1, "expected_revision": 1}), 409, "cutoff_passed")
    expect(api.patch(w.ada, "PASTPOL1", {"table_id": 5, "expected_revision": 0}), 400, "malformed_request")


@pytest.mark.ledger("S3-031", "S1-080")
def test_concurrent_amendments_same_expected_revision(pw, api):
    r = api.book(pw.ada, "r_pol", "p_3", f"{D0}T19:00", 2)
    ref = r["reference"]
    res = tk.parallel([(lambda a, n=n: a.patch(pw.ada, ref, {"party_size": n, "expected_revision": 1}))
                       for n in (1, 3, 4, 5, 6) * 3])
    tk.assert_all_responses(res)
    ok = [x for x in res if x.status == 200]
    assert len(ok) == 1, [x.status for x in res]
    for x in res:
        if x.status != 200:
            expect(x, 409, "stale_revision")
    cur = api.get_ok(pw.ada, ref)
    assert cur["revision"] == 2 and cur["party_size"] == ok[0].json["party_size"]
    assert len(api.entries(pw.ada, ref)) == 2


@pytest.mark.ledger("S3-024", "S1-044")
def test_replay_keeps_original_revision_and_terms(pw, api):
    key = tk.new_key()
    b = tk.body("r_pol", "p_2", f"{D0}T19:00", 3)
    first = expect(api.create(pw.ada, b, key=key), 201)
    expect(api.patch(pw.ada, first["reference"], {"party_size": 2}), 200)
    again = api.create(pw.ada, b, key=key)
    expect(again, 200)
    assert again.json == first and again.json["revision"] == 1
    assert len(api.entries(pw.ada, first["reference"])) == 2


# ---- cutoff against accepted terms (real clock) --------------------------------------------

@pytest.mark.ledger("S3-026", "S3-027", "S3-028")
def test_cancel_and_amend_use_accepted_cutoff(api):
    rest = {**tk.now_restaurant(rid="r_nowpol", cutoff=120), "manager_user_ids": ["u_mgr"]}
    w = tk.World(api, tk.fixture(users=(tk.ADA, MGR), restaurants=(rest,)))
    tids = [t["id"] for t in rest["tables"]]
    now = tk.now_utc()
    inside = api.book(w.ada, rest["id"], tids[0], tk.local_at(rest, now + timedelta(minutes=60)))
    today = inside["starts_at_local"][:10]
    caps = {t: 6 for t in tids}
    loose = {"effective_from": today, "slot_minutes": 1, "reservation_duration_minutes": 30,
             "cancellation_cutoff_minutes": 0,
             "opening_hours": [{"weekday": d, "opens": "00:00", "closes": "23:59"} for d in tk.ALL_DAYS],
             "capacities": caps}
    expect(api.publish(w.tok("u_mgr"), rest["id"], loose), 201)
    # the booking accepted a 120-minute cutoff; the new 0-minute policy does not loosen it
    expect(api.cancel(w.ada, inside["reference"]), 409, "cutoff_passed")
    expect(api.patch(w.ada, inside["reference"], {"party_size": 3}), 409, "cutoff_passed")
    expect(api.patch(w.ada, inside["reference"], {"party_size": inside["party_size"]}), 409, "cutoff_passed")  # no-op too
    later = api.book(w.ada, rest["id"], tids[1], tk.local_at(rest, now + timedelta(minutes=60)))
    tk.assert_terms(later["accepted_terms"], tk.terms_of(loose, 1))
    expect(api.cancel(w.ada, later["reference"]), 200)  # its accepted cutoff is 0
