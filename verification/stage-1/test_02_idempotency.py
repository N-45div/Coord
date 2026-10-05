"""Idempotency (spec §7) for POST /reservations; batch receipts are in test_03_moves.py."""
import json

import pytest

import tk
from tk import THU, body, expect

B1 = body("r_anker", "t_2", f"{THU}T19:00", 2)
B2 = body("r_anker", "t_1", f"{THU}T19:00", 2)


@pytest.mark.ledger("S1-037", "S1-066")
def test_missing_or_empty_key_is_400(w, api):
    expect(api.create(w.ada, B1, key=None), 400, "missing_idempotency_key")
    expect(api.create(w.ada, B1, key=""), 400, "missing_idempotency_key")
    assert api.list(w.ada) == []
    assert "t_2" in api.free_tables("r_anker", f"{THU}T19:00")


@pytest.mark.ledger("S1-025", "S1-038")
def test_key_length_bounds(w, api):
    expect(api.create(w.ada, B1, key="k" * 256), 422, "validation_failed")
    assert api.list(w.ada) == []
    expect(api.create(w.ada, B1, key="k" * 255), 201)
    expect(api.create(w.ada, B2, key="x"), 201)


@pytest.mark.ledger("S1-038", "S1-039")
def test_first_use_201_then_replay_200_identical(w, api):
    key = tk.new_key()
    first = api.create(w.ada, B1, key=key)
    expect(first, 201)
    again = api.create(w.ada, B1, key=key)
    expect(again, 200)
    assert again.json == first.json
    # same JSON value with different key order and whitespace is the same body
    raw = '{ "party_size" : 2,\n "starts_at_local":"%sT19:00",  "table_id":"t_2", "restaurant_id" : "r_anker" }' % THU
    third = api.create(w.ada, raw=raw, key=key)
    expect(third, 200)
    assert third.json == first.json
    assert len(api.list(w.ada)) == 1


@pytest.mark.ledger("S1-040")
@pytest.mark.parametrize("other", [
    B2,
    {**B1, "party_size": -5},              # would be 422
    {**B1, "restaurant_id": "r_nowhere"},  # would be 404
    {},                                    # would be 422 (missing fields)
    {**B1, "party_size": "x"},             # would be 422
    {**B1, "table_id": 7},                 # would be 400 (wrong type)
    {**B1, "note": "window seat"},         # different JSON value (extra field)
], ids=["valid-other", "bad-party", "unknown-restaurant", "empty", "party-string", "table-wrong-type", "extra-field"])
def test_same_key_different_body_is_409_even_if_new_body_invalid(w, api, other):
    key = tk.new_key()
    expect(api.create(w.ada, B1, key=key), 201)
    expect(api.create(w.ada, other, key=key), 409, "idempotency_key_reuse")
    assert len(api.list(w.ada)) == 1


@pytest.mark.ledger("S1-041")
def test_key_scoped_per_user(w, api):
    key = "shared-key-1"
    a = api.create(w.ada, B1, key=key)
    expect(a, 201)
    # Bob's identical request is Bob's first use, not a replay of Ada's: the table is taken.
    expect(api.create(w.bob, B1, key=key), 409, "table_unavailable")
    # Bob's different body is not a reuse conflict either.
    b = api.create(w.bob, B2, key=key)
    expect(b, 201)
    assert b.json["reference"] != a.json["reference"]
    r = api.create(w.ada, B1, key=key)
    expect(r, 200)
    assert r.json == a.json
    assert [x["reference"] for x in api.list(w.bob)] == [b.json["reference"]]


@pytest.mark.ledger("S1-042", "A-06")
def test_same_key_on_different_path_is_independent(w, api):
    key = tk.new_key()
    created = api.create(w.ada, B1, key=key)
    expect(created, 201)
    ref = created.json["reference"]
    # same key + same body on /reservation-moves: a new request there (invalid shape -> 422), not a replay/reuse
    expect(api.moves(w.ada, B1, key=key), 422, "validation_failed")
    # same key + a valid moves body: succeeds normally
    m = api.moves(w.ada, {"moves": [{"reference": ref, "party_size": 3}]}, key=key)
    expect(m, 201)
    assert m.json["reservations"][0]["party_size"] == 3
    # the original create receipt is untouched
    r = api.create(w.ada, B1, key=key)
    expect(r, 200)
    assert r.json == created.json


@pytest.mark.ledger("S1-043", "S1-066", "A-07")
def test_key_reusable_after_4xx(w, api):
    k1 = tk.new_key()
    expect(api.create(w.ada, {**B1, "party_size": 0}, key=k1), 422, "validation_failed")
    expect(api.create(w.ada, B1, key=k1), 201)
    k2 = tk.new_key()
    expect(api.create(w.ada, {**B1, "restaurant_id": "r_nowhere"}, key=k2), 404, "not_found")
    expect(api.create(w.ada, B2, key=k2), 201)


@pytest.mark.ledger("S1-043", "S1-066")
def test_failed_conflict_key_becomes_first_use_after_slot_frees(w, api):
    held = api.book(w.bob, "r_anker", "t_3", f"{THU}T20:00", 3)
    k = tk.new_key()
    b = body("r_anker", "t_3", f"{THU}T20:00", 3)
    expect(api.create(w.ada, b, key=k), 409, "table_unavailable")
    assert api.list(w.ada) == []
    expect(api.cancel(w.bob, held["reference"]), 200)
    r = api.create(w.ada, b, key=k)
    expect(r, 201)
    tk.assert_res(r.json, tk.ANKER, "t_3", f"{THU}T20:00", 3, "confirmed")


@pytest.mark.ledger("S1-044", "S1-039")
def test_replay_returns_original_after_amend_and_cancel(w, api):
    key = tk.new_key()
    orig = expect(api.create(w.ada, B1, key=key), 201)
    expect(api.patch(w.ada, orig["reference"], {"party_size": 3}), 200)
    r = api.create(w.ada, B1, key=key)
    expect(r, 200)
    assert r.json == orig
    assert api.get_ok(w.ada, orig["reference"])["party_size"] == 3  # replay changed nothing
    expect(api.cancel(w.ada, orig["reference"]), 200)
    r = api.create(w.ada, B1, key=key)
    expect(r, 200)
    assert r.json == orig and r.json["status"] == "confirmed"
    cur = api.get_ok(w.ada, orig["reference"])
    assert cur["status"] == "cancelled"
    assert "t_2" in api.free_tables("r_anker", f"{THU}T19:00")  # the replay did not re-book
    assert len(api.list(w.ada)) == 1


@pytest.mark.ledger("S1-046", "S1-035")
def test_replay_recognised_across_tokens_of_same_user(w, api):
    t1 = w.ada
    t2 = api.token(tk.ADA["email"], tk.ADA["password"])
    key = tk.new_key()
    first = api.create(t1, B1, key=key)
    expect(first, 201)
    second = api.create(t2, B1, key=key)
    expect(second, 200)
    assert second.json == first.json
    expect(api.create(t2, B2, key=key), 409, "idempotency_key_reuse")


@pytest.mark.ledger("S1-039")
def test_replay_body_value_equality_not_bytes(w, api):
    key = tk.new_key()
    first = api.create(w.ada, B1, key=key)
    expect(first, 201)
    compact = json.dumps(B1, separators=(",", ":"), sort_keys=True)
    r = api.create(w.ada, raw=compact, key=key)
    expect(r, 200)
    assert r.json == first.json
