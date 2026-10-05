"""Time zones and DST (spec §9, §8 slot rule, ledger A-08).

Expected offsets are written out literally from the spec's transition table and IANA
rules (Europe/Berlin CET +01:00 / CEST +02:00; America/New_York EST -05:00 / EDT -04:00).
"""
import pytest

import tk
from tk import expect

BER_SPRING, BER_FALL = "2026-03-29", "2026-10-25"
NY_SPRING, NY_FALL = "2026-03-08", "2026-11-01"


def _slots(api, rid, date, party=2):
    return [(s["starts_at_local"], s["starts_at"]) for s in api.slots(rid, date, party)]


def _assert_slots(got, want):
    assert [g[0] for g in got] == [x[0] for x in want], f"slot list differs:\n got  {[g[0] for g in got]}\n want {[x[0] for x in want]}"
    for (gl, gs), (wl, ws) in zip(got, want):
        tk.assert_ts(gs, ws)


def _make(date, rows):
    return [(f"{date}T{hm}", f"{date}T{hm}:00{off}") for hm, off in rows]


@pytest.mark.ledger("S1-081", "S1-051", "S1-084", "A-08")
def test_berlin_spring_forward_availability_skips_gap(w, api):
    want = _make(BER_SPRING, [("00:00", "+01:00"), ("00:30", "+01:00"), ("01:00", "+01:00"), ("01:30", "+01:00"),
                              ("03:00", "+02:00"), ("03:30", "+02:00"), ("04:00", "+02:00"), ("04:30", "+02:00")])
    _assert_slots(_slots(api, "r_dst_ber", BER_SPRING), want)


@pytest.mark.ledger("S1-081", "S1-051", "S1-084", "A-08")
def test_new_york_spring_forward_availability_skips_gap(w, api):
    want = _make(NY_SPRING, [("00:00", "-05:00"), ("00:30", "-05:00"), ("01:00", "-05:00"), ("01:30", "-05:00"),
                             ("03:00", "-04:00"), ("03:30", "-04:00"), ("04:00", "-04:00"), ("04:30", "-04:00")])
    _assert_slots(_slots(api, "r_dst_ny", NY_SPRING), want)


@pytest.mark.ledger("S1-082", "S1-051", "S1-084", "A-08")
def test_berlin_fall_back_repeated_times_appear_once_first_offset(w, api):
    want = _make(BER_FALL, [("00:00", "+02:00"), ("00:30", "+02:00"), ("01:00", "+02:00"), ("01:30", "+02:00"),
                            ("02:00", "+02:00"), ("02:30", "+02:00"), ("03:00", "+01:00"), ("03:30", "+01:00"),
                            ("04:00", "+01:00"), ("04:30", "+01:00")])
    _assert_slots(_slots(api, "r_dst_ber", BER_FALL), want)


@pytest.mark.ledger("S1-082", "S1-051", "S1-084", "A-08")
def test_new_york_fall_back_repeated_times_appear_once_first_offset(w, api):
    want = _make(NY_FALL, [("00:00", "-04:00"), ("00:30", "-04:00"), ("01:00", "-04:00"), ("01:30", "-04:00"),
                           ("02:00", "-05:00"), ("02:30", "-05:00"), ("03:00", "-05:00"), ("03:30", "-05:00"),
                           ("04:00", "-05:00"), ("04:30", "-05:00")])
    _assert_slots(_slots(api, "r_dst_ny", NY_FALL), want)


@pytest.mark.ledger("S1-063", "S1-081")
@pytest.mark.parametrize("rid,tid,local", [
    ("r_dst_ber", "d_1", f"{BER_SPRING}T02:00"),
    ("r_dst_ber", "d_1", f"{BER_SPRING}T02:30"),
    ("r_dst_ny", "n_1", f"{NY_SPRING}T02:00"),
    ("r_dst_ny", "n_1", f"{NY_SPRING}T02:30"),
])
def test_booking_in_spring_gap_is_invalid_local_time(w, api, rid, tid, local):
    expect(api.create(w.ada, tk.body(rid, tid, local)), 422, "invalid_local_time")
    assert api.list(w.ada) == []


