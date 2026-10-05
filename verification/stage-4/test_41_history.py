"""Reservation history and decisions (stage-3 "Reservation history", "Policies and accepted terms",
"Combined-table history"; ledger S3-007..S3-013, S3-032, S3-033, S3-047)."""
import pytest

import tk
from tk import POL, MGR, expect

D = "2027-06-17"
T19 = f"{D}T19:00"


@pytest.fixture
def hw(api):
    return tk.World(api, tk.fixture(users=(tk.ADA, tk.BOB, MGR), restaurants=(POL,)))


def ch(field, frm, to):
    return {"field": field, "from": frm, "to": to}


def check_entries(entries):
    assert [e["seq"] for e in entries] == list(range(1, len(entries) + 1)), "seq must be 1, 2, 3, ..."
    ats = [tk.parse_ts(e["at"]) for e in entries]
    assert ats == sorted(ats), "entries must be in at order"
    for e in entries:
        assert type(e["revision"]) is int and e["revision"] >= 1, e
        assert isinstance(e["accepted_terms"], dict) and tk.TERMS_KEYS <= set(e["accepted_terms"]), e


@pytest.mark.ledger("S3-007", "S3-008", "S3-009", "S3-013")
def test_created_entry(hw, api):
    r = api.book(hw.ada, "r_pol", "p_2", T19, 3)
    es = api.entries(hw.ada, r["reference"])
    check_entries(es)
    assert len(es) == 1
    e = es[0]
    assert e["event"] == "created" and e["revision"] == 1
    assert e["changes"] == [ch("table_id", None, "p_2"), ch("starts_at_local", None, T19), ch("party_size", None, 3)]
    tk.assert_terms(e["accepted_terms"], tk.terms0(POL))
    assert r["revision"] == 1
    tk.assert_terms(r["accepted_terms"], tk.terms0(POL))


@pytest.mark.ledger("S3-010", "S3-011", "S3-012", "S3-008", "S3-026", "S3-027")
def test_changed_noop_cancelled_and_replay(hw, api):
    key = tk.new_key()
    b = tk.body("r_pol", "p_2", T19, 3)
    r = expect(api.create(hw.ada, b, key=key), 201)
    ref = r["reference"]
    p = api.patch(hw.ada, ref, {"table_id": "p_3"})
    expect(p, 200)
    assert p.json["revision"] == 2
    p = api.patch(hw.ada, ref, {"starts_at_local": f"{D}T20:00", "party_size": 5, "table_id": "p_3"})
    expect(p, 200)
    assert p.json["revision"] == 3
    noop = api.patch(hw.ada, ref, {"party_size": 5, "table_id": "p_3"})
    expect(noop, 200)
    assert noop.json["revision"] == 3 and noop.json == p.json
    expect(api.create(hw.ada, b, key=key), 200)  # replay records nothing
    c = api.cancel(hw.ada, ref)
    expect(c, 200)
    assert c.json["revision"] == 4
    again = api.cancel(hw.ada, ref)
    expect(again, 200)
    assert again.json["revision"] == 4
    expect(api.patch(hw.ada, ref, {"party_size": 4}), 409, "reservation_cancelled")
    es = api.entries(hw.ada, ref)
    check_entries(es)
    assert [e["event"] for e in es] == ["created", "changed", "changed", "cancelled"]
    assert es[1]["changes"] == [ch("table_id", "p_2", "p_3")]
    assert es[2]["changes"] == [ch("starts_at_local", T19, f"{D}T20:00"), ch("party_size", 3, 5)]
    assert es[3]["changes"] == []
    assert [e["revision"] for e in es] == [1, 2, 3, 4]


@pytest.mark.ledger("S3-007", "S3-032", "S3-033")
def test_history_and_decision_owner_only_404_even_without_token(hw, api):
    r = api.book(hw.ada, "r_pol", "p_2", T19, 3)
    ref = r["reference"]
    for get in (api.history, api.decision):
        expect(get(hw.bob, ref), 404, "not_found")
        expect(get(hw.tok("u_mgr"), ref), 404, "not_found")  # managers gain no access
        expect(get(None, ref), 404, "not_found")
        expect(get("bogus-token", ref), 404, "not_found")
        expect(get(hw.ada, "ZZZZZZ99"), 404, "not_found")
    expect(api.get(hw.tok("u_mgr"), ref), 404, "not_found")


