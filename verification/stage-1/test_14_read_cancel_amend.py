"""GET /reservations, GET /reservations/{ref}, cancel and PATCH (spec §8)."""
import pytest

import tk
from tk import ANKER, FRI, THU, THU2, PAST_THU, body, expect


@pytest.mark.ledger("S1-068")
def test_list_empty(w, api):
    r = api.call("GET", "/reservations", token=w.ada)
    expect(r, 200)
    assert r.json == {"reservations": []}


@pytest.mark.ledger("S1-068", "S1-056")
def test_list_ordered_by_absolute_start_descending(w, api):
    made = [
        api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00"),      # 17:00Z
        api.book(w.ada, "r_harbor", "h_1", f"{THU}T14:10"),     # 18:10Z: later instant, earlier wall-clock
        api.book(w.ada, "r_anker", "t_1", f"{FRI}T18:00"),
        api.book(w.ada, "r_anker", "t_2", f"{THU2}T20:00"),
        api.book(w.ada, "r_anker", "t_3", f"{PAST_THU}T19:00"),
    ]
    expect(api.cancel(w.ada, made[2]["reference"]), 200)
    api.book(w.bob, "r_anker", "t_2", f"{THU}T19:00")
    got = api.list(w.ada)
    want = [made[3], made[2], made[1], made[0], made[4]]
    assert [g["reference"] for g in got] == [m["reference"] for m in want]
    assert [g["status"] for g in got] == ["confirmed", "cancelled", "confirmed", "confirmed", "confirmed"]
    for g in got:
        tk.assert_res(g)


@pytest.mark.ledger("S1-069")
def test_get_own_reservation(w, api):
    m = api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00", 3)
    g = api.get_ok(w.ada, m["reference"])
    assert g == m


@pytest.mark.ledger("S1-069")
def test_get_foreign_or_unknown_is_404(w, api):
    m = api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00", 3)
    foreign = api.get(w.bob, m["reference"])
    unknown = api.get(w.bob, "ZZZZZZ99")
    expect(foreign, 404, "not_found")
    expect(unknown, 404, "not_found")
    assert foreign.json["error"]["code"] == unknown.json["error"]["code"]


@pytest.mark.ledger("S1-070", "A-15")
def test_cancel_returns_full_cancelled_reservation(w, api):
    m = api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00", 3)
    c = api.cancel(w.ada, m["reference"])
    expect(c, 200)
    tk.assert_res(c.json, ANKER, "t_2", f"{THU}T19:00", 3, "cancelled")
    tk.same_identity(c.json, m)
    assert api.get_ok(w.ada, m["reference"])["status"] == "cancelled"
    assert "t_2" in api.free_tables("r_anker", f"{THU}T19:00")


@pytest.mark.ledger("S1-071")
def test_cancel_twice_200_current_state(w, api):
    m = api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00")
    first = api.cancel(w.ada, m["reference"])
    expect(first, 200)
    second = api.cancel(w.ada, m["reference"])
    expect(second, 200)
    assert second.json["status"] == "cancelled"
    assert second.json == first.json


@pytest.mark.ledger("S1-073")
def test_cancel_foreign_or_unknown_404(w, api):
    m = api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00")
    expect(api.cancel(w.bob, m["reference"]), 404, "not_found")
    expect(api.cancel(w.bob, "ZZZZZZ99"), 404, "not_found")
    assert api.get_ok(w.ada, m["reference"])["status"] == "confirmed"


@pytest.mark.ledger("S1-074", "S1-079", "A-15")
def test_patch_each_field(w, api):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    p = api.patch(w.ada, m["reference"], {"table_id": "t_2"})
    expect(p, 200)
    tk.assert_res(p.json, ANKER, "t_2", f"{THU}T19:00", 2, "confirmed")
    tk.same_identity(p.json, m)
    p = api.patch(w.ada, m["reference"], {"party_size": 4})
    expect(p, 200)
    tk.assert_res(p.json, ANKER, "t_2", f"{THU}T19:00", 4, "confirmed")
    p = api.patch(w.ada, m["reference"], {"starts_at_local": f"{FRI}T22:00"})
    expect(p, 200)
    tk.assert_res(p.json, ANKER, "t_2", f"{FRI}T22:00", 4, "confirmed")
    tk.assert_ts(p.json["ends_at"], f"{FRI}T23:30:00+02:00")
    p = api.patch(w.ada, m["reference"], {"table_id": "t_3", "starts_at_local": f"{THU}T18:00", "party_size": 6})
    expect(p, 200)
    tk.assert_res(p.json, ANKER, "t_3", f"{THU}T18:00", 6, "confirmed")
    tk.same_identity(p.json, m)
    assert api.get_ok(w.ada, m["reference"]) == p.json


@pytest.mark.ledger("S1-074", "A-04")
def test_patch_empty_body_is_noop_200(w, api):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    p = api.patch(w.ada, m["reference"], {})
    expect(p, 200)
    assert p.json == m


