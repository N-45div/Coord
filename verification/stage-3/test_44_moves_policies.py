"""Collective moves under policies and agreements (stage-3; ledger S3-048..S3-050, S3-049 series)."""
import pytest

import tk
from tk import POL, MGR, expect

D0 = "2027-06-17"
D1 = "2027-07-15"


@pytest.fixture
def mw(api):
    w = tk.World(api, tk.fixture(users=(tk.ADA, tk.BOB, MGR), restaurants=(POL,)))
    w.pol = tk.policy("2027-07-01")
    expect(api.publish(w.tok("u_mgr"), "r_pol", w.pol), 201)
    w.A = api.book(w.ada, "r_pol", "p_1", f"{D0}T19:00", 2)
    w.B = api.book(w.ada, "r_pol", "p_2", f"{D0}T19:00", 2)
    return w


def mv(ref, **kw):
    return {"reference": ref, **kw}


@pytest.mark.ledger("S3-048", "S3-049")
def test_real_moves_adopt_resulting_policy_and_add_one_revision_and_entry(mw, api):
    r = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], starts_at_local=f"{D1}T13:00"),
                                     mv(mw.B["reference"])]})
    expect(r, 201)
    a, b = r.json["reservations"]
    assert a["revision"] == 2 and b["revision"] == 1
    tk.assert_terms(a["accepted_terms"], tk.terms_of(mw.pol, 1))
    tk.assert_ts(a["ends_at"], f"{D1}T15:00:00+02:00")
    assert b == mw.B, "a no-op item keeps terms, revision and everything else"
    ea = api.entries(mw.ada, mw.A["reference"])
    assert [e["event"] for e in ea] == ["created", "changed"]
    assert ea[1]["changes"] == [{"field": "starts_at_local", "from": f"{D0}T19:00", "to": f"{D1}T13:00"}]
    assert ea[1]["revision"] == 2
    assert len(api.entries(mw.ada, mw.B["reference"])) == 1


@pytest.mark.ledger("S3-048", "S3-022")
def test_moves_validate_against_resulting_date_policy(mw, api):
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"], starts_at_local=f"{D1}T13:30")]}), 422, "not_on_slot_grid")
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"], starts_at_local=f"{D1}T13:00", party_size=4)]}),
           422, "party_exceeds_capacity")  # p_1 seats 3 under policy 1
    ok = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], starts_at_local=f"{D1}T13:00", party_size=3)]})
    expect(ok, 201)


@pytest.mark.ledger("S3-048", "S3-030", "A-29")
def test_per_move_expected_revision(mw, api):
    A, B = mw.A["reference"], mw.B["reference"]
    expect(api.moves(mw.ada, {"moves": [mv(A, party_size=1, expected_revision=2)]}), 409, "stale_revision")
    expect(api.moves(mw.ada, {"moves": [mv(A, party_size=1, expected_revision=0)]}), 422, "validation_failed")
    expect(api.moves(mw.ada, {"moves": [mv(A, party_size=1, expected_revision=True)]}), 422, "validation_failed")
    ok = api.moves(mw.ada, {"moves": [mv(A, party_size=1, expected_revision=1), mv(B, expected_revision=1)]})
    expect(ok, 201)
    assert [x["revision"] for x in ok.json["reservations"]] == [2, 1]
    expect(api.moves(mw.ada, {"moves": [mv(B, table_id="p_3", expected_revision=1),
                                        mv(A, party_size=2, expected_revision=1)]}), 409, "stale_revision")
    assert api.get_ok(mw.ada, B)["table_id"] == "p_2"


@pytest.mark.ledger("S3-050", "S1-102")
def test_failed_batch_changes_no_revision_history_or_terms(mw, api):
    api.book(mw.bob, "r_pol", "p_3", f"{D0}T19:30", 2)
    bad = {"moves": [mv(mw.A["reference"], table_id="p_2"), mv(mw.B["reference"], table_id="p_3")]}
    expect(api.moves(mw.ada, bad), 409, "table_unavailable")
    for o in (mw.A, mw.B):
        assert api.get_ok(mw.ada, o["reference"]) == o
        assert len(api.entries(mw.ada, o["reference"])) == 1


@pytest.mark.ledger("S3-050", "S1-104")
def test_batch_replay_changes_nothing(mw, api):
    key = tk.new_key()
    body = {"moves": [mv(mw.A["reference"], table_id="p_3")]}
    first = expect(api.moves(mw.ada, body, key=key), 201)
    expect(api.patch(mw.ada, mw.A["reference"], {"party_size": 1}), 200)
    again = api.moves(mw.ada, body, key=key)
    expect(again, 200)
    assert again.json == first
    cur = api.get_ok(mw.ada, mw.A["reference"])
    assert cur["revision"] == 3 and cur["party_size"] == 1
    assert len(api.entries(mw.ada, mw.A["reference"])) == 3


@pytest.mark.ledger("S3-049", "S3-043", "A-33")
def test_batch_touching_series_occurrences(mw, api):
    s = expect(api.series(mw.ada, {"anchor_reference": mw.A["reference"], "count": 3, "interval_weeks": 1}), 201)
    sid = s["series_id"]
    o1, o2 = s["occurrences"][1]["reference"], s["occurrences"][2]["reference"]
    # two occurrences of the same series changed in one batch, plus one no-op occurrence
    r = api.moves(mw.ada, {"moves": [mv(o1, table_id="p_3"), mv(o2, party_size=1), mv(mw.A["reference"])]})
    expect(r, 201)
    g = expect(api.get_series(mw.ada, sid), 200)
    assert g["revision"] == 2, "each affected series revision increases once per batch"
    assert [o["exception"] for o in g["occurrences"]] == [False, True, True]
    # a failed batch and a no-op batch change nothing
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"], party_size=9)]}), 422, "party_exceeds_capacity")
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"])]}), 201)
    g = expect(api.get_series(mw.ada, sid), 200)
    assert g["revision"] == 2 and g["occurrences"][0]["exception"] is False
