"""Availability explanations (stage-3 "Availability explanations"; ledger S3-001..S3-006)."""
import pytest

import tk
from tk import POL, MGR, THU, MON, expect

D_P0 = "2027-06-17"   # Thursday, policy 0
D_P1 = "2027-07-15"   # Thursday, after the policy below takes effect


@pytest.fixture
def pw(api):
    return tk.World(api, tk.fixture(users=(tk.ADA, tk.BOB, MGR), restaurants=(POL, tk.ANKER)))


def explain_slots(api, rid, date, party, value="true"):
    r = api.avail(rid, date, party, extra={"explain": value})
    expect(r, 200)
    return r.json["slots"]


def check_slot(slot, rest_tables):
    ex = slot["explain"]
    assert [e["table_id"] for e in ex] == [t["id"] for t in rest_tables], "every table once, fixture order"
    avail = []
    for e in ex:
        assert [r["rule"] for r in e["rules"]] == ["capacity", "no_overlap"], e
        both = all(r["holds"] is True for r in e["rules"])
        assert all(type(r["holds"]) is bool for r in e["rules"]), e
        assert e["available"] is both, f"available must be true exactly when both rules hold: {e}"
        assert type(e["policy_version"]) is int, e
        if both:
            avail.append(e["table_id"])
    assert avail == slot["available_table_ids"], (avail, slot["available_table_ids"])


@pytest.mark.ledger("S3-001")
@pytest.mark.parametrize("value", ["false", "1", "", "TRUE", "True", "yes", "0"])
def test_explain_only_accepts_true(pw, api, value):
    expect(api.avail("r_pol", D_P0, 2, extra={"explain": value}), 422, "validation_failed")


@pytest.mark.ledger("S3-002")
def test_without_explain_no_explanation_fields(pw, api):
    for s in api.slots("r_pol", D_P0, 2):
        assert "explain" not in s, s


@pytest.mark.ledger("S3-003", "S3-004", "S3-006")
def test_explain_shape_rules_and_consistency(pw, api):
    api.book(pw.bob, "r_pol", "p_1", f"{D_P0}T19:00", 2)
    slots = explain_slots(api, "r_pol", D_P0, 3)
    assert slots
    for s in slots:
        check_slot(s, POL["tables"])
        for e in s["explain"]:
            assert e["policy_version"] == 0
    at19 = next(s for s in slots if s["starts_at_local"] == f"{D_P0}T19:00")
    p1 = at19["explain"][0]
    # p_1: capacity 2 < party 3 and occupied -> both rules false (S3-004)
    assert [r["holds"] for r in p1["rules"]] == [False, False], p1
    at22 = next(s for s in slots if s["starts_at_local"] == f"{D_P0}T21:30")
    assert [r["holds"] for r in at22["explain"][0]["rules"]] == [False, True]
    assert at19["available_table_ids"] == ["p_2", "p_3"]


@pytest.mark.ledger("S3-005")
def test_closed_day_and_slot_with_no_table(pw, api):
    r = api.avail("r_anker", MON, 2, extra={"explain": "true"})
    expect(r, 200)
    assert r.json["slots"] == []
    slots = explain_slots(api, "r_pol", D_P0, 7)  # nobody seats 7
    assert slots and all(s["available_table_ids"] == [] for s in slots)
    for s in slots:
        check_slot(s, POL["tables"])
        assert all(e["available"] is False for e in s["explain"])


@pytest.mark.ledger("S3-006", "S3-021", "S3-022")
def test_explain_uses_selected_policy_capacity_and_version(pw, api):
    expect(api.publish(pw.tok("u_mgr"), "r_pol", tk.policy("2027-07-01", caps={"p_1": 3, "p_2": 4, "p_3": 8})), 201)
    slots = explain_slots(api, "r_pol", D_P1, 3)
    assert [s["starts_at_local"][11:] for s in slots] == [f"{h:02d}:00" for h in range(12, 21)]
    for s in slots:
        check_slot(s, POL["tables"])
        assert all(e["policy_version"] == 1 for e in s["explain"])
        assert s["available_table_ids"] == ["p_1", "p_2", "p_3"]  # p_1 seats 3 under policy 1
    before = explain_slots(api, "r_pol", D_P0, 3)
    assert all(e["policy_version"] == 0 for s in before for e in s["explain"])
    assert all(s["available_table_ids"] == ["p_2", "p_3"] for s in before)
