"""Applying seating plans (stage-4 "Seating changes after a table closure"; ledger S4-011..S4-020, A-37,
A-38, A-42)."""
import pytest

import tk
import ui
from tk import REP, MGR, expect
from test_50_replan import D, iso, seed, world, all_bookings, expected_plan, preview



def plan(api, w, table_id, frm_local, to_local, rid="r_rep", closures=()):
    r, cons, orc, f, t = preview(api, w, table_id, frm_local, to_local, rid, closures)
    expect(r, 201)
    return r.json


@pytest.fixture
def aw(api):
    seeds = [seed("RA0001", ["r_3"], f"{D}T19:00", 4), seed("RB0002", ["r_4"], f"{D}T19:30", 3, "u_bob"),
             seed("RC0003", ["r_5"], f"{D}T15:00", 2)]
    return world(api, seeds)


@pytest.mark.ledger("S4-015", "S4-017", "A-42", "S4-010")
def test_apply_moves_bookings_and_records_history(aw, api):
    before = {r["reference"]: r for r in all_bookings(api, aw)}
    p = plan(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00")
    rev0 = p["restaurant_revision"]
    r = api.apply(aw.mgr, "r_rep", p["plan_id"])
    expect(r, 201)
    j = r.json
    assert j["plan_id"] == p["plan_id"] and j["restaurant_revision"] == rev0 + 1
    assert [x["reference"] for x in j["reservations"]] == [a["reference"] for a in p["assignments"]]
    for res, a in zip(j["reservations"], p["assignments"]):
        tk.assert_res(res)
        old = before[res["reference"]]
        assert res["table_ids"] == a["table_ids"]
        for k in ("starts_at", "ends_at", "party_size", "accepted_terms", "starts_at_local", "reservation_id"):
            assert res[k] == old[k], f"{k} changed by a repair"
        if a["changed"]:
            assert res["revision"] == old["revision"] + 1
            es = api.entries(aw.tok("u_ada" if res["reference"] == "RA0001" else "u_bob"), res["reference"])
            last = es[-1]
            assert last["event"] == "reassigned" and last["plan_id"] == p["plan_id"]
            assert last["changes"] == [{"field": "table_ids", "from": old["table_ids"], "to": a["table_ids"]}]
            assert last["revision"] == res["revision"]
            assert last["accepted_terms"] == old["accepted_terms"]
            assert len(es) == 2
        else:
            assert res == old
            assert len(api.entries(aw.tok("u_bob"), res["reference"])) == 1
    assert api.get_ok(aw.ada, "RA0001")["table_ids"] == ["r_1", "r_2"]
    assert api.get_ok(aw.ada, "RC0003") == before["RC0003"]  # not considered
    assert api.rrev(aw.mgr, "r_rep", "r_6") == rev0 + 1


@pytest.mark.ledger("S4-018", "S3-003")
def test_closure_blocks_availability_creates_amendments_and_explains(aw, api):
    p = plan(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00")
    expect(api.apply(aw.mgr, "r_rep", p["plan_id"]), 201)
    s = [x for x in api.avail("r_rep", D, 1, extra={"explain": "true"}).json["slots"]
         if x["starts_at_local"] == f"{D}T17:00"][0]
    assert "r_3" not in s["available_table_ids"]
    assert all("r_3" not in o["table_ids"] for o in s["available_options"])
    e3 = [e for e in s["explain"] if e["table_id"] == "r_3"][0]
    assert [r["holds"] for r in e3["rules"]] == [True, False] and e3["available"] is False
    later = [x for x in api.slots("r_rep", D, 1) if x["starts_at_local"] == f"{D}T21:00"][0]
    assert "r_3" in later["available_table_ids"], "the closure is half-open [from, to)"
    expect(api.create(aw.bob, tk.body("r_rep", "r_3", f"{D}T20:30", 2)), 409, "table_unavailable")
    expect(api.create(aw.bob, {"restaurant_id": "r_rep", "table_ids": ["r_3", "r_4"],
                               "starts_at_local": f"{D}T12:00", "party_size": 2}), 201)  # before the closure
    expect(api.patch(aw.ada, "RC0003", {"table_id": "r_3", "starts_at_local": f"{D}T17:00"}), 409, "table_unavailable")
    expect(api.create(aw.bob, tk.body("r_rep", "r_3", f"{D}T21:00", 2)), 201)


@pytest.mark.ledger("S4-014", "S4-013", "A-37")
def test_apply_idempotency_already_applied_and_stale(aw, api):
    p = plan(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00")
    key = tk.new_key()
    first = expect(api.apply(aw.mgr, "r_rep", p["plan_id"], key=key), 201)
    expect(api.apply(aw.mgr, "r_rep", p["plan_id"]), 409, "plan_already_applied")
    expect(api.patch(aw.ada, "RA0001", {"party_size": 3}), 200)  # later change
    again = api.apply(aw.mgr, "r_rep", p["plan_id"], key=key)
    expect(again, 200)
    assert again.json == first
    # stale: any restaurant revision change after the preview
    q = plan(api, aw, "r_5", f"{D}T14:00", f"{D}T16:00")
    api.book(aw.bob, "r_rep", "r_1", f"{D}T12:00", 1)
    before = all_bookings(api, aw)
    expect(api.apply(aw.mgr, "r_rep", q["plan_id"]), 409, "stale_plan")
    assert all_bookings(api, aw) == before
    expect(api.create(aw.bob, tk.body("r_rep", "r_5", f"{D}T17:00", 2)), 201)  # no closure recorded


@pytest.mark.ledger("S4-013")
def test_closure_at_another_restaurant_does_not_invalidate(api):
    seeds = [seed("RA0001", ["r_3"], f"{D}T19:00", 4),
             {**seed("RZ0001", ["r_3"], f"{D}T19:00", 4), "restaurant_id": "r_rep2"}]
    w = world(api, seeds)
    p1 = plan(api, w, "r_3", f"{D}T18:00", f"{D}T21:00")
    p2 = plan(api, w, "r_3", f"{D}T18:00", f"{D}T21:00", rid="r_rep2")
    expect(api.apply(w.mgr, "r_rep2", p2["plan_id"]), 201)
    expect(api.apply(w.mgr, "r_rep", p1["plan_id"]), 201)


@pytest.mark.ledger("S4-011", "S4-012", "A-37")
def test_apply_permissions_and_unknown_plans(aw, api):
    p = plan(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00")
    expect(api.apply(None, "r_rep", p["plan_id"]), 401, "unauthenticated")
    expect(api.apply(aw.ada, "r_rep", p["plan_id"]), 403, "forbidden")
    expect(api.apply(aw.mgr, "r_nowhere", p["plan_id"]), 404, "not_found")
    expect(api.apply(aw.mgr, "r_rep", "no-such-plan"), 404, "not_found")
    expect(api.apply(aw.mgr, "r_rep2", p["plan_id"]), 404, "not_found")
    expect(api.apply(aw.mgr, "r_rep", p["plan_id"], key=None), 400, "missing_idempotency_key")
    expect(api.apply(aw.mgr, "r_rep", p["plan_id"], raw="nope"), 400, "malformed_request")
    expect(api.apply(aw.mgr, "r_rep", p["plan_id"]), 201)


@pytest.mark.ledger("S4-016")
def test_concurrent_applies_one_winner_no_partial_moves(aw, api):
    p = plan(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00")
    res = tk.parallel([(lambda a: a.apply(aw.mgr, "r_rep", p["plan_id"])) for _ in range(10)])
    tk.assert_all_responses(res)
    assert sum(1 for r in res if r.status == 201) == 1, [r.status for r in res]
    for r in res:
        if r.status != 201:
            assert r.status == 409 and r.json["error"]["code"] in ("plan_already_applied", "stale_plan"), r
    cur = {r["reference"]: r["table_ids"] for r in all_bookings(api, aw)}
    for a in p["assignments"]:
        assert cur[a["reference"]] == a["table_ids"]
    assert api.rrev(aw.mgr, "r_rep", "r_6") == p["restaurant_revision"] + 1


@pytest.mark.ledger("S4-005", "S4-018")
def test_later_plans_respect_applied_closures(aw, api):
    p = plan(api, aw, "r_4", f"{D}T18:00", f"{D}T22:00")
    expect(api.apply(aw.mgr, "r_rep", p["plan_id"]), 201)
    closures = [("r_4", iso(f"{D}T18:00"), iso(f"{D}T22:00"))]
    r, cons, orc, f, t = preview(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00", closures=closures)
    from test_50_replan import check_plan
    if orc == (None, None):
        expect(r, 409, "no_feasible_plan")
    else:
        check_plan(r, cons, orc, "r_3", f, t)
        for a in r.json["assignments"]:
            assert "r_4" not in a["table_ids"]


@pytest.mark.ledger("A-38", "S4-018", "S4-010")
def test_apply_empty_plan_records_closure(api):
    w = world(api, [])
    p = plan(api, w, "r_2", f"{D}T12:00", f"{D}T15:00")
    r = api.apply(w.mgr, "r_rep", p["plan_id"])
    expect(r, 201)
    assert r.json["reservations"] == [] and r.json["restaurant_revision"] == p["restaurant_revision"] + 1
    expect(api.create(w.ada, tk.body("r_rep", "r_2", f"{D}T13:00", 2)), 409, "table_unavailable")


@pytest.mark.ledger("S4-019", "S3-043")
def test_repair_moves_series_occurrences_keeping_flags(api):
    w = world(api, [])
    anchor = api.book(w.ada, "r_rep", "r_3", f"{D}T19:00", 4)
    s = expect(api.series(w.ada, {"anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}), 201)
    o2 = s["occurrences"][2]["reference"]
    expect(api.patch(w.ada, o2, {"party_size": 3}), 200)  # occurrence 2 becomes an exception
    g0 = expect(api.get_series(w.ada, s["series_id"]), 200)
    d1 = s["occurrences"][1]["reservation"]["starts_at_local"][:10]
    p = plan(api, w, "r_3", f"{d1}T18:00", f"{d1}T21:00")
    expect(api.apply(w.mgr, "r_rep", p["plan_id"]), 201)
    p2 = plan(api, w, "r_3", "2027-07-01T18:00", "2027-07-01T21:00")
    expect(api.apply(w.mgr, "r_rep", p2["plan_id"]), 201)
    g = expect(api.get_series(w.ada, s["series_id"]), 200)
    assert g["revision"] == g0["revision"] + 2, "each application that moved a member adds one series revision"
    assert [o["exception"] for o in g["occurrences"]] == [o["exception"] for o in g0["occurrences"]]
    for o, o0 in zip(g["occurrences"], g0["occurrences"]):
        assert o["reference"] == o0["reference"]
        assert o["reservation"]["starts_at_local"] == o0["reservation"]["starts_at_local"]
        assert o["reservation"]["accepted_terms"] == o0["reservation"]["accepted_terms"]
    assert g["occurrences"][1]["reservation"]["table_ids"] != ["r_3"]


@pytest.mark.ledger("S4-030", "S1-088")
def test_plans_closures_and_receipts_survive_export_import(aw, api):
    p = plan(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00")
    key = tk.new_key()
    first = expect(api.apply(aw.mgr, "r_rep", p["plan_id"], key=key), 201)
    q = plan(api, aw, "r_6", f"{D}T12:00", f"{D}T13:00")
    e = api.export()
    api.reset(tk.fixture())
    expect(api.import_(e), 204)
    again = api.apply(aw.mgr, "r_rep", p["plan_id"], key=key)
    expect(again, 200)
    assert again.json == first
    expect(api.create(aw.bob, tk.body("r_rep", "r_3", f"{D}T20:30", 2)), 409, "table_unavailable")
    expect(api.apply(aw.mgr, "r_rep", q["plan_id"]), 201)  # stored preview survives; no revision change since


@pytest.mark.ledger("S4-020", "S2-019", "S2-006")
def test_screens_reflect_an_applied_plan(aw, api, browser):
    p = plan(api, aw, "r_3", f"{D}T18:00", f"{D}T21:00")
    expect(api.apply(aw.mgr, "r_rep", p["plan_id"]), 201)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(ui.WAIT)
    try:
        ui.login(page, tk.ADA["email"], tk.ADA["password"])
        page.goto(ui.url("/lookup"))
        ui.T(page, "lookup-reference-input").fill("RA0001")
        ui.T(page, "lookup-submit").click()
        ui.wait_visible(page, "reservation-detail")
        tables = ui.text(page, "reservation-tables")
        assert "Eins" in tables and "Zwei" in tables and "Drei" not in tables, tables
        ui.search(page, "r_rep", D, 2)
        ui.wait_cell(page, "slot-r_3-19:00", False)
        ui.wait_cell(page, "slot-r_3-21:00", True)
    finally:
        ctx.close()