@pytest.mark.ledger("S1-063", "A-02")
def test_gap_precedes_grid_and_opening_hours(w, api):
    # 02:15 is a gap time and off the 30-minute grid -> invalid_local_time wins (A-02)
    expect(api.create(w.ada, tk.body("r_dst_ber", "d_1", f"{BER_SPRING}T02:15")), 422, "invalid_local_time")
    # r_anker is closed on Sundays: a gap time there is still invalid_local_time (A-02)
    expect(api.create(w.ada, tk.body("r_anker", "t_1", f"{BER_SPRING}T02:30")), 422, "invalid_local_time")


@pytest.mark.ledger("S1-083", "S1-056", "S1-058")
def test_berlin_spring_duration_is_absolute(w, api):
    r = api.book(w.ada, "r_dst_ber", "d_1", f"{BER_SPRING}T01:30")
    tk.assert_ts(r["starts_at"], f"{BER_SPRING}T01:30:00+01:00")
    tk.assert_ts(r["ends_at"], f"{BER_SPRING}T04:00:00+02:00")
    # 03:00 and 03:30 CEST are before the absolute end (04:00 CEST) -> overlap
    expect(api.create(w.bob, tk.body("r_dst_ber", "d_1", f"{BER_SPRING}T03:00")), 409, "table_unavailable")
    expect(api.create(w.bob, tk.body("r_dst_ber", "d_1", f"{BER_SPRING}T03:30")), 409, "table_unavailable")
    free = {s["starts_at_local"]: s["available_table_ids"] for s in api.slots("r_dst_ber", BER_SPRING, 2)}
    assert free[f"{BER_SPRING}T03:00"] == ["d_2"] and free[f"{BER_SPRING}T03:30"] == ["d_2"]
    assert free[f"{BER_SPRING}T04:00"] == ["d_1", "d_2"]
    b = api.book(w.bob, "r_dst_ber", "d_1", f"{BER_SPRING}T04:00")  # back-to-back at the absolute end
    tk.assert_ts(b["starts_at"], f"{BER_SPRING}T04:00:00+02:00")


@pytest.mark.ledger("S1-083", "S1-056", "S1-058")
def test_new_york_spring_duration_is_absolute(w, api):
    r = api.book(w.ada, "r_dst_ny", "n_1", f"{NY_SPRING}T01:30")
    tk.assert_ts(r["starts_at"], f"{NY_SPRING}T01:30:00-05:00")
    tk.assert_ts(r["ends_at"], f"{NY_SPRING}T04:00:00-04:00")
    expect(api.create(w.bob, tk.body("r_dst_ny", "n_1", f"{NY_SPRING}T03:30")), 409, "table_unavailable")
    api.book(w.bob, "r_dst_ny", "n_1", f"{NY_SPRING}T04:00")


@pytest.mark.ledger("S1-083", "S1-082", "S1-056")
def test_berlin_fall_back_spec_example_and_first_occurrence(w, api):
    r = api.book(w.ada, "r_dst_ber", "d_1", f"{BER_FALL}T01:30")
    tk.assert_ts(r["starts_at"], f"{BER_FALL}T01:30:00+02:00")
    tk.assert_ts(r["ends_at"], f"{BER_FALL}T02:00:00+01:00")  # spec §9 example
    assert r["ends_at"].startswith(f"{BER_FALL}T02:00:00")
    # 02:30 resolves to its FIRST occurrence (00:30Z), inside [23:30Z, 01:00Z) -> taken
    free = {s["starts_at_local"]: s["available_table_ids"] for s in api.slots("r_dst_ber", BER_FALL, 2)}
    assert free[f"{BER_FALL}T02:30"] == ["d_2"]
    assert free[f"{BER_FALL}T03:00"] == ["d_1", "d_2"]
    expect(api.create(w.bob, tk.body("r_dst_ber", "d_1", f"{BER_FALL}T02:30")), 409, "table_unavailable")
    expect(api.create(w.bob, tk.body("r_dst_ber", "d_1", f"{BER_FALL}T02:00")), 409, "table_unavailable")
    c = api.book(w.bob, "r_dst_ber", "d_1", f"{BER_FALL}T03:00")
    tk.assert_ts(c["starts_at"], f"{BER_FALL}T03:00:00+01:00")
    d = api.book(w.bob, "r_dst_ber", "d_2", f"{BER_FALL}T02:30")
    tk.assert_ts(d["starts_at"], f"{BER_FALL}T02:30:00+02:00")
    tk.assert_ts(d["ends_at"], f"{BER_FALL}T03:00:00+01:00")


