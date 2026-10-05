"""Atomic reservation moves (spec §11) with its idempotency (§7) and precedence (ledger A-12)."""
import pytest

import tk
from tk import ANKER, PAST_THU, THU, FRI, expect

PAST = tk.seed("res_past_ada", "PAST01", "u_ada", "r_anker", "t_3", f"{PAST_THU}T19:00", 2)


@pytest.fixture
def mw(api):
    """Ada holds A (t_1 19:00) and B (t_2 19:00) on THU at r_anker plus a past booking PAST."""
    w = tk.World(api, tk.fixture(reservations=[PAST]))
    w.A = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00", 2)
    w.B = api.book(w.ada, "r_anker", "t_2", f"{THU}T19:00", 2)
    return w


def _unchanged(api, tok, *originals):
    for o in originals:
        cur = api.get_ok(tok, o["reference"])
        for k in ("table_id", "starts_at", "ends_at", "starts_at_local", "party_size", "status"):
            assert cur[k] == o[k], f"{o['reference']} {k} changed after a failed batch: {o[k]!r} -> {cur[k]!r}"


def mv(ref, **kw):
    return {"reference": ref, **kw}


@pytest.mark.ledger("S1-093", "S1-034")
def test_moves_requires_auth(mw, api):
    b = {"moves": [mv(mw.A["reference"], table_id="t_3")]}
    expect(api.moves(None, b), 401, "unauthenticated")
    expect(api.moves("not-a-real-token", b), 401, "unauthenticated")
    _unchanged(api, mw.ada, mw.A)


@pytest.mark.ledger("S1-093", "S1-037", "S1-025")
def test_moves_requires_idempotency_key(mw, api):
    b = {"moves": [mv(mw.A["reference"], table_id="t_3")]}
    expect(api.moves(mw.ada, b, key=None), 400, "missing_idempotency_key")
    expect(api.moves(mw.ada, b, key=""), 400, "missing_idempotency_key")
    expect(api.moves(mw.ada, b, key="m" * 256), 422, "validation_failed")
    _unchanged(api, mw.ada, mw.A)
    expect(api.moves(mw.ada, b, key="m" * 255), 201)


@pytest.mark.ledger("S1-094")
@pytest.mark.parametrize("bad", [
    {},
    {"moves": "x"},
    {"moves": {}},
    {"moves": None},
    {"moves": []},
    {"moves": [1]},
    {"moves": ["ABCDEF"]},
    {"moves": [{}]},
    {"moves": [{"reference": 123}]},
    {"moves": [{"reference": None}]},
    {"moves": [{"table_id": "t_3"}]},
    "NINE",
    "DUP",
], ids=["no-moves", "string", "object", "null", "empty", "number-item", "string-item", "empty-item",
        "ref-number", "ref-null", "ref-missing", "nine-items", "duplicate-refs"])
def test_moves_invalid_shape_422(mw, api, bad):
    if bad == "NINE":
        bad = {"moves": [mv(f"NOREF{i}") for i in range(9)]}
    elif bad == "DUP":
        bad = {"moves": [mv(mw.A["reference"], table_id="t_3"), mv(mw.A["reference"])]}
    expect(api.moves(mw.ada, bad), 422, "validation_failed")
    _unchanged(api, mw.ada, mw.A, mw.B)


@pytest.mark.ledger("S1-094", "S1-103", "S1-101")
def test_moves_eight_items_is_allowed(api):
    w = tk.World(api)
    refs = []
    for tid in ("t_1", "t_2", "t_3"):
        for hhmm in ("18:00", "19:30", "21:00"):
            refs.append(api.book(w.ada, "r_anker", tid, f"{FRI}T{hhmm}")["reference"])
    batch = {"moves": [mv(r) for r in refs[:8]]}
    r = api.moves(w.ada, batch)
    expect(r, 201)
    assert [x["reference"] for x in r.json["reservations"]] == refs[:8]


@pytest.mark.ledger("S1-020", "A-01")
@pytest.mark.parametrize("raw", ["not json", "[1, 2]", "", '{"moves": [', "null"])
def test_moves_unparseable_or_non_object_body_400(mw, api, raw):
    expect(api.moves(mw.ada, raw=raw), 400, "malformed_request")


@pytest.mark.ledger("S1-095")
def test_moves_unknown_or_foreign_reference_404(mw, api):
    bobs = api.book(mw.bob, "r_anker", "t_3", f"{THU}T21:00", 2)
    expect(api.moves(mw.ada, {"moves": [mv("ZZZZZZ99")]}), 404, "not_found")
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"], table_id="t_3"), mv(bobs["reference"])]}), 404, "not_found")
    _unchanged(api, mw.ada, mw.A)
    _unchanged(api, mw.bob, bobs)


