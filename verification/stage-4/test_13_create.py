"""POST /reservations (spec §8) — success shape, rules and validation."""
from datetime import timedelta

import pytest

import tk
from tk import ANKER, FRI, MON, THU, body, expect


@pytest.mark.ledger("S1-055", "S1-056", "S1-057", "S1-010", "A-15")
def test_create_success_shape(w, api):
    before = tk.now_utc()
    r = api.create(w.ada, body("r_anker", "t_2", f"{THU}T19:00", 4))
    expect(r, 201)
    j = tk.assert_res(r.json, ANKER, "t_2", f"{THU}T19:00", 4, "confirmed")
    tk.assert_ts(j["starts_at"], f"{THU}T19:00:00+02:00")
    tk.assert_ts(j["ends_at"], f"{THU}T20:30:00+02:00")
    created = tk.parse_ts(j["created_at"])
    assert before - timedelta(minutes=10) <= created <= tk.now_utc() + timedelta(minutes=10), \
        f"created_at {j['created_at']} is not the creation time"


@pytest.mark.ledger("S1-057")
def test_references_unique_and_well_formed(api):
    fx = tk.fixture(reservations=[tk.seed("sx", "SEED0001", "u_bob", "r_big", "b_10", f"{THU}T10:00")])
    w = tk.World(api, fx)
    refs = {"SEED0001"}
    ids = {"sx"}
    toks = [w.ada, w.bob, w.cy]
    for i in range(30):
        r = api.book(toks[i % 3], "r_big", f"b_{1 + i % 9}", f"{THU}T{10 + i // 9:02d}:00")
        assert tk.REF_RE.match(r["reference"])
        assert r["reference"] not in refs, f"duplicate reference {r['reference']}"
        assert r["reservation_id"] not in ids, f"duplicate reservation_id {r['reservation_id']}"
        refs.add(r["reference"])
        ids.add(r["reservation_id"])


@pytest.mark.ledger("S1-058", "S1-067")
def test_overlap_rules_half_open(w, api):
    api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00")
    for t in ("18:00", "18:30", "19:00", "19:30", "20:00"):
        expect(api.create(w.bob, body("r_anker", "t_2", f"{THU}T{t}")), 409, "table_unavailable")
    api.book(w.bob, "r_anker", "t_2", f"{THU}T20:30")  # starts exactly at the previous end
    api.book(w.bob, "r_anker", "t_1", f"{THU}T19:00")  # other table, same time
    assert len(api.list(w.bob)) == 2


@pytest.mark.ledger("S1-058")
def test_back_to_back_before(w, api):
    api.book(w.ada, "r_big", "b_1", f"{THU}T12:00")
    api.book(w.bob, "r_big", "b_1", f"{THU}T11:00")  # ends exactly when the other starts
    expect(api.create(w.bob, body("r_big", "b_1", f"{THU}T11:30")), 409, "table_unavailable")


@pytest.mark.ledger("S1-059")
@pytest.mark.parametrize("hhmm", ["19:15", "19:01", "18:59", "20:45"])
def test_not_on_slot_grid(w, api, hhmm):
    expect(api.create(w.ada, body("r_anker", "t_1", f"{THU}T{hhmm}")), 422, "not_on_slot_grid")


@pytest.mark.ledger("S1-060")
@pytest.mark.parametrize("local", [f"{THU}T17:30", f"{THU}T22:00", f"{THU}T22:30", f"{THU}T23:00",
                                   f"{MON}T19:00", f"{THU}T00:00", f"{FRI}T22:30", f"{THU}T17:00"])
def test_outside_opening_hours(w, api, local):
    expect(api.create(w.ada, body("r_anker", "t_1", local)), 422, "outside_opening_hours")


@pytest.mark.ledger("S1-060", "S1-051")
def test_last_slot_ending_exactly_at_close_accepted(w, api):
    api.book(w.ada, "r_anker", "t_1", f"{THU}T21:30")
    api.book(w.ada, "r_anker", "t_1", f"{FRI}T22:00")
    api.book(w.ada, "r_anker", "t_1", f"{THU}T18:00")


@pytest.mark.ledger("S1-061")
def test_capacity(w, api):
    expect(api.create(w.ada, body("r_anker", "t_1", f"{THU}T19:00", 3)), 422, "party_exceeds_capacity")
    api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    expect(api.create(w.ada, body("r_anker", "t_3", f"{THU}T19:00", 7)), 422, "party_exceeds_capacity")
    api.book(w.ada, "r_anker", "t_3", f"{THU}T19:00", 6)