@pytest.mark.ledger("S1-083", "S1-082", "S1-056")
def test_new_york_fall_back_first_occurrence(w, api):
    a = api.book(w.ada, "r_dst_ny", "n_1", f"{NY_FALL}T00:30")
    tk.assert_ts(a["starts_at"], f"{NY_FALL}T00:30:00-04:00")
    tk.assert_ts(a["ends_at"], f"{NY_FALL}T01:00:00-05:00")
    # 01:30 first occurrence (-04:00 = 05:30Z) overlaps [04:30Z, 06:00Z)
    expect(api.create(w.bob, tk.body("r_dst_ny", "n_1", f"{NY_FALL}T01:30")), 409, "table_unavailable")
    expect(api.create(w.bob, tk.body("r_dst_ny", "n_1", f"{NY_FALL}T01:00")), 409, "table_unavailable")
    b = api.book(w.bob, "r_dst_ny", "n_1", f"{NY_FALL}T02:00")
    tk.assert_ts(b["starts_at"], f"{NY_FALL}T02:00:00-05:00")
    c = api.book(w.bob, "r_dst_ny", "n_2", f"{NY_FALL}T01:30")
    tk.assert_ts(c["starts_at"], f"{NY_FALL}T01:30:00-04:00")
    tk.assert_ts(c["ends_at"], f"{NY_FALL}T02:00:00-05:00")


@pytest.mark.ledger("S1-083", "S1-051", "S1-060", "A-08")
def test_closing_time_compared_in_absolute_time_spring(w, api):
    # r_dst_short closes 03:30 CEST (01:30Z) on spring-forward night; 01:30 CET + 90 min = 04:00 CEST
    want = _make(BER_SPRING, [("00:00", "+01:00"), ("00:30", "+01:00"), ("01:00", "+01:00")])
    _assert_slots(_slots(api, "r_dst_short", BER_SPRING), want)
    expect(api.create(w.ada, tk.body("r_dst_short", "s_1", f"{BER_SPRING}T01:30")), 422, "outside_opening_hours")
    r = api.book(w.ada, "r_dst_short", "s_1", f"{BER_SPRING}T01:00")
    tk.assert_ts(r["ends_at"], f"{BER_SPRING}T03:30:00+02:00")


@pytest.mark.ledger("S1-083", "S1-051", "S1-060", "A-08")
def test_closing_time_compared_in_absolute_time_fall(w, api):
    # closes 03:30 CET (02:30Z) on fall-back night; 02:30 (+02:00) + 90 min = 03:00 CET <= closes
    want = _make(BER_FALL, [("00:00", "+02:00"), ("00:30", "+02:00"), ("01:00", "+02:00"), ("01:30", "+02:00"),
                            ("02:00", "+02:00"), ("02:30", "+02:00")])
    _assert_slots(_slots(api, "r_dst_short", BER_FALL), want)
    r = api.book(w.ada, "r_dst_short", "s_1", f"{BER_FALL}T02:30")
    tk.assert_ts(r["ends_at"], f"{BER_FALL}T03:00:00+01:00")
    expect(api.create(w.ada, tk.body("r_dst_short", "s_1", f"{BER_FALL}T03:00")), 422, "outside_opening_hours")


