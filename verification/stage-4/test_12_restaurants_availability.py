"""Restaurants and availability (spec §8)."""
import pytest

import tk
from tk import ANKER, FRI, MON, THU, WINTER_THU, body, expect

THU_TIMES = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
FRI_TIMES = THU_TIMES + ["22:00"]


@pytest.mark.ledger("S1-047")
def test_list_restaurants_fixture_order(w, api):
    r = api.call("GET", "/restaurants")
    expect(r, 200)
    want = [{"id": x["id"], "name": x["name"], "timezone": x["timezone"]} for x in tk.fixture()["restaurants"]]
    got = [{k: x.get(k) for k in ("id", "name", "timezone")} for x in r.json["restaurants"]]
    assert got == want


@pytest.mark.ledger("S1-048", "S1-013", "S1-016")
@pytest.mark.parametrize("rest", [tk.ANKER, tk.HARBOR, tk.BIG], ids=lambda r: r["id"])
def test_restaurant_detail_in_fixture_shape(w, api, rest):
    r = api.call("GET", f"/restaurants/{rest['id']}")
    expect(r, 200)
    for k in ("id", "name", "timezone", "slot_minutes", "reservation_duration_minutes",
              "cancellation_cutoff_minutes", "opening_hours", "tables"):
        assert r.json.get(k) == rest[k], f"{k}: {r.json.get(k)!r} != {rest[k]!r}"


@pytest.mark.ledger("S1-048")
def test_restaurant_detail_unknown_404(w, api):
    expect(api.call("GET", "/restaurants/r_nowhere"), 404, "not_found")


@pytest.mark.ledger("S1-050", "S1-051", "S1-052")
def test_availability_thursday_grid_and_tables(w, api):
    r = api.avail("r_anker", THU, 2)
    expect(r, 200)
    j = r.json
    assert j["restaurant_id"] == "r_anker" and j["date"] == THU and j["timezone"] == "Europe/Berlin"
    assert [s["starts_at_local"] for s in j["slots"]] == [f"{THU}T{t}" for t in THU_TIMES]
    for s in j["slots"]:
        tk.assert_ts(s["starts_at"], tk.exp_start(s["starts_at_local"], "Europe/Berlin"))
        assert s["available_table_ids"] == ["t_1", "t_2", "t_3"]


@pytest.mark.ledger("S1-051")
def test_availability_friday_last_slot_ends_at_close(w, api):
    assert [s["starts_at_local"] for s in api.slots("r_anker", FRI, 1)] == [f"{FRI}T{t}" for t in FRI_TIMES]


@pytest.mark.ledger("S1-051")
def test_grid_counts_from_opening_time(w, api):
    # r_harbor opens 11:10 with 15-minute slots and 60-minute bookings until 22:00
    times = [s["starts_at_local"][11:] for s in api.slots("r_harbor", THU, 2)]
    want, m = [], 11 * 60 + 10
    while m + 60 <= 22 * 60:
        want.append(f"{m // 60:02d}:{m % 60:02d}")
        m += 15
    assert times == want
    expect(api.create(w.ada, body("r_harbor", "h_1", f"{THU}T12:00")), 422, "not_on_slot_grid")
    api.book(w.ada, "r_harbor", "h_1", f"{THU}T12:10")


@pytest.mark.ledger("S1-052")
@pytest.mark.parametrize("party,tables", [(1, ["t_1", "t_2", "t_3"]), (2, ["t_1", "t_2", "t_3"]), (3, ["t_2", "t_3"]),
                                          (4, ["t_2", "t_3"]), (5, ["t_3"]), (6, ["t_3"]), (7, [])])
def test_capacity_filter_and_empty_slots_still_listed(w, api, party, tables):
    slots = api.slots("r_anker", THU, party)
    assert len(slots) == 8
    for s in slots:
        assert s["available_table_ids"] == tables


@pytest.mark.ledger("S1-053", "S1-016")
def test_closed_day_has_no_slots(w, api):
    r = api.avail("r_anker", MON, 2)
    expect(r, 200)
    assert r.json["slots"] == [] and r.json["date"] == MON


@pytest.mark.ledger("S1-052", "S1-058")
def test_booking_blocks_overlapping_slots_only(w, api):
    api.book(w.bob, "r_anker", "t_2", f"{THU}T19:00")
    free = {s["starts_at_local"][11:]: s["available_table_ids"] for s in api.slots("r_anker", THU, 2)}
    for t in ("18:00", "18:30", "19:00", "19:30", "20:00"):
        assert free[t] == ["t_1", "t_3"], t
    for t in ("20:30", "21:00", "21:30"):
        assert free[t] == ["t_1", "t_2", "t_3"], t