@pytest.mark.ledger("S1-096")
def test_moves_across_restaurants_422(mw, api):
    H = api.book(mw.ada, "r_harbor", "h_1", f"{THU}T12:10", 2)
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"], table_id="t_3"), mv(H["reference"])]}), 422, "validation_failed")
    _unchanged(api, mw.ada, mw.A, H)


@pytest.mark.ledger("S1-097", "S1-102")
def test_moves_cancelled_booking_409(mw, api):
    expect(api.cancel(mw.ada, mw.A["reference"]), 200)
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"])]}), 409, "reservation_cancelled")
    expect(api.moves(mw.ada, {"moves": [mv(mw.B["reference"], table_id="t_3"), mv(mw.A["reference"], table_id="t_1")]}),
           409, "reservation_cancelled")
    _unchanged(api, mw.ada, mw.B)


@pytest.mark.ledger("S1-097", "S1-076", "A-12")
def test_moves_cutoff_409_including_noop_items(mw, api):
    expect(api.moves(mw.ada, {"moves": [mv("PAST01", party_size=3)]}), 409, "cutoff_passed")
    expect(api.moves(mw.ada, {"moves": [mv("PAST01")]}), 409, "cutoff_passed")
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"], table_id="t_3"), mv("PAST01")]}), 409, "cutoff_passed")
    _unchanged(api, mw.ada, mw.A)


@pytest.mark.ledger("S1-100", "S1-103", "S1-098", "A-15")
def test_moves_swap_tables(mw, api):
    r = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], table_id="t_2"), mv(mw.B["reference"], table_id="t_1")]})
    expect(r, 201)
    out = r.json["reservations"]
    assert [x["reference"] for x in out] == [mw.A["reference"], mw.B["reference"]]
    tk.assert_res(out[0], ANKER, "t_2", f"{THU}T19:00", 2, "confirmed")
    tk.assert_res(out[1], ANKER, "t_1", f"{THU}T19:00", 2, "confirmed")
    tk.same_identity(out[0], mw.A)
    tk.same_identity(out[1], mw.B)
    assert api.get_ok(mw.ada, mw.A["reference"])["table_id"] == "t_2"
    assert api.get_ok(mw.ada, mw.B["reference"])["table_id"] == "t_1"


@pytest.mark.ledger("S1-100")
def test_moves_chain(mw, api):
    r = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], table_id="t_2"), mv(mw.B["reference"], table_id="t_3")]})
    expect(r, 201)
    assert [x["table_id"] for x in r.json["reservations"]] == ["t_2", "t_3"]


@pytest.mark.ledger("S1-100")
def test_moves_into_slot_vacated_by_other_listed_booking(api):
    w = tk.World(api)
    A = api.book(w.ada, "r_anker", "t_1", f"{THU}T19:00")
    B = api.book(w.ada, "r_anker", "t_1", f"{THU}T20:30")
    r = api.moves(w.ada, {"moves": [mv(A["reference"], starts_at_local=f"{THU}T20:30"),
                                    mv(B["reference"], table_id="t_2")]})
    expect(r, 201)
    a, b = r.json["reservations"]
    tk.assert_res(a, ANKER, "t_1", f"{THU}T20:30", 2)
    tk.assert_res(b, ANKER, "t_2", f"{THU}T20:30", 2)


@pytest.mark.ledger("S1-100", "S1-102", "S1-043")
def test_moves_conflict_with_unlisted_booking_changes_nothing(mw, api):
    api.book(mw.bob, "r_anker", "t_3", f"{THU}T19:30", 2)
    key = tk.new_key()
    bad = {"moves": [mv(mw.B["reference"], party_size=3), mv(mw.A["reference"], table_id="t_3")]}
    expect(api.moves(mw.ada, bad, key=key), 409, "table_unavailable")
    _unchanged(api, mw.ada, mw.A, mw.B)
    assert "t_1" not in (api.free_tables("r_anker", f"{THU}T19:00") or [])
    # the retry key was not consumed: a different body under it is a first use
    ok = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], party_size=1)]}, key=key)
    expect(ok, 201)
    assert ok.json["reservations"][0]["party_size"] == 1


@pytest.mark.ledger("S1-100", "S1-102")
def test_moves_overlap_among_resulting_bookings(mw, api):
    bad = {"moves": [mv(mw.A["reference"], table_id="t_3"),
                     mv(mw.B["reference"], table_id="t_3", starts_at_local=f"{THU}T19:30")]}
    expect(api.moves(mw.ada, bad), 409, "table_unavailable")
    _unchanged(api, mw.ada, mw.A, mw.B)