@pytest.mark.ledger("S1-062", "S1-022", "A-16")
@pytest.mark.parametrize("party", [0, -1, 2.5, "2", True, False, None, [2], {"n": 2}, 1.5],
                         ids=["zero", "negative", "fraction", "string", "true", "false", "null", "list", "object", "1.5"])
def test_invalid_party_size_422(w, api, party):
    expect(api.create(w.ada, body("r_anker", "t_2", f"{THU}T19:00", party)), 422, "validation_failed")
    assert api.list(w.ada) == []


@pytest.mark.ledger("S1-062", "S1-065")
def test_missing_party_size_422(w, api):
    b = body("r_anker", "t_2", f"{THU}T19:00")
    del b["party_size"]
    expect(api.create(w.ada, b), 422, "validation_failed")


@pytest.mark.ledger("S1-023")
@pytest.mark.parametrize("local", [f"{THU}T19:00:00", f"{THU}T19:00+02:00", f"{THU}T19:00Z", f"{THU} 19:00",
                                   "2027-02-30T19:00", f"{THU}T25:00", f"{THU}T19:60", "", "19:00", "2027-6-17T19:00",
                                   f"{THU}T19:00:00.000", f"{THU}t19:00", f"{THU}T1900", f" {THU}T19:00", f"{THU}T19:00 ",
                                   f"{THU}T9:00"])
def test_malformed_starts_at_local_422(w, api, local):
    expect(api.create(w.ada, body("r_anker", "t_2", local)), 422, "validation_failed")


@pytest.mark.ledger("S1-023", "S1-020")
@pytest.mark.parametrize("value", [1900, None, ["2027-06-17T19:00"], {"t": 1}, True],
                         ids=["int", "null", "list", "object", "bool"])
def test_non_string_starts_at_local_400(w, api, value):
    if value is None:
        pytest.skip("null for a required string: missing (422) or wrong type (400) is not decided by the spec")
    expect(api.create(w.ada, body("r_anker", "t_2", value)), 400, "malformed_request")


@pytest.mark.ledger("S1-064")
@pytest.mark.parametrize("rid,tid", [("r_nowhere", "t_1"), ("r_anker", "t_nope"), ("r_anker", "b_1"), ("r_big", "t_1")])
def test_unknown_or_foreign_restaurant_table_404(w, api, rid, tid):
    expect(api.create(w.ada, body(rid, tid, f"{THU}T19:00")), 404, "not_found")


@pytest.mark.ledger("S1-065", "S1-020")
@pytest.mark.parametrize("field,value,status", [
    ("restaurant_id", None, 422), ("table_id", None, 422), ("starts_at_local", None, 422),
    ("restaurant_id", 5, 400), ("table_id", 5, 400), ("restaurant_id", ["r_anker"], 400), ("table_id", {"id": "t_1"}, 400),
    ("table_id", True, 400),
], ids=["no-restaurant", "no-table", "no-start", "restaurant-int", "table-int", "restaurant-list", "table-object", "table-bool"])
def test_missing_or_wrong_type_fields(w, api, field, value, status):
    b = body("r_anker", "t_1", f"{THU}T19:00")
    if value is None:
        del b[field]
    else:
        b[field] = value
    expect(api.create(w.ada, b), status, "validation_failed" if status == 422 else "malformed_request")


@pytest.mark.ledger("S1-066", "S1-001")
def test_rejected_creates_leave_nothing_behind(w, api):
    bad = [
        body("r_anker", "t_1", f"{THU}T19:15"),
        body("r_anker", "t_1", f"{THU}T19:00", 3),
        body("r_anker", "t_1", f"{MON}T19:00"),
        body("r_anker", "t_nope", f"{THU}T19:00"),
        body("r_anker", "t_1", "2026-03-29T02:30"),
    ]
    for b in bad:
        assert api.create(w.ada, b).status in (404, 422)
    assert api.list(w.ada) == []
    assert api.free_tables("r_anker", f"{THU}T19:00") == ["t_1", "t_2", "t_3"]


@pytest.mark.ledger("S1-055", "S1-018")
def test_any_calendar_date_bookable(w, api):
    for d in ("2030-06-20", "2024-06-20", "2099-06-18"):  # all Thursdays
        r = api.book(w.ada, "r_anker", "t_1", f"{d}T19:00")
        assert r["starts_at_local"] == f"{d}T19:00"
        tk.assert_ts(r["starts_at"], tk.exp_start(f"{d}T19:00", "Europe/Berlin"))