@pytest.mark.ledger("S1-054", "S1-070")
def test_cancel_frees_slot_for_next_read(w, api):
    r = api.book(w.ada, "r_anker", "t_3", f"{THU}T20:00", 5)
    assert api.free_tables("r_anker", f"{THU}T20:00", 5) == []
    expect(api.cancel(w.ada, r["reference"]), 200)
    assert api.free_tables("r_anker", f"{THU}T20:00", 5) == ["t_3"]
    api.book(w.bob, "r_anker", "t_3", f"{THU}T20:00", 5)


@pytest.mark.ledger("S1-049", "S1-021")
@pytest.mark.parametrize("params", [
    {"date": THU, "party_size": "2"},
    {"restaurant_id": "r_anker", "party_size": "2"},
    {"restaurant_id": "r_anker", "date": THU},
    {},
], ids=["no-restaurant", "no-date", "no-party", "none"])
def test_missing_params_422(w, api, params):
    expect(api.call("GET", "/availability", params=params), 422, "validation_failed")


@pytest.mark.ledger("S1-024", "S1-049")
@pytest.mark.parametrize("party", ["0", "-1", "1e9", "4.0", "+4", "abc", "", " 4", "4 ", "0x4", "2.5"])
def test_party_size_query_must_be_plain_positive_digits(w, api, party):
    expect(api.avail("r_anker", THU, party), 422, "validation_failed")


@pytest.mark.ledger("S1-024")
def test_party_size_leading_zero_is_plain_digits(w, api):
    r = api.avail("r_anker", THU, "04")
    expect(r, 200)
    assert r.json["slots"][0]["available_table_ids"] == ["t_2", "t_3"]


@pytest.mark.ledger("S1-049", "S1-021")
@pytest.mark.parametrize("date", ["2027-02-29", "2027-13-01", "2027-06-31", "2027-6-17", "17.06.2027",
                                  f"{THU}T00:00", "", "tomorrow", "2027/06/17", "20270617"])
def test_invalid_dates_422(w, api, date):
    expect(api.avail("r_anker", date, 2), 422, "validation_failed")


@pytest.mark.ledger("S1-049")
def test_leap_day_valid(api):
    rest = {**tk.HARBOR}
    tk.World(api, tk.fixture(restaurants=(rest,)))
    r = api.avail("r_harbor", "2028-02-29", 2)
    expect(r, 200)
    assert r.json["slots"] and r.json["slots"][0]["starts_at_local"] == "2028-02-29T11:10"


@pytest.mark.ledger("S1-049")
def test_unknown_restaurant_404(w, api):
    expect(api.avail("r_nowhere", THU, 2), 404, "not_found")


@pytest.mark.ledger("S1-015", "S1-052")
def test_seeded_reservation_blocks_availability(api):
    fx = tk.fixture(reservations=[tk.seed("s1", "SEED01", "u_bob", "r_anker", "t_1", f"{THU}T21:30", 2)])
    tk.World(api, fx)
    free = {s["starts_at_local"][11:]: s["available_table_ids"] for s in api.slots("r_anker", THU, 1)}
    assert free["20:00"] == ["t_1", "t_2", "t_3"]
    assert free["20:30"] == ["t_2", "t_3"] and free["21:30"] == ["t_2", "t_3"]


@pytest.mark.ledger("S1-018", "S1-050")
def test_past_dates_have_availability(w, api):
    slots = api.slots("r_anker", tk.PAST_THU, 2)
    assert len(slots) == 8
    tk.assert_ts(slots[0]["starts_at"], f"{tk.PAST_THU}T18:00:00+02:00")


@pytest.mark.ledger("S1-052")
def test_other_restaurants_bookings_do_not_block(w, api):
    api.book(w.ada, "r_big", "b_1", f"{THU}T19:00")
    assert api.free_tables("r_anker", f"{THU}T19:00", 1) == ["t_1", "t_2", "t_3"]


@pytest.mark.ledger("S1-084")
def test_winter_offsets(w, api):
    for s in api.slots("r_anker", WINTER_THU, 2):
        assert s["starts_at"].endswith("+01:00"), s