@pytest.mark.ledger("S1-102", "S1-099")
def test_moves_late_item_failure_rolls_back_earlier_items(mw, api):
    C = api.book(mw.ada, "r_anker", "t_3", f"{THU}T19:00", 2)
    bad = {"moves": [mv(mw.A["reference"], starts_at_local=f"{THU}T21:00"),
                     mv(mw.B["reference"], party_size=4),
                     mv(C["reference"], starts_at_local=f"{THU}T19:15")]}
    expect(api.moves(mw.ada, bad), 422, "not_on_slot_grid")
    _unchanged(api, mw.ada, mw.A, mw.B, C)
    assert "t_1" in api.free_tables("r_anker", f"{THU}T21:00")


@pytest.mark.ledger("S1-099", "A-12")
def test_moves_errors_take_precedence_in_input_order(mw, api):
    A, B = mw.A["reference"], mw.B["reference"]
    # item 1 (capacity) before item 2 (unknown reference)
    expect(api.moves(mw.ada, {"moves": [mv(A, party_size=3), mv("ZZZZZZ99")]}), 422, "party_exceeds_capacity")
    expect(api.moves(mw.ada, {"moves": [mv("ZZZZZZ99"), mv(A, party_size=3)]}), 404, "not_found")
    # grid vs opening hours, in both orders
    expect(api.moves(mw.ada, {"moves": [mv(A, starts_at_local=f"{THU}T19:15"), mv(B, starts_at_local=f"{THU}T17:00")]}),
           422, "not_on_slot_grid")
    expect(api.moves(mw.ada, {"moves": [mv(B, starts_at_local=f"{THU}T17:00"), mv(A, starts_at_local=f"{THU}T19:15")]}),
           422, "outside_opening_hours")
    # cutoff in item 2 vs validation in item 1, both orders
    expect(api.moves(mw.ada, {"moves": [mv(A, party_size=0), mv("PAST01")]}), 422, "validation_failed")
    expect(api.moves(mw.ada, {"moves": [mv("PAST01"), mv(A, party_size=0)]}), 409, "cutoff_passed")
    _unchanged(api, mw.ada, mw.A, mw.B)


@pytest.mark.ledger("S1-099", "A-12")
def test_moves_cutoff_precedes_other_errors_of_same_item(mw, api):
    expect(api.moves(mw.ada, {"moves": [mv("PAST01", party_size=0)]}), 409, "cutoff_passed")
    expect(api.moves(mw.ada, {"moves": [mv("PAST01", starts_at_local=f"{THU}T19:15")]}), 409, "cutoff_passed")
    expect(api.moves(mw.ada, {"moves": [mv("PAST01", table_id="t_nope")]}), 409, "cutoff_passed")


@pytest.mark.ledger("S1-099", "A-12")
def test_moves_occupancy_reported_only_without_other_errors(mw, api):
    api.book(mw.bob, "r_anker", "t_3", f"{THU}T19:00", 2)
    bad = {"moves": [mv(mw.A["reference"], table_id="t_3"), mv(mw.B["reference"], starts_at_local=f"{THU}T19:15")]}
    expect(api.moves(mw.ada, bad), 422, "not_on_slot_grid")
    _unchanged(api, mw.ada, mw.A, mw.B)


@pytest.mark.ledger("S1-099", "A-12")
def test_moves_cancelled_reported_in_item_order(mw, api):
    expect(api.cancel(mw.ada, mw.B["reference"]), 200)
    expect(api.moves(mw.ada, {"moves": [mv(mw.B["reference"]), mv("ZZZZZZ99")]}), 409, "reservation_cancelled")
    expect(api.moves(mw.ada, {"moves": [mv("ZZZZZZ99"), mv(mw.B["reference"])]}), 404, "not_found")


@pytest.mark.ledger("S1-101", "S1-103")
def test_moves_noop_items_kept_and_returned(mw, api):
    r = api.moves(mw.ada, {"moves": [mv(mw.A["reference"]), mv(mw.B["reference"], table_id="t_3")]})
    expect(r, 201)
    a, b = r.json["reservations"]
    for k in ("reservation_id", "reference", "table_id", "party_size", "status", "starts_at_local",
              "starts_at", "ends_at", "created_at", "restaurant_id"):
        assert a[k] == mw.A[k], f"no-op item changed {k}"
    assert b["table_id"] == "t_3"
    assert "t_1" not in api.free_tables("r_anker", f"{THU}T19:00")


