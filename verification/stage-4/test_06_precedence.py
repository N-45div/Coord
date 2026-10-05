"""Error precedence: spec §5/§7 plus Coordinator decisions A-01, A-02, A-04, A-05, A-11."""
import pytest

import tk
from tk import MON, PAST_THU, THU, body, expect

GOOD = body("r_anker", "t_1", f"{THU}T19:00", 2)
PAST = tk.seed("res_past", "PASTA1", "u_ada", "r_anker", "t_1", f"{PAST_THU}T19:00", 2)


@pytest.fixture
def pw(api):
    return tk.World(api, tk.fixture(reservations=[PAST]))


# ---- create: request level (A-01) --------------------------------------------------------

@pytest.mark.ledger("A-01", "S1-034")
def test_create_auth_first(pw, api):
    expect(api.create(None, raw="garbage", key=None), 401, "unauthenticated")
    expect(api.create("bogus-token", {**GOOD, "party_size": 0}, key="k" * 300), 401, "unauthenticated")


@pytest.mark.ledger("A-01", "S1-020")
@pytest.mark.parametrize("raw", ["garbage", "", "[1,2]", '"text"', "42", "null", '{"restaurant_id": '])
def test_create_unparseable_or_non_object_before_key_check(pw, api, raw):
    expect(api.create(pw.ada, raw=raw, key=None), 400, "malformed_request")
    expect(api.create(pw.ada, raw=raw), 400, "malformed_request")


@pytest.mark.ledger("A-01", "S1-037")
def test_missing_key_before_field_validation_and_resources(pw, api):
    expect(api.create(pw.ada, {"party_size": 0}, key=None), 400, "missing_idempotency_key")
    expect(api.create(pw.ada, {**GOOD, "restaurant_id": "r_nowhere"}, key=None), 400, "missing_idempotency_key")
    expect(api.create(pw.ada, {**GOOD, "table_id": 5}, key=None), 400, "missing_idempotency_key")


@pytest.mark.ledger("A-01", "S1-025")
def test_key_length_before_field_validation_and_resources(pw, api):
    expect(api.create(pw.ada, {**GOOD, "restaurant_id": "r_nowhere"}, key="k" * 256), 422, "validation_failed")
    expect(api.create(pw.ada, {**GOOD, "table_id": 5}, key="k" * 256), 422, "validation_failed")


# ---- create: rule order (A-02) -----------------------------------------------------------

CASES = [
    # (description, body, status, code)
    ("wrong type beats invalid party", {**GOOD, "restaurant_id": 5, "party_size": 0}, 400, "malformed_request"),
    ("wrong type table beats unknown restaurant", {**GOOD, "restaurant_id": "r_nowhere", "table_id": 9}, 400, "malformed_request"),
    ("starts_at_local wrong type", {**GOOD, "starts_at_local": 1900}, 400, "malformed_request"),
    ("missing field beats unknown restaurant", {"restaurant_id": "r_nowhere", "starts_at_local": f"{THU}T19:00", "party_size": 2}, 422, "validation_failed"),
    ("invalid party beats unknown restaurant", {**GOOD, "restaurant_id": "r_nowhere", "party_size": 0}, 422, "validation_failed"),
    ("bad local format beats unknown table", {**GOOD, "table_id": "t_nope", "starts_at_local": f"{THU}T19:00:00"}, 422, "validation_failed"),
    ("unknown table beats grid and capacity", {**GOOD, "table_id": "t_nope", "starts_at_local": f"{THU}T19:15", "party_size": 9}, 404, "not_found"),
    ("foreign table beats hours", {**GOOD, "table_id": "h_1", "starts_at_local": f"{MON}T19:00"}, 404, "not_found"),
    ("unknown restaurant", {**GOOD, "restaurant_id": "r_nowhere"}, 404, "not_found"),
    ("gap beats closed day", {**GOOD, "starts_at_local": "2026-03-29T02:30"}, 422, "invalid_local_time"),
    ("hours beat grid", {**GOOD, "starts_at_local": f"{THU}T17:15"}, 422, "outside_opening_hours"),
    ("closed day beats capacity", {**GOOD, "starts_at_local": f"{MON}T19:00", "party_size": 5}, 422, "outside_opening_hours"),
    ("end after close beats capacity", {**GOOD, "starts_at_local": f"{THU}T22:00", "party_size": 5}, 422, "outside_opening_hours"),
    ("grid beats capacity", {**GOOD, "starts_at_local": f"{THU}T19:15", "party_size": 5}, 422, "not_on_slot_grid"),
    ("capacity beats occupancy", {**GOOD, "party_size": 5}, 422, "party_exceeds_capacity"),
]


@pytest.mark.ledger("A-02", "S1-058", "S1-059", "S1-060", "S1-061", "S1-063", "S1-064", "S1-065")
@pytest.mark.parametrize("desc,b,status,code", CASES, ids=[c[0] for c in CASES])
def test_create_rule_precedence(pw, api, desc, b, status, code):
    api.book(pw.bob, "r_anker", "t_1", f"{THU}T19:00")  # occupancy conflict for GOOD
    expect(api.create(pw.ada, b), status, code)
    assert api.list(pw.ada) == [api.get_ok(pw.ada, "PASTA1")]


# ---- PATCH order (A-04) ------------------------------------------------------------------