@pytest.mark.ledger("S3-032", "S3-007")
def test_decision_current_including_after_cancel(hw, api):
    r = api.book(hw.ada, "r_pol", "p_2", T19, 3)
    d = api.decision(hw.ada, r["reference"])
    expect(d, 200)
    assert d.json["reference"] == r["reference"] and d.json["revision"] == 1
    tk.assert_terms(d.json["accepted_terms"], tk.terms0(POL))
    expect(api.cancel(hw.ada, r["reference"]), 200)
    d = api.decision(hw.ada, r["reference"])
    expect(d, 200)
    assert d.json["revision"] == 2
    assert api.entries(hw.ada, r["reference"])[-1]["event"] == "cancelled"


@pytest.mark.ledger("S3-047", "S3-009", "S3-010", "S3-028")
def test_pair_history_uses_table_ids(hw, api):
    r = expect(api.create(hw.ada, {"restaurant_id": "r_pol", "table_ids": ["p_1", "p_2"], "starts_at_local": T19,
                                   "party_size": 5}), 201)
    ref = r["reference"]
    rev = api.patch(hw.ada, ref, {"table_ids": ["p_2", "p_1"]})  # reversed pair: same set, no amendment
    expect(rev, 200)
    assert rev.json["revision"] == 1 and rev.json["table_ids"] == ["p_1", "p_2"]
    expect(api.patch(hw.ada, ref, {"table_id": "p_3"}), 200)
    expect(api.patch(hw.ada, ref, {"table_ids": ["p_1", "p_2"]}), 200)
    expect(api.patch(hw.ada, ref, {"table_id": "p_2", "party_size": 4}), 200)
    expect(api.patch(hw.ada, ref, {"table_id": "p_3"}), 200)
    es = api.entries(hw.ada, ref)
    check_entries(es)
    assert es[0]["changes"] == [ch("table_ids", None, ["p_1", "p_2"]), ch("starts_at_local", None, T19),
                                ch("party_size", None, 5)]
    assert es[1]["changes"] == [ch("table_ids", ["p_1", "p_2"], ["p_3"])]
    assert es[2]["changes"] == [ch("table_ids", ["p_3"], ["p_1", "p_2"])]
    assert es[3]["changes"] == [ch("table_ids", ["p_1", "p_2"], ["p_2"]), ch("party_size", 5, 4)]
    assert es[4]["changes"] == [ch("table_id", "p_2", "p_3")]
    assert len(es) == 5


@pytest.mark.ledger("S3-013", "S3-025", "S3-027")
def test_entries_keep_their_terms_after_publication_and_amendment(hw, api):
    r = api.book(hw.ada, "r_pol", "p_2", T19, 3)
    pol = tk.policy("2027-07-01")
    expect(api.publish(hw.tok("u_mgr"), "r_pol", pol), 201)
    unchanged = api.get_ok(hw.ada, r["reference"])
    assert unchanged == r, "publishing a policy changed an existing booking"
    assert len(api.entries(hw.ada, r["reference"])) == 1
    p = api.patch(hw.ada, r["reference"], {"starts_at_local": "2027-07-15T13:00"})
    expect(p, 200)
    assert p.json["revision"] == 2
    tk.assert_terms(p.json["accepted_terms"], tk.terms_of(pol, 1))
    tk.assert_ts(p.json["ends_at"], "2027-07-15T15:00:00+02:00")
    es = api.entries(hw.ada, r["reference"])
    tk.assert_terms(es[0]["accepted_terms"], tk.terms0(POL))
    tk.assert_terms(es[1]["accepted_terms"], tk.terms_of(pol, 1))
    assert es[1]["revision"] == 2


@pytest.mark.ledger("S3-024", "A-43", "S2-032")
def test_seeded_bookings_revision_1_policy_0(api):
    seeds = [tk.seed("s1", "SEEDPOL1", "u_ada", "r_pol", "p_2", T19, 3),
             {**tk.seed("s2", "SEEDPOL2", "u_ada", "r_pol", "p_3", T19, 2), "status": "cancelled"}]
    w = tk.World(api, tk.fixture(users=(tk.ADA, MGR), restaurants=(POL,), reservations=seeds))
    a = api.get_ok(w.ada, "SEEDPOL1")
    assert a["revision"] == 1
    tk.assert_terms(a["accepted_terms"], tk.terms0(POL))
    es = api.entries(w.ada, "SEEDPOL1")
    assert [e["event"] for e in es] == ["created"]
    b = api.get_ok(w.ada, "SEEDPOL2")
    assert b["status"] == "cancelled" and b["revision"] == 1
    es = api.entries(w.ada, "SEEDPOL2")
    assert [(e["event"], e["revision"], e["changes"]) for e in es][1] == ("cancelled", 1, [])
    assert es[0]["event"] == "created" and es[0]["revision"] == 1