@pytest.mark.ledger("S1-098", "S1-011")
def test_moves_item_fields_merge_and_unknown_fields_ignored(mw, api):
    r = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], starts_at_local=f"{THU}T20:00", colour="blue",
                                        restaurant_id="r_harbor", reservation_id="hijack", status="cancelled")],
                           "comment": "ignored"})
    expect(r, 201)
    a = r.json["reservations"][0]
    tk.assert_res(a, ANKER, "t_1", f"{THU}T20:00", 2, "confirmed")
    tk.same_identity(a, mw.A)


@pytest.mark.ledger("S1-098", "S1-100")
def test_moves_table_and_party_change_together(mw, api):
    r = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], table_id="t_3", party_size=6)]})
    expect(r, 201)
    tk.assert_res(r.json["reservations"][0], ANKER, "t_3", f"{THU}T19:00", 6)


@pytest.mark.ledger("S1-100", "S1-079")
def test_moves_overlapping_own_old_interval(mw, api):
    r = api.moves(mw.ada, {"moves": [mv(mw.A["reference"], starts_at_local=f"{THU}T19:30")]})
    expect(r, 201)
    tk.assert_res(r.json["reservations"][0], ANKER, "t_1", f"{THU}T19:30", 2)


@pytest.mark.ledger("S1-098", "A-12")
def test_moves_item_field_types(mw, api):
    A = mw.A["reference"]
    expect(api.moves(mw.ada, {"moves": [mv(A, party_size="3")]}), 422, "validation_failed")
    expect(api.moves(mw.ada, {"moves": [mv(A, party_size=True)]}), 422, "validation_failed")
    expect(api.moves(mw.ada, {"moves": [mv(A, starts_at_local=f"{THU} 20:00")]}), 422, "validation_failed")
    expect(api.moves(mw.ada, {"moves": [mv(A, table_id=3)]}), 400, "malformed_request")
    expect(api.moves(mw.ada, {"moves": [mv(A, starts_at_local=1900)]}), 400, "malformed_request")
    expect(api.moves(mw.ada, {"moves": [mv(A, table_id="t_nope")]}), 404, "not_found")
    expect(api.moves(mw.ada, {"moves": [mv(A, starts_at_local="2026-03-29T02:30")]}), 422, "invalid_local_time")
    _unchanged(api, mw.ada, mw.A)


@pytest.mark.ledger("S1-104", "S1-039", "S1-044")
def test_moves_replay_returns_original_after_later_changes(mw, api):
    key = tk.new_key()
    b = {"moves": [mv(mw.A["reference"], table_id="t_3")]}
    first = api.moves(mw.ada, b, key=key)
    expect(first, 201)
    expect(api.cancel(mw.ada, mw.A["reference"]), 200)
    again = api.moves(mw.ada, b, key=key)
    expect(again, 200)
    assert again.json == first.json
    assert api.get_ok(mw.ada, mw.A["reference"])["status"] == "cancelled"
    assert "t_3" in api.free_tables("r_anker", f"{THU}T19:00")


@pytest.mark.ledger("S1-040", "A-01")
def test_moves_key_reuse_with_different_or_invalid_body_409(mw, api):
    key = tk.new_key()
    expect(api.moves(mw.ada, {"moves": [mv(mw.A["reference"], table_id="t_3")]}, key=key), 201)
    expect(api.moves(mw.ada, {"moves": [mv(mw.B["reference"], table_id="t_1")]}, key=key), 409, "idempotency_key_reuse")
    expect(api.moves(mw.ada, {"moves": []}, key=key), 409, "idempotency_key_reuse")
    expect(api.moves(mw.ada, {"moves": [mv("ZZZZZZ99")]}, key=key), 409, "idempotency_key_reuse")


@pytest.mark.ledger("S1-041", "S1-095")
def test_moves_key_scoped_per_user(mw, api):
    key = "batch-key"
    ada_body = {"moves": [mv(mw.A["reference"], party_size=1)]}
    expect(api.moves(mw.ada, ada_body, key=key), 201)
    # Bob sending Ada's body under the same key is Bob's own first use, not a replay: not his booking -> 404
    expect(api.moves(mw.bob, ada_body, key=key), 404, "not_found")
    bobs = api.book(mw.bob, "r_anker", "t_3", f"{THU}T21:00", 2)
    r = api.moves(mw.bob, {"moves": [mv(bobs["reference"], party_size=1)]}, key=key)
    expect(r, 201)
    assert r.json["reservations"][0]["reference"] == bobs["reference"]