@pytest.mark.ledger("A-04", "S1-078", "S1-020")
def test_patch_precedence_request_level(pw, api):
    mine = api.book(pw.ada, "r_anker", "t_2", f"{THU}T19:00")
    bobs = api.book(pw.bob, "r_anker", "t_3", f"{THU}T19:00")
    expect(api.patch(None, mine["reference"], raw="garbage"), 401, "unauthenticated")
    expect(api.patch(pw.ada, "NOSUCH1", raw="garbage"), 400, "malformed_request")
    expect(api.patch(pw.ada, "NOSUCH1", {"party_size": 0}), 404, "not_found")
    expect(api.patch(pw.ada, bobs["reference"], {"party_size": 0}), 404, "not_found")
    expect(api.patch(pw.ada, bobs["reference"], {"table_id": 7}), 404, "not_found")
    expect(api.patch(pw.ada, mine["reference"], raw="[1]"), 400, "malformed_request")


@pytest.mark.ledger("A-04", "S1-077", "S1-076")
def test_patch_precedence_state_rules(pw, api):
    mine = api.book(pw.ada, "r_anker", "t_2", f"{THU}T19:00")
    expect(api.cancel(pw.ada, mine["reference"]), 200)
    ref = mine["reference"]
    expect(api.patch(pw.ada, ref, {"table_id": 7}), 400, "malformed_request")          # type before cancelled
    expect(api.patch(pw.ada, ref, {"party_size": 0}), 409, "reservation_cancelled")    # cancelled before validation
    expect(api.patch(pw.ada, ref, {"table_id": "t_nope"}), 409, "reservation_cancelled")
    expect(api.patch(pw.ada, ref, {}), 409, "reservation_cancelled")                   # no-op still checked
    expect(api.patch(pw.ada, "PASTA1", {"starts_at_local": 5}), 400, "malformed_request")
    expect(api.patch(pw.ada, "PASTA1", {"party_size": 0}), 409, "cutoff_passed")      # cutoff before validation
    expect(api.patch(pw.ada, "PASTA1", {"table_id": "t_nope"}), 409, "cutoff_passed")
    expect(api.patch(pw.ada, "PASTA1", {"starts_at_local": f"{THU}T19:15"}), 409, "cutoff_passed")
    expect(api.patch(pw.ada, "PASTA1", {}), 409, "cutoff_passed")


PATCH_CASES = [
    ("party wrong type is 422", {"party_size": "4"}, 422, "validation_failed"),
    ("bad local format", {"starts_at_local": f"{THU}T20:00Z"}, 422, "validation_failed"),
    ("unknown table beats grid", {"table_id": "t_nope", "starts_at_local": f"{THU}T19:15"}, 404, "not_found"),
    ("foreign table", {"table_id": "h_2"}, 404, "not_found"),
    ("gap beats hours", {"starts_at_local": "2026-03-29T02:00"}, 422, "invalid_local_time"),
    ("hours beat grid", {"starts_at_local": f"{THU}T22:15"}, 422, "outside_opening_hours"),
    ("grid beats capacity", {"starts_at_local": f"{THU}T20:15", "party_size": 5}, 422, "not_on_slot_grid"),
    ("capacity on merged result", {"party_size": 5}, 422, "party_exceeds_capacity"),
    ("capacity beats occupancy", {"table_id": "t_1", "party_size": 3}, 422, "party_exceeds_capacity"),
    ("occupancy", {"table_id": "t_1", "party_size": 2}, 409, "table_unavailable"),
]


@pytest.mark.ledger("A-04", "S1-075", "S1-079")
@pytest.mark.parametrize("desc,b,status,code", PATCH_CASES, ids=[c[0] for c in PATCH_CASES])
def test_patch_rule_precedence_and_no_change_on_failure(pw, api, desc, b, status, code):
    api.book(pw.bob, "r_anker", "t_1", f"{THU}T19:00")
    mine = api.book(pw.ada, "r_anker", "t_2", f"{THU}T19:00", 4)
    expect(api.patch(pw.ada, mine["reference"], b), status, code)
    assert api.get_ok(pw.ada, mine["reference"]) == mine
    assert "t_2" not in api.free_tables("r_anker", f"{THU}T19:00")


# ---- cancel order (A-05) -----------------------------------------------------------------

@pytest.mark.ledger("A-05", "S1-073", "S1-034")
def test_cancel_precedence(pw, api):
    bobs = api.book(pw.bob, "r_anker", "t_3", f"{THU}T19:00")
    expect(api.cancel(None, bobs["reference"]), 401, "unauthenticated")
    expect(api.cancel("bogus", "NOSUCH1"), 401, "unauthenticated")
    expect(api.cancel(pw.ada, bobs["reference"]), 404, "not_found")
    expect(api.cancel(pw.ada, "NOSUCH1"), 404, "not_found")
    expect(api.cancel(pw.ada, "PASTA1"), 409, "cutoff_passed")
    assert api.get_ok(pw.bob, bobs["reference"])["status"] == "confirmed"


# ---- availability (A-11) -----------------------------------------------------------------

@pytest.mark.ledger("A-11", "S1-049")
def test_availability_params_before_unknown_restaurant(pw, api):
    expect(api.avail("r_nowhere", party=2), 422, "validation_failed")
    expect(api.avail("r_nowhere", THU, "abc"), 422, "validation_failed")
    expect(api.avail("r_nowhere", "2027-02-30", 2), 422, "validation_failed")
    expect(api.avail("r_nowhere", THU, 2), 404, "not_found")