@pytest.mark.ledger("S1-084", "S1-017", "S1-050")
def test_offsets_follow_iana_summer_and_winter(w, api):
    s = api.slots("r_anker", tk.THU, 2)[0]
    assert s["starts_at_local"] == f"{tk.THU}T18:00"
    tk.assert_ts(s["starts_at"], f"{tk.THU}T18:00:00+02:00")
    s = api.slots("r_anker", tk.WINTER_THU, 2)[0]
    tk.assert_ts(s["starts_at"], f"{tk.WINTER_THU}T18:00:00+01:00")
    s = api.slots("r_harbor", tk.THU, 2)[0]
    tk.assert_ts(s["starts_at"], f"{tk.THU}T11:10:00-04:00")
    s = api.slots("r_harbor", tk.WINTER_THU, 2)[0]
    tk.assert_ts(s["starts_at"], f"{tk.WINTER_THU}T11:10:00-05:00")
    r = api.book(w.ada, "r_anker", "t_1", f"{tk.WINTER_THU}T21:30")
    tk.assert_ts(r["starts_at"], f"{tk.WINTER_THU}T21:30:00+01:00")
    tk.assert_ts(r["ends_at"], f"{tk.WINTER_THU}T23:00:00+01:00")


@pytest.mark.ledger("S1-084", "S1-017")
def test_half_hour_offset_zone(api):
    kol = {"id": "r_kol", "name": "Chai", "timezone": "Asia/Kolkata", "slot_minutes": 30,
           "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 60,
           "opening_hours": [{"weekday": "thu", "opens": "12:00", "closes": "15:00"}],
           "tables": [{"id": "k_1", "label": "1", "capacity": 4}]}
    w = tk.World(api, tk.fixture(restaurants=(kol,)))
    got = _slots(api, "r_kol", tk.THU)
    want = _make(tk.THU, [("12:00", "+05:30"), ("12:30", "+05:30"), ("13:00", "+05:30"), ("13:30", "+05:30"), ("14:00", "+05:30")])
    _assert_slots(got, want)
    r = api.book(w.ada, "r_kol", "k_1", f"{tk.THU}T13:00")
    tk.assert_ts(r["ends_at"], f"{tk.THU}T14:00:00+05:30")


@pytest.mark.ledger("S1-075", "S1-063", "S1-084")
def test_patch_into_future_gap_is_invalid_local_time(w, api):
    # IANA rules beyond the spec table: Berlin springs forward on 2027-03-28 02:00 -> 03:00
    r = api.book(w.ada, "r_dst_ber", "d_1", f"{BER_FALL}T00:00")
    expect(api.patch(w.ada, r["reference"], {"starts_at_local": "2027-03-28T02:30"}), 422, "invalid_local_time")
    assert api.get_ok(w.ada, r["reference"])["starts_at_local"] == f"{BER_FALL}T00:00"
    ok = api.patch(w.ada, r["reference"], {"starts_at_local": "2027-03-28T03:00"})
    expect(ok, 200)
    tk.assert_ts(ok.json["starts_at"], "2027-03-28T03:00:00+02:00")
    tk.assert_ts(ok.json["ends_at"], "2027-03-28T04:30:00+02:00")


@pytest.mark.ledger("S1-082", "S1-083")
def test_fall_back_patch_resolves_first_occurrence(w, api):
    a = api.book(w.ada, "r_dst_ber", "d_1", f"{BER_FALL}T00:00")
    ok = api.patch(w.ada, a["reference"], {"starts_at_local": f"{BER_FALL}T02:00"})
    expect(ok, 200)
    tk.assert_ts(ok.json["starts_at"], f"{BER_FALL}T02:00:00+02:00")
    tk.assert_ts(ok.json["ends_at"], f"{BER_FALL}T02:30:00+01:00")
