"""Cancellation/amendment cutoff against the service's real clock (spec §8, ledger A-03, A-05).

Bookings are placed relative to the real current time in a restaurant whose zone keeps
the test window inside one local day. Margins of >= 15 s absorb host/container clock skew.
"""
from datetime import timedelta

import pytest

import tk
from tk import PAST_THU, body, expect


@pytest.mark.ledger("S1-018", "S1-072", "S1-076", "S1-055")
def test_past_booking_allowed_but_not_cancellable_or_amendable(w, api):
    r = api.create(w.ada, body("r_anker", "t_1", f"{PAST_THU}T19:00", 2))
    expect(r, 201)
    tk.assert_res(r.json, tk.ANKER, "t_1", f"{PAST_THU}T19:00", 2, "confirmed")
    ref = r.json["reference"]
    expect(api.cancel(w.ada, ref), 409, "cutoff_passed")
    expect(api.patch(w.ada, ref, {"party_size": 1}), 409, "cutoff_passed")
    cur = api.get_ok(w.ada, ref)
    assert cur["status"] == "confirmed" and cur["party_size"] == 2
    assert "t_1" not in api.free_tables("r_anker", f"{PAST_THU}T19:00")


@pytest.mark.ledger("S1-015", "S1-072")
def test_seeded_past_booking_cutoff(api):
    fx = tk.fixture(reservations=[tk.seed("rs1", "OLDBK1", "u_ada", "r_anker", "t_2", f"{PAST_THU}T18:00", 2)])
    w = tk.World(api, fx)
    expect(api.cancel(w.ada, "OLDBK1"), 409, "cutoff_passed")
    assert api.get_ok(w.ada, "OLDBK1")["status"] == "confirmed"


@pytest.mark.ledger("S1-072", "S1-076", "S1-070", "S1-074", "A-03")
def test_cutoff_window_relative_to_now(api):
    rest = tk.now_restaurant(cutoff=120)
    w = tk.World(api, tk.fixture(restaurants=(rest,)))
    tok = w.ada
    now = tk.now_utc()
    tids = [t["id"] for t in rest["tables"]]
    inside = api.book(tok, rest["id"], tids[0], tk.local_at(rest, now + timedelta(minutes=60)))
    outside = api.book(tok, rest["id"], tids[1], tk.local_at(rest, now + timedelta(minutes=180)))
    mover = api.book(tok, rest["id"], tids[2], tk.local_at(rest, now + timedelta(minutes=170)))
    # inside the cutoff: no cancel, no change
    expect(api.cancel(tok, inside["reference"]), 409, "cutoff_passed")
    expect(api.patch(tok, inside["reference"], {"party_size": 3}), 409, "cutoff_passed")
    expect(api.moves(tok, {"moves": [{"reference": inside["reference"], "party_size": 3}]}), 409, "cutoff_passed")
    assert api.get_ok(tok, inside["reference"])["status"] == "confirmed"
    # outside: allowed
    c = api.cancel(tok, outside["reference"])
    expect(c, 200)
    tk.assert_res(c.json, rest, tids[1], outside["starts_at_local"], 2, "cancelled")
    # cutoff is measured against the CURRENT start: moving into the window is allowed ...
    target = tk.local_at(rest, now + timedelta(minutes=45))
    p = api.patch(tok, mover["reference"], {"starts_at_local": target})
    expect(p, 200)
    assert p.json["starts_at_local"] == target
    # ... and afterwards the booking is inside its cutoff
    expect(api.patch(tok, mover["reference"], {"party_size": 3}), 409, "cutoff_passed")
    expect(api.cancel(tok, mover["reference"]), 409, "cutoff_passed")


@pytest.mark.ledger("S1-072", "S1-018")
def test_zero_cutoff_allows_until_start(api):
    rest = tk.now_restaurant(cutoff=0)
    w = tk.World(api, tk.fixture(restaurants=(rest,)))
    now = tk.now_utc()
    soon = api.book(w.ada, rest["id"], rest["tables"][0]["id"], tk.local_at(rest, now + timedelta(minutes=3)))
    started = api.book(w.ada, rest["id"], rest["tables"][1]["id"], tk.local_at(rest, now - timedelta(minutes=5)))
    expect(api.patch(w.ada, soon["reference"], {"party_size": 4}), 200)
    expect(api.cancel(w.ada, soon["reference"]), 200)
    expect(api.cancel(w.ada, started["reference"]), 409, "cutoff_passed")


@pytest.mark.slow
@pytest.mark.ledger("A-03", "A-05", "S1-071", "S1-072", "S1-076", "S1-097")
def test_crossing_the_cutoff_boundary(api):
    """Book so that starts_at - cutoff lies ~25-85 s ahead; act before and after it."""
    rest = tk.now_restaurant(cutoff=30)
    w = tk.World(api, tk.fixture(restaurants=(rest,)))
    tok = w.ada
    tids = [t["id"] for t in rest["tables"]]
    start_local = tk.local_at(rest, tk.now_utc() + timedelta(minutes=30, seconds=25))
    boundary = tk.instant(start_local, rest["timezone"]) - timedelta(minutes=30)
    X = api.book(tok, rest["id"], tids[0], start_local)
    Y = api.book(tok, rest["id"], tids[1], start_local)
    Z = api.book(tok, rest["id"], tids[2], start_local)
    assert tk.now_utc() < boundary - timedelta(seconds=15), "setup too slow to test the boundary"
    expect(api.cancel(tok, X["reference"]), 200)
    expect(api.patch(tok, Y["reference"], {"party_size": 3}), 200)
    tk.wait_until(boundary + timedelta(seconds=15))
    again = api.cancel(tok, X["reference"])
    expect(again, 200)  # already cancelled: current state, not an error, even past the cutoff
    assert again.json["status"] == "cancelled"
    expect(api.cancel(tok, Z["reference"]), 409, "cutoff_passed")
    expect(api.patch(tok, Y["reference"], {"party_size": 4}), 409, "cutoff_passed")
    expect(api.moves(tok, {"moves": [{"reference": Y["reference"]}]}), 409, "cutoff_passed")
    assert api.get_ok(tok, Y["reference"])["party_size"] == 3
    assert api.get_ok(tok, Z["reference"])["status"] == "confirmed"