@pytest.mark.ledger("S1-079")
def test_patch_releases_old_slot_and_reserves_new(w, api):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    expect(api.patch(w.ada, m["reference"], {"starts_at_local": f"{THU}T21:00"}), 200)
    assert "t_1" in api.free_tables("r_anker", f"{THU}T19:00")
    assert "t_1" not in api.free_tables("r_anker", f"{THU}T21:00")
    api.book(w.bob, "r_anker", "t_1", f"{THU}T19:00")
    expect(api.create(w.bob, body("r_anker", "t_1", f"{THU}T21:30")), 409, "table_unavailable")


@pytest.mark.ledger("S1-079")
def test_patch_into_overlap_with_own_old_interval(w, api):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    p = api.patch(w.ada, m["reference"], {"starts_at_local": f"{THU}T19:30"})
    expect(p, 200)
    tk.assert_res(p.json, ANKER, "t_1", f"{THU}T19:30", 2)
    p = api.patch(w.ada, m["reference"], {"starts_at_local": f"{THU}T19:00"})
    expect(p, 200)


@pytest.mark.ledger("S1-079", "S1-058")
def test_failed_patch_keeps_booking_and_occupancy(w, api):
    other = api.book(w.bob, "r_anker", "t_2", f"{THU}T20:30")
    m = api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00")
    expect(api.patch(w.ada, m["reference"], {"starts_at_local": f"{THU}T20:00"}), 409, "table_unavailable")
    assert api.get_ok(w.ada, m["reference"]) == m
    assert "t_2" not in api.free_tables("r_anker", f"{THU}T19:00")
    expect(api.create(w.cy, body("r_anker", "t_2", f"{THU}T19:00")), 409, "table_unavailable")
    assert api.get_ok(w.bob, other["reference"]) == other


@pytest.mark.ledger("S1-077")
def test_patch_cancelled_409(w, api):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00")
    expect(api.cancel(w.ada, m["reference"]), 200)
    expect(api.patch(w.ada, m["reference"], {"party_size": 1}), 409, "reservation_cancelled")
    cur = api.get_ok(w.ada, m["reference"])
    assert cur["status"] == "cancelled" and cur["party_size"] == 2


@pytest.mark.ledger("S1-078")
def test_patch_foreign_or_unknown_404(w, api):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00")
    expect(api.patch(w.bob, m["reference"], {"party_size": 1}), 404, "not_found")
    expect(api.patch(w.bob, "ZZZZZZ99", {"party_size": 1}), 404, "not_found")
    assert api.get_ok(w.ada, m["reference"])["party_size"] == 2


@pytest.mark.ledger("S1-075")
@pytest.mark.parametrize("b,status,code", [
    ({"starts_at_local": f"{THU}T19:15"}, 422, "not_on_slot_grid"),
    ({"starts_at_local": f"{THU}T22:00"}, 422, "outside_opening_hours"),
    ({"starts_at_local": f"{tk.MON}T19:00"}, 422, "outside_opening_hours"),
    ({"party_size": 3}, 422, "party_exceeds_capacity"),
    ({"party_size": 0}, 422, "validation_failed"),
    ({"party_size": "2"}, 422, "validation_failed"),
    ({"party_size": None}, 422, "validation_failed"),
    ({"starts_at_local": f"{THU}T19:00:00"}, 422, "validation_failed"),
    ({"starts_at_local": "2027-02-30T19:00"}, 422, "validation_failed"),
    ({"starts_at_local": 1900}, 400, "malformed_request"),
    ({"table_id": 2}, 400, "malformed_request"),
    ({"table_id": "t_nope"}, 404, "not_found"),
    ({"table_id": "b_1"}, 404, "not_found"),
    ({"starts_at_local": "2026-03-29T02:30"}, 422, "invalid_local_time"),
], ids=["grid", "end-after-close", "closed-day", "capacity", "party-zero", "party-string", "party-null",
        "local-seconds", "local-impossible", "local-int", "table-int", "table-unknown", "table-foreign", "gap"])
def test_patch_validation_same_as_create(w, api, b, status, code):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    expect(api.patch(w.ada, m["reference"], b), status, code)
    assert api.get_ok(w.ada, m["reference"]) == m


@pytest.mark.ledger("S1-074")
def test_patch_does_not_need_idempotency_key_and_is_repeatable(w, api):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    for _ in range(2):
        p = api.patch(w.ada, m["reference"], {"table_id": "t_2"})
        expect(p, 200)
        assert p.json["table_id"] == "t_2"


@pytest.mark.ledger("S1-020", "A-04")
@pytest.mark.parametrize("raw", ["garbage", "[1]", '"x"', "{"])
def test_patch_unparseable_body_400(w, api, raw):
    m = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    expect(api.patch(w.ada, m["reference"], raw=raw), 400, "malformed_request")
